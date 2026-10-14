# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""OAuth 2.0 PKCE Broker & Versioned Token Refresh (AU-51 / DESIGN §5.2 / Titan S6 & S10).

Implements:
- RFC 7636 PKCE (`S256`) high-entropy verifier and challenge generation/verification.
- Mode L fixed loopback redirect URI (`http://127.0.0.1:8000/api/v1/oauth/callback`) vs
  Mode S HTTPS redirect URI resolution (`Titan S10`).
- HMAC-SHA256 signed state tokens binding `(user_id, profile_id, connection_id, code_verifier, nonce, exp)`.
- Envelope-encrypted credential persistence in `carefold.vault` with AAD binding.
- `Titan S6` optimistic concurrency versioned token refresh (`WHERE token_version = :v`),
  handling rotating refresh tokens and concurrent worker races safely.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Callable, Coroutine, Dict, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode, urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import Connection, Credential, utc_now
from carefold.vault import (
    decrypt_credential,
    encrypt_credential,
    get_kek,
    get_or_create_dek,
)

DEFAULT_OAUTH_STATE_TTL_SECONDS: int = 600
DEFAULT_LOOPBACK_PORT: int = 8000
OAUTH_CALLBACK_PATH: str = "/api/v1/oauth/callback"


def _b64url_encode(data: bytes) -> str:
    """Encodes raw bytes as unpadded URL-safe base64 string."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Decodes an unpadded URL-safe base64 string into raw bytes."""
    clean = (data or "").strip()
    padding = "=" * ((4 - len(clean) % 4) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii"))


def _compute_s256_challenge(code_verifier: str) -> str:
    """Computes RFC 7636 S256 code_challenge from a code_verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return _b64url_encode(digest)


def generate_pkce_pair() -> Tuple[str, str]:
    """Generates a high-entropy PKCE `code_verifier` (64 chars) and its `S256` `code_challenge`.

    Returns:
        Tuple of `(code_verifier, code_challenge)`.
    """
    # 48 random bytes -> 64 URL-safe base64 characters without '=' padding (RFC 7636 §4.1: 43-128 chars)
    code_verifier = _b64url_encode(os.urandom(48))
    code_challenge = _compute_s256_challenge(code_verifier)
    return code_verifier, code_challenge


def verify_pkce_challenge(code_verifier: str, expected_challenge: str) -> bool:
    """Verifies a PKCE `code_verifier` against an expected `S256` `code_challenge` in constant time."""
    if not code_verifier or not isinstance(code_verifier, str) or not code_verifier.strip():
        return False
    if not expected_challenge or not isinstance(expected_challenge, str) or not expected_challenge.strip():
        return False
    try:
        computed = _compute_s256_challenge(code_verifier.strip())
        return hmac.compare_digest(
            computed.encode("ascii"),
            expected_challenge.strip().encode("ascii"),
        )
    except Exception:
        return False


def resolve_redirect_uri(
    deployment_mode: str = "local",
    external_base_url: Optional[str] = None,
    loopback_port: int = DEFAULT_LOOPBACK_PORT,
) -> str:
    """Resolves the OAuth 2.0 callback redirect URI for Mode L (local) or Mode S (server) (`Titan S10`).

    Args:
        deployment_mode: `'local'` (Mode L) or `'server'` (Mode S).
        external_base_url: Required HTTPS base URL when `deployment_mode == 'server'`.
        loopback_port: Local loopback port in Mode L (defaults to 8000).

    Returns:
        Canonical redirect URI string.

    Raises:
        ValueError: If `deployment_mode` is invalid or `external_base_url` is missing/non-HTTPS in server mode.
    """
    mode = (deployment_mode or "local").strip().lower()
    if mode in ("local", "mode_l", "l"):
        port = int(loopback_port)
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid loopback_port: {loopback_port}. Must be between 1 and 65535.")
        return f"http://127.0.0.1:{port}{OAUTH_CALLBACK_PATH}"

    if mode in ("server", "mode_s", "s"):
        if not external_base_url or not str(external_base_url).strip():
            raise ValueError("external_base_url is required when deployment_mode is 'server'.")
        clean_base = str(external_base_url).strip().rstrip("/")
        parsed = urlparse(clean_base)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError(
                f"Server mode redirect URI requires an https:// external_base_url; got '{external_base_url}'."
            )
        return f"{clean_base}{OAUTH_CALLBACK_PATH}"

    raise ValueError(f"Unsupported deployment_mode '{deployment_mode}'. Expected 'local' or 'server'.")


def resolve_oauth_kek(kek: Optional[bytes] = None) -> bytes:
    """Resolves the 32-byte Vault KEK, falling back to CAREFOLD_MASTER_KEY or local home key in dev/test."""
    if kek is not None:
        return bytes(kek)
    try:
        return get_kek()
    except Exception:
        env_master = os.environ.get("CAREFOLD_MASTER_KEY", "").strip()
        if env_master:
            try:
                raw = bytes.fromhex(env_master)
                if len(raw) == 32:
                    return raw
            except ValueError:
                pass
            return hashlib.sha256(env_master.encode("utf-8")).digest()
        from carefold.config import settings

        return hashlib.sha256(f"carefold-local-kek:{settings.home_dir}".encode("utf-8")).digest()


def _normalize_secret_key(secret_key: Union[bytes, str, None]) -> bytes:
    """Validates and normalizes an HMAC signing key into raw bytes."""
    if secret_key is None:
        return resolve_oauth_kek()
    if isinstance(secret_key, str):
        key_bytes = secret_key.encode("utf-8")
    elif isinstance(secret_key, (bytes, bytearray)):
        key_bytes = bytes(secret_key)
    else:
        raise ValueError("secret_key must be bytes or str.")
    if not key_bytes:
        raise ValueError("secret_key cannot be empty.")
    return key_bytes


def create_oauth_state(
    user_id: str,
    profile_id: str,
    connection_id: str,
    code_verifier: str,
    secret_key: Union[bytes, str],
    ttl_seconds: int = DEFAULT_OAUTH_STATE_TTL_SECONDS,
) -> str:
    """Creates an HMAC-SHA256 signed OAuth `state` token binding user, profile, connection, and PKCE verifier.

    Args:
        user_id: Authenticated user ID initiating the OAuth flow.
        profile_id: Target care profile ID.
        connection_id: Target Connection ID.
        code_verifier: PKCE code_verifier associated with the authorization request.
        secret_key: HMAC signing secret key bytes.
        ttl_seconds: State token time-to-live in seconds (default 600s).

    Returns:
        Signed state token formatted as `<base64url_payload>.<hmac_hex_signature>`.
    """
    clean_user_id = (user_id or "").strip()
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    clean_verifier = (code_verifier or "").strip()

    if not clean_user_id:
        raise ValueError("user_id is required to create OAuth state.")
    if not clean_profile_id:
        raise ValueError("profile_id is required to create OAuth state.")
    if not clean_connection_id:
        raise ValueError("connection_id is required to create OAuth state.")
    if not clean_verifier:
        raise ValueError("code_verifier is required to create OAuth state.")

    key_bytes = _normalize_secret_key(secret_key)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp_ts = now_ts + int(ttl_seconds)

    payload_dict: Dict[str, Any] = {
        "user_id": clean_user_id,
        "profile_id": clean_profile_id,
        "connection_id": clean_connection_id,
        "code_verifier": clean_verifier,
        "nonce": secrets.token_urlsafe(16),
        "iat": now_ts,
        "exp": exp_ts,
    }
    payload_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    sig_hex = hmac.new(key_bytes, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig_hex}"


def verify_oauth_state(
    state_token: str,
    secret_key: Union[bytes, str],
    expected_user_id: Optional[str] = None,
    expected_profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verifies an HMAC-SHA256 signed OAuth `state` token and checks expiration and tenant binding.

    Args:
        state_token: Signed state token string from OAuth callback.
        secret_key: HMAC signing secret key bytes.
        expected_user_id: Optional user ID to enforce caller ownership.
        expected_profile_id: Optional profile ID to enforce profile isolation.

    Returns:
        Decoded state dictionary containing `user_id`, `profile_id`, `connection_id`, `code_verifier`, `nonce`, `exp`.

    Raises:
        ValueError: If malformed, tampered, expired, or mismatched against expected user/profile.
    """
    if not state_token or not isinstance(state_token, str) or "." not in state_token:
        raise ValueError("Invalid OAuth state token format.")

    parts = state_token.strip().split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid OAuth state token structure.")

    payload_b64, provided_sig = parts
    key_bytes = _normalize_secret_key(secret_key)
    expected_sig = hmac.new(key_bytes, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig.encode("ascii"), provided_sig.encode("ascii")):
        raise ValueError("OAuth state signature verification failed: token has been tampered with.")

    try:
        raw_json = _b64url_decode(payload_b64)
        payload = json.loads(raw_json.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to decode OAuth state payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Decoded OAuth state payload must be a JSON object.")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp_ts = payload.get("exp")
    if exp_ts is None or int(exp_ts) < now_ts:
        raise ValueError("OAuth state token has expired.")

    if expected_user_id is not None and payload.get("user_id") != expected_user_id.strip():
        raise ValueError(
            f"OAuth state user_id mismatch: expected '{expected_user_id.strip()}', got '{payload.get('user_id')}'."
        )

    if expected_profile_id is not None and payload.get("profile_id") != expected_profile_id.strip():
        raise ValueError(
            f"OAuth state profile_id mismatch: expected '{expected_profile_id.strip()}', got '{payload.get('profile_id')}'."
        )

    return payload


def build_authorization_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: Optional[Sequence[str]] = None,
    extra_params: Optional[Dict[str, str]] = None,
) -> str:
    """Constructs a full OAuth 2.0 Authorization Code + PKCE (`S256`) authorization URL."""
    params: Dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scopes:
        params["scope"] = " ".join(s.strip() for s in scopes if s and s.strip())
    if extra_params:
        params.update(extra_params)
    sep = "&" if "?" in authorization_endpoint else "?"
    return f"{authorization_endpoint}{sep}{urlencode(params)}"


def _resolve_token_expiration(token_payload: Dict[str, Any]) -> Optional[datetime]:
    """Resolves UTC expiration datetime from a token payload dictionary."""
    now = utc_now()
    raw_exp_at = token_payload.get("expires_at")
    if isinstance(raw_exp_at, datetime):
        return raw_exp_at if raw_exp_at.tzinfo else raw_exp_at.replace(tzinfo=timezone.utc)
    if isinstance(raw_exp_at, (int, float)):
        return datetime.fromtimestamp(float(raw_exp_at), tz=timezone.utc)
    if isinstance(raw_exp_at, str) and raw_exp_at.strip():
        clean = raw_exp_at.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(clean)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    expires_in = token_payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return now + timedelta(seconds=float(expires_in))
    return None


async def store_connection_tokens(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    user_id: Optional[str],
    token_payload: Dict[str, Any],
    kek: Optional[bytes] = None,
) -> Credential:
    """Encrypts and persists OAuth/API credentials in Vault and activates the parent `Connection`.

    Uses `get_or_create_dek` and `encrypt_credential` with strict AAD binding
    `f"{profile_id}|{connection_id}|{dek_version}"`.
    """
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    if not clean_profile_id or not clean_connection_id:
        raise ValueError("profile_id and connection_id are required to store connection tokens.")
    if not isinstance(token_payload, dict) or not token_payload:
        raise ValueError("token_payload must be a non-empty dictionary.")

    effective_kek = resolve_oauth_kek(kek)
    dek, dek_version = await get_or_create_dek(session, clean_profile_id, effective_kek)

    serialized_payload = json.dumps(token_payload, sort_keys=True)
    ciphertext_bytes = encrypt_credential(
        dek,
        serialized_payload,
        clean_profile_id,
        clean_connection_id,
        dek_version,
    )
    aad_str = f"{clean_profile_id}|{clean_connection_id}|{dek_version}"
    expires_at = _resolve_token_expiration(token_payload)
    now = utc_now()

    stmt = select(Credential).where(
        Credential.connection_id == clean_connection_id,
        Credential.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    cred = res.scalar_one_or_none()

    if cred is not None:
        cred.encrypted_blob = ciphertext_bytes.hex()
        cred.token_version = 1
        cred.dek_version = dek_version
        cred.aad_binding = aad_str
        cred.expires_at = expires_at
        cred.updated_at = now
        if user_id:
            cred.user_id = user_id
    else:
        cred = Credential(
            connection_id=clean_connection_id,
            user_id=user_id,
            profile_id=clean_profile_id,
            encrypted_blob=ciphertext_bytes.hex(),
            token_version=1,
            dek_version=dek_version,
            aad_binding=aad_str,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(cred)

    conn_stmt = select(Connection).where(
        Connection.id == clean_connection_id,
        Connection.profile_id == clean_profile_id,
    )
    conn_res = await session.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is not None:
        connection.status = "active"
        connection.consecutive_failures = 0
        connection.status_message = None
        connection.updated_at = now

    await session.commit()
    await session.refresh(cred)
    if connection is not None:
        await session.refresh(connection)
    return cred


async def load_connection_tokens(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    kek: Optional[bytes] = None,
) -> Tuple[Dict[str, Any], int]:
    """Loads and decrypts `Credential` tokens for `(profile_id, connection_id)`.

    Returns:
        Tuple of `(token_dict, token_version)`.

    Raises:
        ValueError: If no credential record exists for `(profile_id, connection_id)`.
        DecryptionError: If AAD binding or ciphertext verification fails.
    """
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    if not clean_profile_id or not clean_connection_id:
        raise ValueError("profile_id and connection_id are required.")

    stmt = (
        select(Credential)
        .where(
            Credential.connection_id == clean_connection_id,
            Credential.profile_id == clean_profile_id,
        )
        .execution_options(populate_existing=True)
    )
    res = await session.execute(stmt)
    cred = res.scalar_one_or_none()
    if cred is None:
        raise ValueError(
            f"No stored credential found for connection '{clean_connection_id}' in profile '{clean_profile_id}'."
        )

    effective_kek = resolve_oauth_kek(kek)
    dek, _ = await get_or_create_dek(session, clean_profile_id, effective_kek)
    plaintext_bytes = decrypt_credential(
        dek,
        cred.encrypted_blob,
        clean_profile_id,
        clean_connection_id,
        cred.dek_version,
    )
    token_dict = json.loads(plaintext_bytes.decode("utf-8"))
    return token_dict, cred.token_version


def _is_invalid_grant_failure(exc_or_payload: Any) -> bool:
    """Detects OAuth `invalid_grant` / `401` / `unauthorized` errors requiring user re-authentication."""
    if isinstance(exc_or_payload, dict):
        err_code = str(exc_or_payload.get("error") or "").strip().lower()
        status_code = exc_or_payload.get("status_code")
        return err_code in ("invalid_grant", "unauthorized", "invalid_token", "token_expired") or status_code == 401

    msg = str(exc_or_payload).lower()
    cls_name = type(exc_or_payload).__name__.lower()
    if "authexpired" in cls_name:
        return True
    for marker in ("invalid_grant", "401", "unauthorized", "refresh token expired", "token_expired", "needs_reauth"):
        if marker in msg:
            return True
    return False


async def refresh_connection_token(
    session: AsyncSession,
    connection_id: str,
    token_fetcher: Callable[[str], Coroutine[Any, Any, Dict[str, Any]]],
    kek: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Executes `Titan S6` Versioned Token Refresh with optimistic concurrency (`WHERE token_version = :v`).

    Steps:
    1. Loads `Connection` and current `Credential` (`current_version = cred.token_version`), decrypts `refresh_token`.
    2. Calls `await token_fetcher(refresh_token)` to exchange at the OAuth provider.
    3. On `invalid_grant` or `401`, transitions `Connection.status = 'needs_reauth'`, commits,
       and raises `PermissionError('needs_reauth')`.
    4. Encrypts the new token payload (persisting the new rotating `refresh_token` BEFORE using
       the new `access_token`) with `get_or_create_dek`.
    5. Executes `UPDATE credentials SET ..., token_version = current_version + 1 WHERE id = :id AND token_version = :v`.
    6. If `rowcount == 0` (concurrent worker won the race), re-reads the latest `Credential` row from DB,
       decrypts it, and returns the winning token dictionary.
    """
    clean_connection_id = (connection_id or "").strip()
    if not clean_connection_id:
        raise ValueError("connection_id is required.")

    conn_stmt = select(Connection).where(Connection.id == clean_connection_id)
    conn_res = await session.execute(conn_stmt)
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise ValueError(f"Connection '{clean_connection_id}' not found.")

    profile_id = connection.profile_id
    cred_stmt = (
        select(Credential)
        .where(
            Credential.connection_id == clean_connection_id,
            Credential.profile_id == profile_id,
        )
        .execution_options(populate_existing=True)
    )
    cred_res = await session.execute(cred_stmt)
    cred = cred_res.scalar_one_or_none()
    if cred is None:
        raise ValueError(f"No credential found for connection '{clean_connection_id}'.")

    current_version = cred.token_version
    effective_kek = resolve_oauth_kek(kek)
    dek, dek_version = await get_or_create_dek(session, profile_id, effective_kek)

    plaintext_bytes = decrypt_credential(
        dek,
        cred.encrypted_blob,
        profile_id,
        clean_connection_id,
        cred.dek_version,
    )
    current_tokens: Dict[str, Any] = json.loads(plaintext_bytes.decode("utf-8"))
    refresh_token = str(current_tokens.get("refresh_token") or "").strip()

    if not refresh_token:
        connection.status = "needs_reauth"
        connection.status_message = "OAuth refresh token missing; re-authentication required."
        connection.updated_at = utc_now()
        await session.commit()
        raise PermissionError("needs_reauth")

    try:
        fetched_payload = await token_fetcher(refresh_token)
    except Exception as exc:
        if _is_invalid_grant_failure(exc):
            connection.status = "needs_reauth"
            connection.status_message = "OAuth token expired or revoked (invalid_grant); re-authentication required."
            connection.updated_at = utc_now()
            await session.commit()
            raise PermissionError("needs_reauth") from exc
        raise

    if not isinstance(fetched_payload, dict) or _is_invalid_grant_failure(fetched_payload):
        connection.status = "needs_reauth"
        connection.status_message = "OAuth token expired or revoked (invalid_grant); re-authentication required."
        connection.updated_at = utc_now()
        await session.commit()
        raise PermissionError("needs_reauth")

    # Merge new tokens (preserving rotating refresh_token before returning access_token)
    merged_tokens = dict(current_tokens)
    merged_tokens.update(fetched_payload)

    new_cipher_hex = encrypt_credential(
        dek,
        json.dumps(merged_tokens, sort_keys=True),
        profile_id,
        clean_connection_id,
        dek_version,
    ).hex()
    new_exp = _resolve_token_expiration(merged_tokens)
    now = utc_now()
    aad_str = f"{profile_id}|{clean_connection_id}|{dek_version}"

    upd_stmt = (
        update(Credential)
        .where(
            Credential.id == cred.id,
            Credential.token_version == current_version,
        )
        .values(
            encrypted_blob=new_cipher_hex,
            token_version=current_version + 1,
            dek_version=dek_version,
            aad_binding=aad_str,
            expires_at=new_exp,
            rotated_at=now,
            updated_at=now,
        )
    )
    upd_res = await session.execute(upd_stmt)

    if (upd_res.rowcount or 0) == 0:
        # Another worker concurrently refreshed the token; re-read winning credential from DB
        winning_stmt = (
            select(Credential)
            .where(Credential.id == cred.id)
            .execution_options(populate_existing=True)
        )
        winning_res = await session.execute(winning_stmt)
        winning_cred = winning_res.scalar_one()
        winning_bytes = decrypt_credential(
            dek,
            winning_cred.encrypted_blob,
            profile_id,
            clean_connection_id,
            winning_cred.dek_version,
        )
        winning_tokens: Dict[str, Any] = json.loads(winning_bytes.decode("utf-8"))
        return winning_tokens

    connection.status = "active"
    connection.consecutive_failures = 0
    connection.status_message = None
    connection.updated_at = now
    await session.commit()
    return merged_tokens


__all__ = [
    "DEFAULT_LOOPBACK_PORT",
    "DEFAULT_OAUTH_STATE_TTL_SECONDS",
    "OAUTH_CALLBACK_PATH",
    "build_authorization_url",
    "create_oauth_state",
    "generate_pkce_pair",
    "load_connection_tokens",
    "refresh_connection_token",
    "resolve_redirect_uri",
    "store_connection_tokens",
    "verify_oauth_state",
    "verify_pkce_challenge",
]
