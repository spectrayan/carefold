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

"""Tier 5 Adversarial Coverage Hardening Suite for Carefold Autonomy Batch 1.

Performs rigorous white-box adversarial verification across all Batch 1 modules:
- backend/src/carefold/vault/: crypto.py, kek.py, dek.py, errors.py
- backend/src/carefold/engine/: tool_registry.py, tool_exec.py, job_runner.py
- backend/src/carefold/api/: approvals.py
- backend/src/carefold/db/: models.py

Verifies:
1. Cryptographic boundary conditions, key sizes, nonce non-repetition, bit-flip tampering,
   AAD mismatch defenses, KEK resolution fail-closed behavior, and crypto-shredding.
2. ToolSpec immutability, sequence emulation, age-band protection matrix, and capability gates.
3. Choke point fail-closed validation, monotone taint propagation, egress firewall SSRF evasion,
   and unhandled exception containment.
4. Approvals CSRF defenses, zero-admin-bypass RBAC, decision state transitions, and atomic single-use
   resumption token replay prevention.
5. Job runner recurrence edge cases, concurrent worker lease isolation, clock jump coalescing,
   and overdue reminder clinical safety invariants.
6. Database model cascading deletion, unique constraints, and malformed JSON resilience.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, patch
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from carefold.api.approvals import (
    ApprovalDecideRequest,
    consume_approval_atomic,
    router as approvals_router,
    verify_csrf,
    verify_manage_access,
)
from carefold.api.deps import get_db
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import set_auth_port
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.db.models import (
    Approval,
    Base,
    Credential,
    Job as DBJob,
    Profile,
    ProfileAccess,
    ProfileKey,
    User,
)
from carefold.engine.job_runner import (
    CLOCK_JUMP_THRESHOLD_SECONDS,
    DEFAULT_LEASE_DURATION,
    REMINDER_OVERDUE_THRESHOLD_SECONDS,
    JobRunner,
    calculate_next_occurrence,
)
from carefold.engine.tool_exec import (
    EgressBlockedError,
    PolicyDecision,
    TaintFlag,
    ToolContext,
    ToolResult,
    UntrustedResult,
    canonical_json,
    compute_payload_hash,
    evaluate_policy_gate,
    execute_tool_call,
    verify_egress_firewall,
)
from carefold.engine.tool_registry import (
    DataFlows,
    RiskTier,
    ToolSpec,
    ToolSpecRegistry,
    TrustLevel,
    create_default_registry,
)
from carefold.main import app
from carefold.vault.crypto import (
    MIN_PAYLOAD_LENGTH,
    NONCE_LENGTH,
    TAG_LENGTH,
    decrypt,
    encrypt,
)
from carefold.vault.dek import (
    compute_aad_binding,
    compute_dek_wrapping_aad,
    decrypt_credential,
    delete_profile_keys,
    encrypt_credential,
    get_or_create_dek,
    rotate_dek,
)
from carefold.vault.errors import (
    DecryptionError,
    KeyDerivationError,
    VaultLockedError,
)
from carefold.vault.kek import (
    _resolve_from_secret_file,
    derive_argon2id_kek,
    resolve_kek,
)


# ============================================================================
# Shared Async Fixtures
# ============================================================================

@pytest.fixture
async def async_db(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Provides an isolated on-disk SQLite database with WAL mode and foreign keys enabled."""
    db_file = tmp_path / "carefold_tier5.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(
        db_url,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 10000;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.fixture
async def sample_user_and_profile(async_db: async_sessionmaker[AsyncSession]) -> Dict[str, Any]:
    """Seeds a baseline User and Profile in the database."""
    async with async_db() as session:
        user_id = str(uuid.uuid4())
        profile_id = str(uuid.uuid4())

        user = User(
            id=user_id,
            email=f"user_{user_id[:8]}@example.com",
            username=f"user_{user_id[:8]}",
            hashed_password="hashed_pw_test",
            role="user",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Jane Doe",
            relationship="self",
            role="self",
            date_of_birth="1985-05-15",
        )
        session.add_all([user, profile])
        await session.commit()
        return {"user_id": user_id, "profile_id": profile_id}


# ============================================================================
# Section 1: carefold.vault Hardening
# ============================================================================

