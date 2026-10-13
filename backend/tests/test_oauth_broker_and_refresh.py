# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit and integration tests for OAuth 2.0 PKCE Broker & Versioned Token Refresh (AU-51)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.connectors.oauth import (
    build_authorization_url,
    create_oauth_state,
    generate_pkce_pair,
    load_connection_tokens,
    refresh_connection_token,
    resolve_redirect_uri,
    store_connection_tokens,
    verify_oauth_state,
    verify_pkce_challenge,
)
from carefold.db.base import Base
from carefold.db.models import Connection, Credential, Profile, User
from carefold.vault import DecryptionError, encrypt_credential, get_or_create_dek


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Provides an isolated in-memory SQLite AsyncSession for OAuth broker tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    await engine.dispose()


def test_pkce_s256_generation_and_verification() -> None:
    """Verifies RFC 7636 PKCE S256 verifier/challenge generation and constant-time verification."""
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) == 64
    assert "=" not in verifier
    assert "=" not in challenge
    assert verifier != challenge

    assert verify_pkce_challenge(verifier, challenge) is True
    assert verify_pkce_challenge(verifier + "x", challenge) is False
    assert verify_pkce_challenge("", challenge) is False
    assert verify_pkce_challenge(verifier, "") is False


def test_resolve_redirect_uri_local_and_server_modes() -> None:
    """Verifies Titan S10 fixed loopback redirect URI in Mode L and HTTPS enforcement in Mode S."""
    local_uri = resolve_redirect_uri(deployment_mode="local", loopback_port=8000)
    assert local_uri == "http://127.0.0.1:8000/api/v1/oauth/callback"

    custom_port_uri = resolve_redirect_uri(deployment_mode="local", loopback_port=9090)
    assert custom_port_uri == "http://127.0.0.1:9090/api/v1/oauth/callback"

    server_uri = resolve_redirect_uri(
        deployment_mode="server",
        external_base_url="https://carefold.example.org/",
    )
    assert server_uri == "https://carefold.example.org/api/v1/oauth/callback"

    with pytest.raises(ValueError, match="https://"):
        resolve_redirect_uri(
            deployment_mode="server",
            external_base_url="http://carefold.example.org",
        )

    with pytest.raises(ValueError, match="external_base_url is required"):
        resolve_redirect_uri(deployment_mode="server", external_base_url=None)


def test_oauth_state_hmac_signing_tampering_isolation_and_expiry() -> None:
    """Verifies HMAC-SHA256 OAuth state signing, tampering detection, cross-profile rejection, and TTL expiry."""
    secret = os.urandom(32)
    verifier, challenge = generate_pkce_pair()

    state = create_oauth_state(
        user_id="user-1",
        profile_id="prof-alice",
        connection_id="conn-withings-1",
        code_verifier=verifier,
        secret_key=secret,
        ttl_seconds=600,
    )

    decoded = verify_oauth_state(
        state_token=state,
        secret_key=secret,
        expected_user_id="user-1",
        expected_profile_id="prof-alice",
    )
    assert decoded["user_id"] == "user-1"
    assert decoded["profile_id"] == "prof-alice"
    assert decoded["connection_id"] == "conn-withings-1"
    assert decoded["code_verifier"] == verifier
    assert decoded["nonce"]

    # Tampered signature must fail
    tampered_state = state[:-4] + ("0000" if not state.endswith("0000") else "ffff")
    with pytest.raises(ValueError, match="tampered"):
        verify_oauth_state(tampered_state, secret_key=secret)

    # Cross-profile replay must fail
    with pytest.raises(ValueError, match="profile_id mismatch"):
        verify_oauth_state(
            state,
            secret_key=secret,
            expected_user_id="user-1",
            expected_profile_id="prof-bob",
        )

    # Cross-user replay must fail
    with pytest.raises(ValueError, match="user_id mismatch"):
        verify_oauth_state(
            state,
            secret_key=secret,
            expected_user_id="user-2",
            expected_profile_id="prof-alice",
        )

    # Expired state token must fail
    expired_state = create_oauth_state(
        user_id="user-1",
        profile_id="prof-alice",
        connection_id="conn-withings-1",
        code_verifier=verifier,
        secret_key=secret,
        ttl_seconds=-10,
    )
    with pytest.raises(ValueError, match="expired"):
        verify_oauth_state(expired_state, secret_key=secret)

    auth_url = build_authorization_url(
        authorization_endpoint="https://account.withings.com/oauth2_user/authorize2",
        client_id="byo-client-123",
        redirect_uri="http://127.0.0.1:8000/api/v1/oauth/callback",
        state=state,
        code_challenge=challenge,
        scopes=["user.metrics"],
    )
    assert "code_challenge_method=S256" in auth_url
    assert f"code_challenge={challenge}" in auth_url


