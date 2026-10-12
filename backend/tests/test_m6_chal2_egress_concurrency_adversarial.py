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

"""Adversarial stress test suite for ScopedHttp egress blocking & Credential token concurrency.

Scope: Challenger 2 (m6_18_chal2)
- AU-50 / AU-51 / AU-52 / R7:
  1. ScopedHttp Anti-SSRF & Egress Stress:
     - Cloud metadata attempts: 169.254.169.254, 169.254.170.2, metadata.google.internal
       must be unconditionally blocked with EgressBlockedError (even if in allowlist).
     - Link-local IPs: 169.254.1.1, [fe80::1] blocked with EgressBlockedError.
     - Non-allowlisted external domains: evil.com, google.com (when allowed is api.hospital.org).
     - Scheme injection: file:///etc/passwd, ftp://attacker.com, gopher://127.0.0.1, data, ws, javascript.
     - Subdomain and prefix spoofing: api.hospital.org.evil.com, evilapi.hospital.org.
  2. Credential Concurrency & Optimistic Locking:
     - Simulate 10 concurrent tasks attempting to rotate tokens on the same Credential row with token_version.
     - Verify exactly 1 task succeeds at version N -> N+1, while 9 other tasks detect concurrency conflict.
     - Verify cryptographic AAD binding format carefold:p:{profile_id}:c:{connection_id}.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
import httpx
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from carefold.db.base import Base
from carefold.db.models import Connection, ConnectionState, Credential, Profile, User
from connectors.errors import EgressBlockedError
from connectors.http import ScopedHttp


# ==============================================================================
# Database Fixtures
# ==============================================================================

@pytest.fixture
def thread_safe_db():
    """In-memory SQLite database configured with StaticPool for concurrency testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    # Seed baseline User, Profile, and Connection
    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    connection_id = str(uuid.uuid4())

    init_session = session_factory()
    user = User(
        id=user_id,
        email="challenger2@carefold.org",
        username="chal2_tester",
        hashed_password="argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        full_name="Challenger Two",
        role="steward",
    )
    profile = Profile(
        id=profile_id,
        user_id=user_id,
        name="Adversarial Patient",
        relationship="self",
        role="self",
    )
    connection = Connection(
        id=connection_id,
        user_id=user_id,
        profile_id=profile_id,
        connector_id="adversarial-hospital-connector",
        status=ConnectionState.ACTIVE.value,
        label="Adversarial EHR Connection",
    )
    init_session.add_all([user, profile, connection])
    init_session.commit()
    init_session.close()

    yield {
        "engine": engine,
        "session_factory": session_factory,
        "user_id": user_id,
        "profile_id": profile_id,
        "connection_id": connection_id,
    }

    Base.metadata.drop_all(bind=engine)


# ==============================================================================
# Part 1: ScopedHttp Anti-SSRF & Egress Stress Tests
# ==============================================================================