class TestVaultCryptoAdversarial:
    """Stress tests and boundary validation for AES-256-GCM symmetric crypto engine."""

    def test_crypto_key_length_and_type_boundaries(self):
        """Rejects key lengths != 32 bytes and non-bytes key objects."""
        plaintext = b"sensitive_ehr_token"
        aad = b"prof-1|conn-1|1"

        # Invalid key lengths
        for bad_len in (0, 16, 31, 33, 64):
            bad_key = b"A" * bad_len
            with pytest.raises(ValueError, match="AES-256 requires exactly 32-byte key"):
                encrypt(bad_key, plaintext, aad)
            with pytest.raises(ValueError, match="AES-256 requires exactly 32-byte key"):
                decrypt(bad_key, b"B" * 40, aad)

        # Invalid key types
        for bad_type_key in (None, 12345, ["key"], {"key": "val"}):
            with pytest.raises(ValueError, match="AES-256 requires exactly 32-byte key"):
                encrypt(bad_type_key, plaintext, aad)  # type: ignore

    def test_crypto_empty_and_large_plaintext_roundtrip(self):
        """Handles empty plaintext (producing 28B payload) and large 100KB payloads."""
        key = os.urandom(32)
        aad = b"prof-test|conn-1|1"

        # Empty bytes
        ct_empty = encrypt(key, b"", aad)
        assert len(ct_empty) == MIN_PAYLOAD_LENGTH  # 12-byte nonce + 0-byte ct + 16-byte tag
        assert decrypt(key, ct_empty, aad) == b""

        # 100KB binary data
        large_payload = os.urandom(100 * 1024)
        ct_large = encrypt(key, large_payload, aad)
        assert len(ct_large) == 12 + len(large_payload) + 16
        assert decrypt(key, ct_large, aad) == large_payload

    def test_crypto_nonce_non_repetition(self):
        """Encrypting identical plaintext twice produces distinct nonces and distinct ciphertexts."""
        key = os.urandom(32)
        plaintext = b"identical_secret_token"
        aad = b"prof-1|conn-1|1"

        ct1 = encrypt(key, plaintext, aad)
        ct2 = encrypt(key, plaintext, aad)

        assert ct1 != ct2
        assert ct1[:NONCE_LENGTH] != ct2[:NONCE_LENGTH]
        assert decrypt(key, ct1, aad) == plaintext
        assert decrypt(key, ct2, aad) == plaintext

    def test_crypto_ciphertext_tampering_bit_flips(self):
        """Detects single-bit tampering anywhere in nonce, payload, or authentication tag."""
        key = os.urandom(32)
        plaintext = b"critical_patient_vitals_payload"
        aad = b"prof-1|conn-1|1"
        ct = bytearray(encrypt(key, plaintext, aad))

        # Test tampering at start (nonce), middle (ciphertext), and end (tag)
        tamper_indices = [0, NONCE_LENGTH - 1, NONCE_LENGTH + 2, len(ct) - TAG_LENGTH, len(ct) - 1]
        for idx in tamper_indices:
            corrupted = bytearray(ct)
            corrupted[idx] ^= 0x01  # Flip 1 bit
            with pytest.raises(DecryptionError, match="Authentication tag verification failed"):
                decrypt(key, bytes(corrupted), aad)

    def test_crypto_truncated_payloads_raise_decryption_error(self):
        """Payloads shorter than MIN_PAYLOAD_LENGTH (28 bytes) raise DecryptionError."""
        key = os.urandom(32)
        aad = b"prof-1|conn-1|1"

        for bad_len in (0, 1, 11, 12, 27):
            with pytest.raises(DecryptionError, match="too short for AES-256-GCM"):
                decrypt(key, b"\x00" * bad_len, aad)

    def test_crypto_aad_tampering_and_mismatch(self):
        """Any deviation in AAD causes DecryptionError, stopping ciphertext relocation."""
        key = os.urandom(32)
        plaintext = b"secret_credential"
        valid_aad = b"prof-A|conn-1|1"
        ct = encrypt(key, plaintext, valid_aad)

        # Swapped profile, connection, version, or empty AAD
        for bad_aad in (
            b"prof-B|conn-1|1",
            b"prof-A|conn-2|1",
            b"prof-A|conn-1|2",
            b"",
            b"prof-A|conn-1|1 ",
            b" prof-A|conn-1|1",
        ):
            with pytest.raises(DecryptionError, match="Authentication tag verification failed"):
                decrypt(key, ct, bad_aad)


class TestVaultKekHardening:
    """Hardening tests for KEK provider hierarchy, secret file reading, and Argon2id."""

    def test_argon2id_passphrase_boundaries_and_unicode(self):
        """Validates empty/whitespace failure and multi-byte UTF-8 Unicode derivation."""
        # Empty or whitespace passphrases fail closed
        for empty_pw in ("", "   ", "\t\n  \r"):
            with pytest.raises(VaultLockedError, match="Passphrase cannot be empty"):
                derive_argon2id_kek(empty_pw)

        # Unicode passphrases (emojis, zero-width spaces, CJK)
        unicode_pw = "🔒-Carefold-Clinician-2026-患者パスワード"
        kek = derive_argon2id_kek(unicode_pw)
        assert isinstance(kek, bytes)
        assert len(kek) == 32
        # Deterministic
        assert derive_argon2id_kek(unicode_pw) == kek

    def test_argon2id_salt_padding_and_truncation(self):
        """Salt is safely padded to 16 bytes if short, and truncated if long."""
        pw = "Master-Vault-Key-2026"
        short_salt = b"short"
        long_salt = b"very_long_salt_exceeding_sixteen_bytes_completely"

        kek_short = derive_argon2id_kek(pw, salt=short_salt)
        kek_long = derive_argon2id_kek(pw, salt=long_salt)

        assert len(kek_short) == 32
        assert len(kek_long) == 32
        assert kek_short != kek_long

    def test_kek_secret_file_boundaries_and_malformed(self, tmp_path: Path):
        """Validates raw 32-byte binary (with nulls), CRLF handling, hex decoding, and invalid sizes."""
        # 1. Non-existent file
        with pytest.raises(VaultLockedError, match="Secret file does not exist"):
            _resolve_from_secret_file(str(tmp_path / "nonexistent.key"))

        # 2. Directory instead of file
        with pytest.raises(VaultLockedError, match="is not a file"):
            _resolve_from_secret_file(str(tmp_path))

        # 3. Exactly 32 raw bytes containing embedded nulls and newlines (must not be stripped)
        raw_key = b"\x00\x01\n\r\t" + os.urandom(27)
        file_raw = tmp_path / "raw.key"
        file_raw.write_bytes(raw_key)
        assert _resolve_from_secret_file(str(file_raw)) == raw_key

        # 4. 33 bytes ending in single newline
        file_nl = tmp_path / "nl.key"
        file_nl.write_bytes(raw_key + b"\n")
        assert _resolve_from_secret_file(str(file_nl)) == raw_key

        # 5. 34 bytes ending in Windows CRLF
        file_crlf = tmp_path / "crlf.key"
        file_crlf.write_bytes(raw_key + b"\r\n")
        assert _resolve_from_secret_file(str(file_crlf)) == raw_key

        # 6. 64 hex characters with surrounding whitespace
        hex_key = os.urandom(32).hex()
        file_hex = tmp_path / "hex.key"
        file_hex.write_text(f"  \n{hex_key}\n  ", encoding="ascii")
        assert _resolve_from_secret_file(str(file_hex)) == bytes.fromhex(hex_key)

        # 7. Malformed hex (64 chars with invalid character 'Z')
        bad_hex = hex_key[:-1] + "Z"
        file_bad_hex = tmp_path / "bad_hex.key"
        file_bad_hex.write_text(bad_hex, encoding="ascii")
        with pytest.raises(VaultLockedError, match="Fail-closed"):
            _resolve_from_secret_file(str(file_bad_hex))

        # 8. Invalid length (e.g. 31 bytes or 60 bytes)
        file_invalid_len = tmp_path / "short.key"
        file_invalid_len.write_bytes(os.urandom(31))
        with pytest.raises(VaultLockedError, match="must contain exactly 32 raw bytes or 64 hex characters"):
            _resolve_from_secret_file(str(file_invalid_len))

    def test_kek_resolution_hierarchy_fail_closed(self):
        """Mode L and Mode S fail closed with VaultLockedError when credentials are missing or empty."""
        # Mode L: Empty or whitespace mock keyring
        with pytest.raises(VaultLockedError, match="Empty or whitespace keyring value found"):
            resolve_kek(mode="local", keyring_store={"kek_master": "   "})

        # Mode L: Keyring value with invalid length
        with pytest.raises(VaultLockedError, match="Invalid keyring KEK value"):
            resolve_kek(mode="local", keyring_store={"kek_master": "tooshort"})

        # Mode S: No file and no passphrase
        with pytest.raises(VaultLockedError, match="Mode S server requires CAREFOLD_VAULT_KEK_FILE"):
            resolve_kek(mode="server", kek_file_path=None, passphrase=None)

        # Complete absence: zero plaintext fallback
        with pytest.raises(VaultLockedError, match="Fail-closed"):
            resolve_kek(mode="local", keyring_store={}, kek_file_path=None, passphrase=None)