@pytest.mark.asyncio
async def test_store_and_load_connection_tokens_with_aad_binding(db_session: AsyncSession) -> None:
    """Verifies Vault token encryption, AAD binding, and Connection activation."""
    kek = os.urandom(32)
    user = User(id="u-oauth-1", email="alice@example.com", username="alice", hashed_password="pw")
    profile_a = Profile(id="p-oauth-a", user_id=user.id, name="Alice")
    profile_b = Profile(id="p-oauth-b", user_id=user.id, name="Bob")
    conn = Connection(
        id="c-withings-a",
        user_id=user.id,
        profile_id=profile_a.id,
        connector_id="withings",
        status="pending_auth",
        consecutive_failures=2,
    )
    db_session.add_all([user, profile_a, profile_b, conn])
    await db_session.commit()

    cred = await store_connection_tokens(
        session=db_session,
        profile_id=profile_a.id,
        connection_id=conn.id,
        user_id=user.id,
        token_payload={
            "access_token": "acc_initial_123",
            "refresh_token": "ref_initial_456",
            "expires_in": 3600,
        },
        kek=kek,
    )
    assert cred.token_version == 1
    assert cred.dek_version == 1
    assert cred.aad_binding == f"{profile_a.id}|{conn.id}|1"

    await db_session.refresh(conn)
    assert conn.status == "active"
    assert conn.consecutive_failures == 0

    loaded_tokens, version = await load_connection_tokens(
        session=db_session,
        profile_id=profile_a.id,
        connection_id=conn.id,
        kek=kek,
    )
    assert version == 1
    assert loaded_tokens["access_token"] == "acc_initial_123"
    assert loaded_tokens["refresh_token"] == "ref_initial_456"

    # Attempt cross-profile decryption with wrong profile_id must fail due to AAD binding
    with pytest.raises((ValueError, DecryptionError)):
        await load_connection_tokens(
            session=db_session,
            profile_id=profile_b.id,
            connection_id=conn.id,
            kek=kek,
        )


@pytest.mark.asyncio
async def test_versioned_token_refresh_optimistic_concurrency_and_invalid_grant(
    db_session: AsyncSession,
) -> None:
    """Verifies Titan S6 versioned token refresh: normal rotation, concurrent worker race, and invalid_grant -> needs_reauth."""
    kek = os.urandom(32)
    user = User(id="u-refresh-1", email="steward@example.com", username="steward", hashed_password="pw")
    profile = Profile(id="p-refresh-1", user_id=user.id, name="Steward")
    conn = Connection(
        id="c-refresh-1",
        user_id=user.id,
        profile_id=profile.id,
        connector_id="withings",
        status="active",
    )
    db_session.add_all([user, profile, conn])
    await db_session.commit()

    await store_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        user_id=user.id,
        token_payload={
            "access_token": "acc_v1",
            "refresh_token": "ref_v1",
            "expires_in": 3600,
        },
        kek=kek,
    )

    # 1. Standard rotating token refresh (version 1 -> 2)
    async def _rotate_v2(old_refresh: str) -> Dict[str, Any]:
        assert old_refresh == "ref_v1"
        return {
            "access_token": "acc_v2",
            "refresh_token": "ref_v2",
            "expires_in": 7200,
        }

    refreshed = await refresh_connection_token(
        session=db_session,
        connection_id=conn.id,
        token_fetcher=_rotate_v2,
        kek=kek,
    )
    assert refreshed["access_token"] == "acc_v2"
    assert refreshed["refresh_token"] == "ref_v2"

    loaded_v2, ver_v2 = await load_connection_tokens(
        session=db_session,
        profile_id=profile.id,
        connection_id=conn.id,
        kek=kek,
    )
    assert ver_v2 == 2
    assert loaded_v2["access_token"] == "acc_v2"
    assert loaded_v2["refresh_token"] == "ref_v2"

    # 2. Concurrent worker race simulation:
    # While worker A's token_fetcher is in flight, worker B updates token_version from 2 -> 3 in DB.
    # Worker A's optimistic UPDATE sees rowcount == 0 and must re-read and return Worker B's winning token!
    async def _concurrent_loser_fetcher(old_refresh: str) -> Dict[str, Any]:
        assert old_refresh == "ref_v2"
        dek, dek_ver = await get_or_create_dek(db_session, profile.id, kek)
        winning_payload = {
            "access_token": "acc_v3_winner_from_worker_b",
            "refresh_token": "ref_v3_winner_from_worker_b",
        }
        winning_ct = encrypt_credential(
            dek,
            json.dumps(winning_payload, sort_keys=True),
            profile.id,
            conn.id,
            dek_ver,
        ).hex()
        await db_session.execute(
            update(Credential)
            .where(Credential.connection_id == conn.id, Credential.token_version == 2)
            .values(encrypted_blob=winning_ct, token_version=3)
        )
        await db_session.commit()
        return {
            "access_token": "acc_v3_stale_loser_worker_a",
            "refresh_token": "ref_v3_stale_loser_worker_a",
        }

    race_result = await refresh_connection_token(
        session=db_session,
        connection_id=conn.id,
        token_fetcher=_concurrent_loser_fetcher,
        kek=kek,
    )
    assert race_result["access_token"] == "acc_v3_winner_from_worker_b"
    assert race_result["refresh_token"] == "ref_v3_winner_from_worker_b"

    # 3. OAuth invalid_grant transitions Connection to needs_reauth
    async def _invalid_grant_fetcher(_old_refresh: str) -> Dict[str, Any]:
        return {"error": "invalid_grant", "error_description": "Refresh token revoked by user"}

    with pytest.raises(PermissionError, match="needs_reauth"):
        await refresh_connection_token(
            session=db_session,
            connection_id=conn.id,
            token_fetcher=_invalid_grant_fetcher,
            kek=kek,
        )

    conn_res = await db_session.execute(select(Connection).where(Connection.id == conn.id))
    updated_conn = conn_res.scalar_one()
    assert updated_conn.status == "needs_reauth"
    assert "invalid_grant" in (updated_conn.status_message or "")