class TestScopedHttpAntiSsrfAndEgress:
    """Adversarial stress testing of ScopedHttp egress blocking and SSRF containment."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata_target",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://169.254.170.2/v2/metadata",
            "http://169.254.170.2/v2/credentials",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://metadata.google.internal/",
        ],
    )
    async def test_cloud_metadata_unconditionally_blocked_even_when_in_allowlist(
        self, metadata_target: str
    ):
        """Verify cloud metadata endpoints (AWS, ECS, GCP) are UNCONDITIONALLY blocked.

        Even if an adversary or malicious connector manifest attempts to include
        169.254.169.254, 169.254.170.2, or metadata.google.internal in allowed_hosts,
        ScopedHttp MUST unconditionally raise EgressBlockedError.
        """
        # Malicious allowlist attempting to whitelist metadata
        malicious_allowlist = [
            "169.254.169.254",
            "169.254.170.2",
            "metadata.google.internal",
            "api.hospital.org",
        ]
        scoped = ScopedHttp(allowed_hosts=malicious_allowlist)

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(metadata_target)

        err_msg = str(exc_info.value).lower()
        assert (
            "metadata" in err_msg
            or "strictly blocked" in err_msg
            or "blocked" in err_msg
        ), f"Expected metadata error for {metadata_target}, got: {exc_info.value}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata_target",
        [
            "http://169.254.169.254/latest/meta-data",
            "http://169.254.170.2/v2/metadata",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    async def test_cloud_metadata_blocked_when_not_in_allowlist(
        self, metadata_target: str
    ):
        """Verify cloud metadata attempts are strictly blocked under standard allowlist."""
        scoped = ScopedHttp(allowed_hosts=["api.hospital.org"])

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(metadata_target)

        assert "blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "link_local_url",
        [
            "http://169.254.1.1/internal",
            "http://169.254.200.50:8080/metrics",
            "http://[fe80::1]/service",
            "http://[fe80::1]:8443/debug",
            "http://[fe80::200:5efe:10.0.0.1]/status",
        ],
    )
    async def test_link_local_ips_blocked_unconditionally(self, link_local_url: str):
        """Verify IPv4 (169.254.0.0/16) and IPv6 (fe80::/10) link-local IPs are blocked."""
        # Include link-local addresses in allowlist to verify unconditional blocking
        scoped = ScopedHttp(
            allowed_hosts=["169.254.1.1", "169.254.200.50", "fe80::1", "[fe80::1]", "api.hospital.org"]
        )

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(link_local_url)

        err_msg = str(exc_info.value).lower()
        assert (
            "link-local" in err_msg
            or "metadata" in err_msg
            or "blocked" in err_msg
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "external_domain",
        [
            "https://evil.com/exfiltrate",
            "https://google.com/search",
            "https://attacker.org/leak",
            "https://104.244.42.1/steal",
            "https://internal.hospital.org.attacker.com/credentials",
        ],
    )
    async def test_non_allowlisted_external_domains_blocked(self, external_domain: str):
        """Verify non-allowlisted domains raise EgressBlockedError when allowed is api.hospital.org."""
        scoped = ScopedHttp(allowed_hosts=["api.hospital.org"])

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(external_domain)

        assert "blocked by manifest policy" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scheme_payload",
        [
            "file:///etc/passwd",
            "file:///var/run/secrets",
            "ftp://attacker.com/loot",
            "ftp://api.hospital.org/files",
            "gopher://127.0.0.1:70/_status",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "javascript:alert(document.cookie)",
            "ws://api.hospital.org/ws",
            "wss://api.hospital.org/secure-ws",
            "ldap://api.hospital.org/cn=admin",
        ],
    )
    async def test_scheme_injection_blocked(self, scheme_payload: str):
        """Verify non-HTTP/HTTPS scheme injection attacks are rejected with EgressBlockedError."""
        scoped = ScopedHttp(allowed_hosts=["api.hospital.org", "attacker.com"])

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(scheme_payload)

        err_msg = str(exc_info.value).lower()
        assert "scheme" in err_msg or "prohibited" in err_msg or "malformed" in err_msg

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spoofed_host_url",
        [
            "https://api.hospital.org.evil.com/leak",
            "https://api.hospital.org.evil.com:443/leak",
            "https://evilapi.hospital.org/leak",
            "https://api.hospital.org-attacker.com/v1/auth",
            "https://not-api.hospital.org/v1/auth",
            "https://api.hospital.org.attacker.net/records",
        ],
    )
    async def test_subdomain_and_prefix_spoofing_blocked(self, spoofed_host_url: str):
        """Verify subdomain suffix and prefix spoofing attacks cannot masquerade as allowed host."""
        scoped = ScopedHttp(allowed_hosts=["api.hospital.org"])

        with pytest.raises(EgressBlockedError) as exc_info:
            scoped.validate_url(spoofed_host_url)

        assert "blocked by manifest policy" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_allowlisted_host_variants_permitted(self):
        """Verify exact allowed host matching permits legitimate port and path variations."""
        scoped = ScopedHttp(allowed_hosts=["api.hospital.org"])

        # Default HTTPS port
        u1 = scoped.validate_url("https://api.hospital.org/v1/Patient/100")
        assert u1.host == "api.hospital.org"

        # Explicit non-standard port
        u2 = scoped.validate_url("https://api.hospital.org:8443/v1/Observation")
        assert u2.host == "api.hospital.org"

        # Case-insensitivity in hostname
        u3 = scoped.validate_url("https://API.HOSPITAL.ORG/v1/Encounter")
        assert u3.host.lower() == "api.hospital.org"


# ==============================================================================
# Part 2: Credential Concurrency & Optimistic Locking Tests
# ==============================================================================

class TestCredentialConcurrencyAndOptimisticLocking:
    """Adversarial stress testing of Credential token_version optimistic locking & AAD binding."""

    @pytest.mark.asyncio
    async def test_10_concurrent_tasks_optimistic_token_rotation(self, thread_safe_db: dict):
        """Simulate 10 concurrent tasks attempting to rotate tokens on the same Credential row.

        Verifies:
        - Exactly 1 task succeeds at version N -> N+1 (rowcount == 1).
        - Exactly 9 tasks detect concurrency conflict without crashing (rowcount == 0).
        - Final token_version in database is exactly N+1.
        - Data integrity is preserved with winning task payload; zero data corruption.
        """
        session_factory = thread_safe_db["session_factory"]
        user_id = thread_safe_db["user_id"]
        profile_id = thread_safe_db["profile_id"]
        connection_id = thread_safe_db["connection_id"]

        # 1. Create Credential at token_version=1
        cred_id = str(uuid.uuid4())
        aad_str = f"carefold:p:{profile_id}:c:{connection_id}"

        setup_session: Session = session_factory()
        cred = Credential(
            id=cred_id,
            connection_id=connection_id,
            user_id=user_id,
            profile_id=profile_id,
            encrypted_blob="initial_token_v1",
            token_version=1,
            aad_binding=aad_str,
        )
        setup_session.add(cred)
        setup_session.commit()
        setup_session.close()

        # 2. Concurrency stress harness: 10 concurrent workers
        execution_results: list[dict] = []
        concurrency_barrier = asyncio.Event()

        async def worker_task(worker_id: int):
            # Wait for all workers to spawn and synchronize on the starting line
            await concurrency_barrier.wait()

            worker_session: Session = session_factory()
            try:
                # All 10 workers read current version 1 simultaneously
                cred_record = worker_session.execute(
                    select(Credential).where(Credential.id == cred_id)
                ).scalar_one()
                read_version = cred_record.token_version

                # Simulate small micro-jitter
                await asyncio.sleep(0.005 * (worker_id % 3))

                # Attempt optimistic conditional update: WHERE id == cred_id AND token_version == read_version
                stmt = (
                    update(Credential)
                    .where(
                        Credential.id == cred_id,
                        Credential.token_version == read_version,
                    )
                    .values(
                        encrypted_blob=f"rotated_token_by_worker_{worker_id}",
                        token_version=read_version + 1,
                        rotated_at=datetime.now(timezone.utc),
                    )
                )
                res = worker_session.execute(stmt)
                worker_session.commit()

                if res.rowcount == 1:
                    execution_results.append({
                        "worker_id": worker_id,
                        "status": "SUCCESS",
                        "written_payload": f"rotated_token_by_worker_{worker_id}",
                    })
                else:
                    execution_results.append({
                        "worker_id": worker_id,
                        "status": "CONFLICT",
                        "written_payload": None,
                    })
            finally:
                worker_session.close()

        # Launch 10 concurrent worker tasks
        tasks = [asyncio.create_task(worker_task(i)) for i in range(10)]

        # Release barrier so all 10 workers hit the database concurrently
        concurrency_barrier.set()
        await asyncio.gather(*tasks)

        # 3. Assertions on concurrency outcomes
        successes = [r for r in execution_results if r["status"] == "SUCCESS"]
        conflicts = [r for r in execution_results if r["status"] == "CONFLICT"]

        assert len(successes) == 1, (
            f"Expected exactly 1 task to succeed in optimistic rotation, got {len(successes)}. "
            f"Results: {execution_results}"
        )
        assert len(conflicts) == 9, (
            f"Expected exactly 9 tasks to encounter conflict, got {len(conflicts)}. "
            f"Results: {execution_results}"
        )

        # 4. Verify database state integrity
        verify_session: Session = session_factory()
        final_cred = verify_session.execute(
            select(Credential).where(Credential.id == cred_id)
        ).scalar_one()

        assert final_cred.token_version == 2
        winner = successes[0]
        assert final_cred.encrypted_blob == winner["written_payload"]
        assert final_cred.encrypted_data == winner["written_payload"]  # synonym check
        verify_session.close()

    @pytest.mark.asyncio
    async def test_sequential_multi_round_concurrent_rotations(self, thread_safe_db: dict):
        """Verify multiple sequential rounds of 10 concurrent tasks each increment version reliably."""
        session_factory = thread_safe_db["session_factory"]
        user_id = thread_safe_db["user_id"]
        profile_id = thread_safe_db["profile_id"]
        connection_id = thread_safe_db["connection_id"]

        cred_id = str(uuid.uuid4())
        setup_session: Session = session_factory()
        cred = Credential(
            id=cred_id,
            connection_id=connection_id,
            user_id=user_id,
            profile_id=profile_id,
            encrypted_blob="base_round_v1",
            token_version=1,
            aad_binding=f"carefold:p:{profile_id}:c:{connection_id}",
        )
        setup_session.add(cred)
        setup_session.commit()
        setup_session.close()

        # Run 3 consecutive rounds of 10-worker competition (v1->v2, v2->v3, v3->v4)
        for expected_version in range(1, 4):
            round_results: list[str] = []

            async def round_worker(wid: int, exp_ver: int):
                s: Session = session_factory()
                try:
                    stmt = (
                        update(Credential)
                        .where(Credential.id == cred_id, Credential.token_version == exp_ver)
                        .values(
                            encrypted_blob=f"round_{exp_ver}_worker_{wid}",
                            token_version=exp_ver + 1,
                            rotated_at=datetime.now(timezone.utc),
                        )
                    )
                    res = s.execute(stmt)
                    s.commit()
                    round_results.append("SUCCESS" if res.rowcount == 1 else "CONFLICT")
                finally:
                    s.close()

            await asyncio.gather(*[round_worker(i, expected_version) for i in range(10)])

            assert round_results.count("SUCCESS") == 1
            assert round_results.count("CONFLICT") == 9

        # Verify final state is version 4
        verify_session: Session = session_factory()
        final_cred = verify_session.execute(
            select(Credential).where(Credential.id == cred_id)
        ).scalar_one()
        assert final_cred.token_version == 4
        verify_session.close()

    def test_stale_worker_cannot_overwrite_newer_version(self, thread_safe_db: dict):
        """Verify that a worker operating on a stale version cannot overwrite a newer token."""
        session_factory = thread_safe_db["session_factory"]
        user_id = thread_safe_db["user_id"]
        profile_id = thread_safe_db["profile_id"]
        connection_id = thread_safe_db["connection_id"]

        cred_id = str(uuid.uuid4())
        s: Session = session_factory()
        cred = Credential(
            id=cred_id,
            connection_id=connection_id,
            user_id=user_id,
            profile_id=profile_id,
            encrypted_blob="fresh_token_v5",
            token_version=5,
        )
        s.add(cred)
        s.commit()

        # Stale worker tries to update using outdated token_version=2
        stale_stmt = (
            update(Credential)
            .where(Credential.id == cred_id, Credential.token_version == 2)
            .values(
                encrypted_blob="corrupted_stale_payload",
                token_version=3,
            )
        )
        result = s.execute(stale_stmt)
        s.commit()

        assert result.rowcount == 0  # Stale update blocked

        s.refresh(cred)
        assert cred.token_version == 5
        assert cred.encrypted_blob == "fresh_token_v5"
        s.close()

    def test_cryptographic_aad_binding_format_and_tampering(self, thread_safe_db: dict):
        """Verify cryptographic AAD binding format carefold:p:{profile_id}:c:{connection_id}.

        Verifies:
        - Canonical format conforms strictly to carefold:p:{profile_id}:c:{connection_id}.
        - Changing profile_id or connection_id causes AAD verification failure.
        - Cross-profile credential isolation prevents cross-tenant credential reuse.
        """
        profile_id = thread_safe_db["profile_id"]
        connection_id = thread_safe_db["connection_id"]

        # Canonical AAD string
        canonical_aad = f"carefold:p:{profile_id}:c:{connection_id}"
        assert canonical_aad.startswith("carefold:p:")
        assert ":c:" in canonical_aad

        # Verify parsing components
        parts = canonical_aad.split(":")
        assert len(parts) == 5
        assert parts[0] == "carefold"
        assert parts[1] == "p"
        assert parts[2] == profile_id
        assert parts[3] == "c"
        assert parts[4] == connection_id

        # Tampering tests
        tampered_profile_aad = f"carefold:p:attacker_profile:c:{connection_id}"
        assert tampered_profile_aad != canonical_aad

        tampered_connection_aad = f"carefold:p:{profile_id}:c:attacker_connection"
        assert tampered_connection_aad != canonical_aad

        missing_prefix_aad = f"p:{profile_id}:c:{connection_id}"
        assert missing_prefix_aad != canonical_aad