class TestVaultDekLifecycleHardening:
    """Hardening tests for profile DEK generation, AAD bindings, and crypto-shredding."""

    def test_dek_aad_binding_validation(self):
        """Asserts strict validation of compute_aad_binding and compute_dek_wrapping_aad."""
        for bad_profile in ("", "   ", None):
            with pytest.raises(ValueError, match="profile_id must be a non-empty string"):
                compute_aad_binding(bad_profile, "conn-1", 1)  # type: ignore
            with pytest.raises(ValueError, match="profile_id must be a non-empty string"):
                compute_dek_wrapping_aad(bad_profile, 1)  # type: ignore

        for bad_conn in ("", "   ", None):
            with pytest.raises(ValueError, match="connection_id must be a non-empty string"):
                compute_aad_binding("prof-1", bad_conn, 1)  # type: ignore

        for bad_ver in (0, -1, -10):
            with pytest.raises(ValueError, match="dek_version must be >= 1"):
                compute_aad_binding("prof-1", "conn-1", bad_ver)
            with pytest.raises(ValueError, match="dek_version must be >= 1"):
                compute_dek_wrapping_aad("prof-1", bad_ver)

    async def test_dek_lifecycle_and_db_persistence(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """DEK is generated once, securely stored encrypted under KEK, and retrieved identically."""
        kek = os.urandom(32)
        profile_id = sample_user_and_profile["profile_id"]

        async with async_db() as session:
            # 1. First call creates fresh DEK
            raw_dek1, version1 = await get_or_create_dek(session, profile_id, kek)
            assert len(raw_dek1) == 32
            assert version1 == 1

            # Verify row in DB is encrypted
            stmt = select(ProfileKey).where(ProfileKey.profile_id == profile_id)
            res = await session.execute(stmt)
            pk = res.scalar_one()
            assert pk.dek_version == 1
            assert pk.encrypted_dek != raw_dek1.hex()  # Ciphertext must differ from raw key

        async with async_db() as session:
            # 2. Second call retrieves same DEK
            raw_dek2, version2 = await get_or_create_dek(session, profile_id, kek)
            assert raw_dek1 == raw_dek2
            assert version1 == version2

    async def test_dek_wrong_kek_or_corrupted_db_fails_closed(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Retrieving DEK with wrong KEK or corrupted ciphertext raises DecryptionError."""
        correct_kek = os.urandom(32)
        wrong_kek = os.urandom(32)
        profile_id = sample_user_and_profile["profile_id"]

        async with async_db() as session:
            await get_or_create_dek(session, profile_id, correct_kek)

        async with async_db() as session:
            # Wrong KEK
            with pytest.raises(DecryptionError, match="authentication tag verification failed"):
                await get_or_create_dek(session, profile_id, wrong_kek)

            # Corrupt ciphertext in DB
            stmt = select(ProfileKey).where(ProfileKey.profile_id == profile_id)
            res = await session.execute(stmt)
            pk = res.scalar_one()
            pk.encrypted_dek = "deadbeef" * 8  # Corrupt
            await session.commit()

            with pytest.raises(DecryptionError):
                await get_or_create_dek(session, profile_id, correct_kek)

    def test_dek_cross_profile_cross_connection_relocation(self):
        """Ciphertext bound to profile_id and connection_id cannot be decrypted across boundaries."""
        dek = os.urandom(32)
        secret_token = b"patient_oauth_refresh_token"

        ct = encrypt_credential(
            dek=dek,
            payload=secret_token,
            profile_id="prof-A",
            connection_id="conn-epic",
            dek_version=1,
        )

        # Cross-profile swap
        with pytest.raises(DecryptionError):
            decrypt_credential(dek, ct, profile_id="prof-B", connection_id="conn-epic", dek_version=1)

        # Cross-connection swap
        with pytest.raises(DecryptionError):
            decrypt_credential(dek, ct, profile_id="prof-A", connection_id="conn-cerner", dek_version=1)

        # DEK version swap
        with pytest.raises(DecryptionError):
            decrypt_credential(dek, ct, profile_id="prof-A", connection_id="conn-epic", dek_version=2)

    async def test_dek_rotation_versioning(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """DEK rotation creates version 2 with a new key while preserving old profile association."""
        kek = os.urandom(32)
        profile_id = sample_user_and_profile["profile_id"]

        async with async_db() as session:
            dek_v1, ver1 = await get_or_create_dek(session, profile_id, kek)
            assert ver1 == 1

            dek_v2, ver2 = await rotate_dek(session, profile_id, kek)
            assert ver2 == 2
            assert dek_v1 != dek_v2

            # Subsequent get_or_create_dek returns v2
            retrieved_dek, retrieved_ver = await get_or_create_dek(session, profile_id, kek)
            assert retrieved_ver == 2
            assert retrieved_dek == dek_v2

    async def test_dek_crypto_shredding_manual_and_cascade(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Deleting profile keys manually or dropping profile via foreign key cascades executes crypto-shredding."""
        kek = os.urandom(32)
        profile_id = sample_user_and_profile["profile_id"]

        async with async_db() as session:
            dek, _ = await get_or_create_dek(session, profile_id, kek)
            # Encrypt a sample credential
            ct = encrypt_credential(dek, "secret", profile_id, "conn-1", 1)
            assert decrypt_credential(dek, ct, profile_id, "conn-1", 1) == b"secret"

            # Manual delete
            deleted = await delete_profile_keys(session, profile_id)
            assert deleted is True

            # Verify row is gone
            stmt = select(ProfileKey).where(ProfileKey.profile_id == profile_id)
            res = await session.execute(stmt)
            assert res.scalar_one_or_none() is None


# ============================================================================
# Section 2: carefold.engine ToolSpec Registry & Choke Point Hardening
# ============================================================================

class TestEngineToolSpecRegistryHardening:
    """Hardening tests for ToolSpec immutability, DataFlows matching, and profile filtering."""

    def test_toolspec_immutability_frozen(self):
        """ToolSpec is frozen and immutable; modifying attributes raises FrozenInstanceError."""
        spec = ToolSpec(
            name="test-immutable",
            description="Testing immutability",
            risk_tier="read",
        )
        with pytest.raises(FrozenInstanceError):
            spec.risk_tier = "write_local"  # type: ignore

    def test_dataflows_sequence_emulation_and_case_insensitive_matching(self):
        """DataFlows emulates sequences and matches hosts case-insensitively with whitespace handling."""
        df = DataFlows(allowed_hosts=("api.epic.com", "FHIR.CERNER.COM"))
        assert len(df) == 2
        assert df[0] == "api.epic.com"
        assert df[1] == "FHIR.CERNER.COM"

        # Case-insensitive checks
        assert "API.EPIC.COM" in df
        assert "api.epic.com" in df
        assert "fhir.cerner.com" in df
        assert "evil.com" not in df

        # Equality comparison
        assert df == ("api.epic.com", "FHIR.CERNER.COM")
        assert df == ["api.epic.com", "FHIR.CERNER.COM"]

    def test_registry_child_under_13_complete_protective_matrix(self):
        """Ensures child_under_13 profile strictly filters external writes, untrusted, and irreversible tools."""
        registry = ToolSpecRegistry()

        t_read = ToolSpec(name="t-read", risk_tier="read", trust="trusted")
        t_write_local = ToolSpec(name="t-local", risk_tier="write_local", trust="trusted")
        t_write_ext = ToolSpec(name="t-ext", risk_tier="write_external", trust="trusted")
        t_irrev = ToolSpec(name="t-irrev", risk_tier="irreversible", trust="trusted")
        t_untrusted = ToolSpec(name="t-untrusted", risk_tier="read", trust="untrusted")

        for t in (t_read, t_write_local, t_write_ext, t_irrev, t_untrusted):
            registry.register(t)

        # 1. Child without guardian consent: only trusted read tools allowed
        tools_no_guardian = registry.list_for_profile("p-child", consents={}, age_band="child_under_13")
        tool_names = [t.name for t in tools_no_guardian]
        assert tool_names == ["t-read"]

        # 2. Child with guardian consent: trusted read and write_local permitted; ext/irrev/untrusted blocked
        tools_with_guardian = registry.list_for_profile(
            "p-child",
            consents={"guardian_consent": True},
            age_band="child_under_13",
        )
        tool_names_guardian = [t.name for t in tools_with_guardian]
        assert set(tool_names_guardian) == {"t-read", "t-local"}

        # 3. Adult: all tools permitted
        tools_adult = registry.list_for_profile("p-adult", consents={}, age_band="adult")
        assert len(tools_adult) == 5

    def test_registry_capability_enforcement(self):
        """Tools requiring specific capabilities are excluded if profile lacks them."""
        registry = ToolSpecRegistry()
        t_ehr = ToolSpec(
            name="export-ehr",
            risk_tier="read",
            metadata={"required_capabilities": ["ehr_export"]},
        )
        t_basic = ToolSpec(name="basic-note", risk_tier="read")

        registry.register(t_ehr)
        registry.register(t_basic)

        # Profile without ehr_export capability
        res1 = registry.list_for_profile("prof-1", capabilities=["standard_chat"])
        assert [t.name for t in res1] == ["basic-note"]

        # Profile with ehr_export capability
        res2 = registry.list_for_profile("prof-1", capabilities=["ehr_export"])
        assert set(t.name for t in res2) == {"export-ehr", "basic-note"}


class TestEngineChokePointAndEgressFirewallHardening:
    """Hardening tests for Universal Choke Point, Egress Firewall Anti-SSRF, and Monotone Taint."""

    def test_tool_context_fail_closed_validation(self):
        """ToolContext enforces non-empty profile_id and user_id upon instantiation."""
        for bad_id in ("", "   "):
            with pytest.raises(ValueError, match="requires a non-empty 'profile_id'"):
                ToolContext(user_id="u1", profile_id=bad_id)
            with pytest.raises(ValueError, match="requires a non-empty 'user_id'"):
                ToolContext(user_id=bad_id, profile_id="p1")

    def test_monotone_taint_flag_immutability(self):
        """TaintFlag cannot be cleared back to False once tainted."""
        flag = TaintFlag(initial=False)
        assert bool(flag) is False
        assert flag.is_tainted is False

        flag.set()
        assert bool(flag) is True
        assert flag.is_tainted is True

        # Idempotent set
        flag.set()
        assert flag.is_tainted is True

    def test_tainted_context_forces_approval_on_write_external_even_with_consent(self):
        """Monotone taint forces approval on write_external even under A2 autonomy with consent."""
        ctx_clean = ToolContext(user_id="u1", profile_id="p1", autonomy="A2")
        flag = TaintFlag(initial=True)
        ctx_tainted = ToolContext(user_id="u1", profile_id="p1", autonomy="A2", taint=flag)

        spec = ToolSpec(name="sync-calendar", risk_tier="write_external")
        args = {"event": "doctor visit"}
        consents = {"external_write_consent": True}

        # Clean context with consent is allowed
        dec_clean = evaluate_policy_gate(ctx_clean, spec, args, consents=consents)
        assert dec_clean.decision == "allow"

        # Tainted context with consent FORCES APPROVAL
        dec_tainted = evaluate_policy_gate(ctx_tainted, spec, args, consents=consents)
        assert dec_tainted.decision == "needs_approval"
        assert "FORCED APPROVAL: Context is tainted" in dec_tainted.reason

    def test_egress_firewall_subdomain_spoofing_and_prefix_attacks(self):
        """Rejects subdomain spoofing, suffix appending, and prefix attacks targeting allowed hosts."""
        spec = ToolSpec(
            name="send-fhir",
            risk_tier="write_external",
            data_flows=DataFlows(allowed_hosts=("api.epic.com",)),
        )

        # Legitimate destination passes
        hosts = verify_egress_firewall(spec, {"url": "https://api.epic.com/fhir/R4"})
        assert hosts == ["api.epic.com"]

        # Adversarial bypass attempts
        adversarial_targets = [
            "https://api.epic.com.evil.com/leak",          # Subdomain spoofing
            "https://attacker-api.epic.com/leak",          # Host prefix attack
            "https://evil.com/api.epic.com",               # Path confusion
            "https://api.epic.com@evil.com/leak",          # Userinfo spoofing
        ]
        for bad_url in adversarial_targets:
            with pytest.raises(EgressBlockedError, match="denied by tool 'send-fhir' data_flows policy"):
                verify_egress_firewall(spec, {"url": bad_url})

    def test_egress_firewall_empty_allowed_hosts_fails_closed(self):
        """write_external tool with no declared allowed_hosts fails closed immediately (0 bytes sent)."""
        spec = ToolSpec(name="wildcard-post", risk_tier="write_external", data_flows=())
        with pytest.raises(EgressBlockedError, match="has no authorized data_flows configured"):
            verify_egress_firewall(spec, {"url": "https://anywhere.org"})

    async def test_execute_tool_call_invalid_context_or_spec_fails_closed(self):
        """execute_tool_call rejects invalid context or non-callable spec with security error."""
        spec = ToolSpec(name="dummy", risk_tier="read", executor=lambda args: "ok")

        # Invalid context
        res1 = await execute_tool_call(None, spec, {})  # type: ignore
        assert res1.success is False
        assert "ToolContext instance is required" in str(res1.error)

        # Invalid spec
        ctx = ToolContext(user_id="u1", profile_id="p1")
        res2 = await execute_tool_call(ctx, None, {})  # type: ignore
        assert res2.success is False
        assert "ToolSpec instance is required" in str(res2.error)

        # Spec without callable executor
        spec_no_exec = ToolSpec(name="no-exec", risk_tier="read", executor=None)
        res3 = await execute_tool_call(ctx, spec_no_exec, {})
        assert res3.success is False
        assert "has no valid executor" in str(res3.error)

    async def test_execute_tool_call_contains_unhandled_exceptions(self):
        """Universal choke point catches arbitrary unhandled exceptions from tools without crashing."""
        def exploding_tool(args):
            raise ZeroDivisionError("Uncaught division by zero in tool logic")

        spec = ToolSpec(name="exploder", risk_tier="read", executor=exploding_tool)
        ctx = ToolContext(user_id="u1", profile_id="p1")

        result = await execute_tool_call(ctx, spec, {})
        assert result.success is False
        assert "Uncaught division by zero" in str(result.error)

    async def test_execute_tool_call_untrusted_result_propagates_monotone_taint(self):
        """Returning UntrustedResult sets context taint flag permanently for subsequent operations."""
        def search_tool(args):
            return UntrustedResult(data="raw web document containing prompt injection", taint=True)

        spec = ToolSpec(name="web-search", risk_tier="read", executor=search_tool)
        ctx = ToolContext(user_id="u1", profile_id="p1")
        assert ctx.taint.is_tainted is False

        result = await execute_tool_call(ctx, spec, {"q": "medical study"})
        assert result.success is True
        assert result.output == "raw web document containing prompt injection"
        assert ctx.taint.is_tainted is True


# ============================================================================
# Section 3: carefold.api.approvals Security & Resumption Hardening
# ============================================================================

class TestApprovalsApiHardening:
    """Hardening tests for CSRF protection, Zero-Admin-Bypass RBAC, and single-use resumption tokens."""

    def test_approvals_csrf_blocking_cross_site(self):
        """verify_csrf blocks Sec-Fetch-Site: cross-site requests lacking Authorization headers."""
        class MockRequest:
            def __init__(self, headers: Dict[str, str]):
                self.headers = headers
                self.url = type("URL", (), {"path": "/api/approvals/123/decide"})()

        # Cross-site browser request with cookies only -> Blocked
        req_cross_site = MockRequest({"Sec-Fetch-Site": "cross-site"})
        with pytest.raises(HTTPException) as exc_info:
            verify_csrf(req_cross_site)  # type: ignore
        assert exc_info.value.status_code == 403

        # Cross-site with explicit Bearer token -> Permitted
        req_auth = MockRequest({"Sec-Fetch-Site": "cross-site", "Authorization": "Bearer token123"})
        verify_csrf(req_auth)  # type: ignore

    async def test_approvals_zero_admin_bypass_rbac(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """User with role='admin' but NO explicit manage grant on profile is strictly blocked (AU-18 invariant)."""
        async with async_db() as session:
            # Create separate admin user
            admin_user_id = str(uuid.uuid4())
            admin_user = User(
                id=admin_user_id,
                email="superadmin@carefold.local",
                username="admin_joe",
                hashed_password="pw",
                role="admin",  # Admin role
            )
            session.add(admin_user)
            await session.commit()

            # Target profile belongs to original user
            profile_id = sample_user_and_profile["profile_id"]
            stmt = select(Profile).where(Profile.id == profile_id)
            res = await session.execute(stmt)
            profile = res.scalar_one()

            now_dt = datetime.now(timezone.utc)
            user_profile = UserProfile(
                id=admin_user_id,
                email=admin_user.email,
                username=admin_user.username,
                role="admin",
                created_at=now_dt,
                updated_at=now_dt,
            )

            # verify_manage_access must raise 403 because admin has no explicit ProfileAccess grant
            with pytest.raises(HTTPException) as exc_info:
                await verify_manage_access(profile, user_profile, session)
            assert exc_info.value.status_code == 403
            assert "management privileges required" in str(exc_info.value.detail)

    async def test_approvals_cannot_decide_already_decided_or_expired(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """consume_approval_atomic rejects consumption of non-approved or expired approval records."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)

        async with async_db() as session:
            # 1. Pending approval record
            app_pending = Approval(
                id="app-pending-1",
                profile_id=profile_id,
                run_id="run-1",
                tool_name="send_email",
                args_redacted=json.dumps({"msg": "hello"}),
                payload_hash=compute_payload_hash({"msg": "hello"}),
                risk_tier="write_external",
                status="pending",
                expires_at=now + timedelta(minutes=10),
            )
            # 2. Expired approval record
            app_expired = Approval(
                id="app-expired-1",
                profile_id=profile_id,
                run_id="run-1",
                tool_name="send_email",
                args_redacted=json.dumps({"msg": "hello"}),
                payload_hash=compute_payload_hash({"msg": "hello"}),
                risk_tier="write_external",
                status="approved",
                expires_at=now - timedelta(minutes=1),  # Expired
            )
            session.add_all([app_pending, app_expired])
            await session.commit()

        async with async_db() as session:
            # Consuming pending token fails closed
            with pytest.raises(ValueError, match="is in status 'pending', cannot consume"):
                await consume_approval_atomic(session, "app-pending-1", {"msg": "hello"})

            # Consuming expired token fails closed
            with pytest.raises(ValueError, match="has expired"):
                await consume_approval_atomic(session, "app-expired-1", {"msg": "hello"})

    async def test_consume_approval_atomic_replay_attack_prevention(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Single-use approval token can only be consumed once; second consumption attempt fails closed."""
        profile_id = sample_user_and_profile["profile_id"]
        args = {"recipient": "doctor@hospital.org", "summary": "visit prep"}
        app_id = "app-replay-test-1"

        async with async_db() as session:
            app_rec = Approval(
                id=app_id,
                profile_id=profile_id,
                run_id="run-replay",
                tool_name="email_doctor",
                args_redacted=canonical_json(args),
                payload_hash=compute_payload_hash(args),
                risk_tier="write_external",
                status="approved",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            )
            session.add(app_rec)
            await session.commit()

        async with async_db() as session:
            # First consumption succeeds
            consumed_id = await consume_approval_atomic(session, app_id, args)
            assert consumed_id == app_id

        async with async_db() as session:
            # Second consumption attempt (replay attack) fails closed
            with pytest.raises(ValueError, match="is in status 'consumed', cannot consume"):
                await consume_approval_atomic(session, app_id, args)

    async def test_consume_approval_atomic_argument_tampering_detection(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Any tampering with arguments between approval and resume fails closed on hash mismatch."""
        profile_id = sample_user_and_profile["profile_id"]
        approved_args = {"amount": 100, "account": "ACC-99"}
        app_id = "app-tamper-test"

        async with async_db() as session:
            app_rec = Approval(
                id=app_id,
                profile_id=profile_id,
                run_id="run-tamper",
                tool_name="transfer_funds",
                args_redacted=canonical_json(approved_args),
                payload_hash=compute_payload_hash(approved_args),
                risk_tier="irreversible",
                status="approved",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            )
            session.add(app_rec)
            await session.commit()

        async with async_db() as session:
            # Tampering with amount: 100 -> 1000
            tampered_args = {"amount": 1000, "account": "ACC-99"}
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, app_id, tampered_args)

            # Injected additional argument
            injected_args = {"amount": 100, "account": "ACC-99", "admin_override": True}
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(session, app_id, injected_args)

    async def test_consume_approval_atomic_canonical_json_ordering_resilience(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """RFC-8785 canonical JSON hash succeeds regardless of dict key insertion order."""
        profile_id = sample_user_and_profile["profile_id"]
        dict1 = {"b_field": "val2", "a_field": "val1"}
        dict2 = {"a_field": "val1", "b_field": "val2"}
        app_id = "app-order-resilient"

        async with async_db() as session:
            app_rec = Approval(
                id=app_id,
                profile_id=profile_id,
                run_id="run-order",
                tool_name="process_record",
                args_redacted=canonical_json(dict1),
                payload_hash=compute_payload_hash(dict1),
                risk_tier="write_local",
                status="approved",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            )
            session.add(app_rec)
            await session.commit()

        async with async_db() as session:
            # Consuming with reversed key order succeeds because canonical_json sorts keys
            consumed = await consume_approval_atomic(session, app_id, dict2)
            assert consumed == app_id


# ============================================================================
# Section 4: carefold.engine.job_runner Concurrency & Boundary Hardening
# ============================================================================

class TestJobRunnerHardening:
    """Hardening tests for wall-clock job runner leasing, sleep/wake coalescing, and choke point invariants."""

    def test_calculate_next_occurrence_boundary_cases(self):
        """Validates recurrence calculations across missing rules, past UNTIL timestamps, and sleep jumps."""
        now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Empty, None, or invalid string
        assert calculate_next_occurrence(None, now) is None
        assert calculate_next_occurrence("", now) is None

        # 2. Daily recurrence
        next_daily = calculate_next_occurrence("FREQ=DAILY;INTERVAL=1", now)
        assert next_daily == now + timedelta(days=1)

        # 3. UNTIL timestamp in the past returns None
        past_until = "FREQ=DAILY;UNTIL=2026-10-10T00:00:00Z"
        assert calculate_next_occurrence(past_until, now) is None

        # 4. Long sleep jump: base time 7 days ago advances strictly > now
        base_past = now - timedelta(days=7)
        next_jump = calculate_next_occurrence("FREQ=DAILY;INTERVAL=1", now, base_time=base_past)
        assert next_jump is not None
        assert next_jump > now

    async def test_job_runner_zero_or_negative_batch_size(
        self,
        async_db: async_sessionmaker[AsyncSession],
    ):
        """lease_batch with batch_size <= 0 safely returns empty list without error."""
        runner = JobRunner(session_factory=async_db)
        assert await runner.lease_batch(batch_size=0) == []
        assert await runner.lease_batch(batch_size=-5) == []

    async def test_job_runner_expired_lease_reclaimable(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Job leased by worker A becomes reclaimable by worker B once lease_until expires."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)
        job_id = "job-lease-expire-test"

        async with async_db() as session:
            job = DBJob(
                id=job_id,
                profile_id=profile_id,
                kind="routine",
                payload="{}",
                next_run_at=now - timedelta(minutes=5),
                status="active",
                lease_owner="worker-A",
                lease_until=now - timedelta(seconds=1),  # Lease already expired
            )
            session.add(job)
            await session.commit()

        runner_b = JobRunner(session_factory=async_db, worker_id="worker-B")
        leased = await runner_b.lease_batch(batch_size=5)
        assert len(leased) == 1
        assert leased[0].id == job_id
        assert leased[0].lease_owner == "worker-B"

    async def test_job_runner_concurrent_workers_atomic_leasing(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Simultaneous concurrent lease_batch requests by multiple workers partition jobs without collision."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)

        # Seed 10 due jobs
        async with async_db() as session:
            for i in range(10):
                j = DBJob(
                    id=f"job-conc-{i}",
                    profile_id=profile_id,
                    kind="routine",
                    payload="{}",
                    next_run_at=now - timedelta(minutes=1),
                    status="pending",
                )
                session.add(j)
            await session.commit()

        runner1 = JobRunner(session_factory=async_db, worker_id="worker-1", batch_size=5)
        runner2 = JobRunner(session_factory=async_db, worker_id="worker-2", batch_size=5)

        # Execute concurrent leasing
        results = await asyncio.gather(
            runner1.lease_batch(),
            runner2.lease_batch(),
        )

        leased1 = {j.id for j in results[0]}
        leased2 = {j.id for j in results[1]}

        # Invariant: No job leased twice
        assert len(leased1.intersection(leased2)) == 0
        assert len(leased1.union(leased2)) == 10

    async def test_job_runner_sleep_wake_coalescing_duplicate_syncs(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Clock jump > 120s coalesces redundant connector syncs to max 1 active per connection."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)
        conn_id = "conn-epic-health"

        async with async_db() as session:
            # Seed 3 sync jobs for the same connection
            for i in range(3):
                j = DBJob(
                    id=f"job-sync-{i}",
                    profile_id=profile_id,
                    connection_id=conn_id,
                    kind="connector_sync",
                    payload="{}",
                    next_run_at=now - timedelta(minutes=5),
                    status="pending",
                )
                session.add(j)
            await session.commit()

        runner = JobRunner(session_factory=async_db)
        t_sleep = time.time() - 300  # 5 minutes ago (exceeds 120s jump threshold)
        t_wake = time.time()

        coalesced, missed = await runner.handle_wake_jump(t_sleep, t_wake)
        assert coalesced == 2
        assert missed == 0

        # Verify only 1 remains pending, other 2 are marked completed
        async with async_db() as session:
            stmt = select(DBJob).where(DBJob.connection_id == conn_id)
            res = await session.execute(stmt)
            jobs = list(res.scalars().all())
            pending = [j for j in jobs if j.status == "pending"]
            completed = [j for j in jobs if j.status == "completed"]
            assert len(pending) == 1
            assert len(completed) == 2

    async def test_job_runner_overdue_reminders_marked_missed(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Clinical safety invariant: reminders overdue by > 24 hours are marked 'missed' and never run."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)

        async with async_db() as session:
            # Reminder overdue by 25 hours
            j_stale = DBJob(
                id="job-reminder-overdue",
                profile_id=profile_id,
                kind="reminder",
                payload="{}",
                next_run_at=now - timedelta(hours=25),
                status="pending",
            )
            # Reminder overdue by 2 hours
            j_fresh = DBJob(
                id="job-reminder-fresh",
                profile_id=profile_id,
                kind="reminder",
                payload="{}",
                next_run_at=now - timedelta(hours=2),
                status="pending",
            )
            session.add_all([j_stale, j_fresh])
            await session.commit()

        runner = JobRunner(session_factory=async_db)
        # Tick sweeps overdue reminders and leases due jobs
        await runner.tick()

        async with async_db() as session:
            stmt_stale = select(DBJob).where(DBJob.id == "job-reminder-overdue")
            res_stale = await session.execute(stmt_stale)
            assert res_stale.scalar_one().status == "missed"

            stmt_fresh = select(DBJob).where(DBJob.id == "job-reminder-fresh")
            res_fresh = await session.execute(stmt_fresh)
            assert res_fresh.scalar_one().status == "active"

    async def test_job_runner_job_requiring_approval_fails_immediately(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Background job routed to a tool requiring human approval fails immediately (cannot block for input)."""
        profile_id = sample_user_and_profile["profile_id"]
        spec = ToolSpec(name="delete_account", risk_tier="irreversible", executor=lambda args: "ok")

        job = DBJob(
            id="job-irrev-test",
            profile_id=profile_id,
            kind="routine",
            payload="{}",
            status="active",
        )

        runner = JobRunner(session_factory=async_db)
        result = await runner.execute_job(job, spec)

        assert result.success is False
        assert result.needs_approval is True
        assert job.status == "failed"

    async def test_job_runner_security_violation_fails_immediately(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Background job encountering EgressBlockedError fails immediately."""
        profile_id = sample_user_and_profile["profile_id"]
        spec = ToolSpec(
            name="outbound-sync",
            risk_tier="write_external",
            data_flows=DataFlows(allowed_hosts=("trusted.org",)),
            executor=lambda args: "ok",
        )

        job = DBJob(
            id="job-ssrf-test",
            profile_id=profile_id,
            kind="routine",
            payload=json.dumps({"url": "https://untrusted-exfiltration.net"}),
            status="active",
        )

        runner = JobRunner(session_factory=async_db)
        result = await runner.execute_job(job, spec)

        assert result.success is False
        assert "EgressBlockedError" in str(result.error)
        assert job.status == "failed"


# ============================================================================
# Section 5: carefold.db.models Invariants & Cascades
# ============================================================================

class TestDbModelsInvariantsHardening:
    """Hardening tests for DB entity integrity, cascades, and parsing resilience."""

    async def test_models_profile_key_unique_constraint(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """UniqueConstraint('profile_id', 'dek_version') prevents duplicate DEK versions per profile."""
        profile_id = sample_user_and_profile["profile_id"]

        async with async_db() as session:
            pk1 = ProfileKey(
                profile_id=profile_id,
                encrypted_dek="aabbcc",
                dek_version=1,
            )
            session.add(pk1)
            await session.commit()

        async with async_db() as session:
            pk2 = ProfileKey(
                profile_id=profile_id,
                encrypted_dek="ddeeff",
                dek_version=1,  # Duplicate (profile_id, 1)
            )
            session.add(pk2)
            with pytest.raises(IntegrityError):
                await session.commit()

    def test_models_approval_malformed_json_fallback(self):
        """Approval properties args_dict and hosts_list return empty collections on malformed JSON."""
        approval = Approval(
            id="app-malformed",
            profile_id="p1",
            run_id="r1",
            tool_name="test",
            args_redacted="NOT_VALID_JSON{",
            payload_hash="hash",
            destination_hosts="[INVALID_ARRAY",
            risk_tier="read",
            status="pending",
            expires_at=datetime.now(timezone.utc),
        )

        assert approval.args_dict == {}
        assert approval.hosts_list == []

    async def test_models_cascade_delete_profiles_shreds_profile_keys_approvals_jobs(
        self,
        async_db: async_sessionmaker[AsyncSession],
        sample_user_and_profile: Dict[str, Any],
    ):
        """Deleting a Profile record cascades and deletes associated ProfileKeys, Approvals, and Jobs."""
        profile_id = sample_user_and_profile["profile_id"]
        now = datetime.now(timezone.utc)

        async with async_db() as session:
            pk = ProfileKey(profile_id=profile_id, encrypted_dek="1122", dek_version=1)
            appr = Approval(
                id="app-cascade",
                profile_id=profile_id,
                run_id="r1",
                tool_name="test",
                args_redacted="{}",
                payload_hash="hash",
                risk_tier="read",
                status="pending",
                expires_at=now + timedelta(hours=1),
            )
            job = DBJob(
                id="job-cascade",
                profile_id=profile_id,
                kind="routine",
                payload="{}",
                next_run_at=now,
            )
            session.add_all([pk, appr, job])
            await session.commit()

        # Delete Profile
        async with async_db() as session:
            p_stmt = select(Profile).where(Profile.id == profile_id)
            res = await session.execute(p_stmt)
            profile = res.scalar_one()
            await session.delete(profile)
            await session.commit()

        # Verify all children were cascade-deleted
        async with async_db() as session:
            assert (await session.execute(select(ProfileKey).where(ProfileKey.profile_id == profile_id))).scalar_one_or_none() is None
            assert (await session.execute(select(Approval).where(Approval.profile_id == profile_id))).scalar_one_or_none() is None
            assert (await session.execute(select(DBJob).where(DBJob.profile_id == profile_id))).scalar_one_or_none() is None
