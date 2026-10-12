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

"""Adversarial Empirical Stress Testing Suite for Audit Logging & Payload Hashes (AU-06 / #165, R5).

Empirically challenges:
1. Deterministic SHA-256 payload hashing:
   - Known test payload golden vectors (primitives, dicts, lists, nested).
   - Key order invariance under complex combinatorial dictionary shuffling.
   - Empty, None, and whitespace payload edge cases.
   - Multi-language Unicode, emojis, null bytes, and control characters.
   - Deeply nested structures (30 levels deep) and large scale payloads.
   - Non-standard types (datetime, custom objects) and cyclic references (graceful failure).
2. SQL database persistence:
   - Full schema field fidelity across all 13 columns in `audit_events`.
   - Handling of minimal / NULL optional fields.
   - Foreign key lifecycle and cascade retention (ON DELETE SET NULL).
   - End-to-end population via `record_audit` with all parameters.
3. Non-blocking fault isolation:
   - Simulated database disconnection (OperationalError).
   - Session factory crash (RuntimeError / connection pool exhaustion).
   - In-flight commit failure (SQLAlchemyError).
   - Simultaneous catastrophic failure of BOTH SQL database and secondary JSONL file sink.
   - Preservation of primary clinical agent workflow execution despite audit sink failure.
4. Secondary JSONL sink concurrency and integrity under high load:
   - Massively concurrent asynchronous writes (500 events across 50 concurrent tasks).
   - Multi-threaded concurrency across Python OS threads.
   - Concurrent reader / writer contention without corruption or decode errors.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from typing import Any, AsyncIterator, Dict, List
import uuid
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_db
from carefold.audit.logger import (
    AuditLogger,
    compute_payload_hash,
    get_recent_audit_events,
    read_recent_audit_events,
    record_audit,
)
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import reset_auth_port, set_auth_port
from carefold.config import settings
from carefold.db.models import AuditEventRecord, Profile, User
from carefold.db.session import create_db_engine, get_session_factory, init_db
from carefold.main import app
from carefold.schemas.audit import AuditEvent


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
async def adversarial_audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sets up an isolated database, local SQL auth provider, and FastAPI dependencies."""
    test_home = tmp_path / ".carefold_adv"
    test_home.mkdir(parents=True, exist_ok=True)
    logs_dir = test_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite+aiosqlite:///{test_home}/carefold.db"
    engine = create_db_engine(db_url)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    sql_auth = SqlAuthAdapter(session_factory=session_factory)

    audit_file = logs_dir / "audit.jsonl"

    monkeypatch.setattr(settings, "auth_provider", "local")
    monkeypatch.setattr(settings, "home_dir", test_home)
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "audit_log_path", audit_file)
    set_auth_port(sql_auth)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {
            "home": test_home,
            "logs_dir": logs_dir,
            "audit_file": audit_file,
            "session_factory": session_factory,
            "engine": engine,
            "auth": sql_auth,
        }
    finally:
        app.dependency_overrides.clear()
        reset_auth_port()
        await engine.dispose()


# =============================================================================
# 1. DETERMINISTIC SHA-256 PAYLOAD HASHING TESTS
# =============================================================================

class TestPayloadHashAdversarial:
    """Empirical adversarial tests for deterministic SHA-256 payload hashing."""

    def test_known_test_payload_golden_vectors(self):
        """Verifies that compute_payload_hash precisely matches precomputed golden vectors."""
        test_cases = [
            (
                {"tool": "attach-read", "args": {"page": 1, "path": "cardiac_notes.pdf"}},
                # Canonical: {"args": {"page": 1, "path": "cardiac_notes.pdf"}, "tool": "attach-read"}
                "034b4d3a6868f1f7ab6b9159080eba57f3fc9377c2cd842589fe31ce35e7c218",
            ),
            (
                [1, 2, "three", {"four": 4}],
                # Canonical: [1, 2, "three", {"four": 4}]
                "facdb3cb0d82650eed4c78138c5815bf72140ec238db2dd513e643435bf2e819",
            ),
            (
                "plain string payload",
                # Canonical: "plain string payload" (quoted json string)
                "b41cc5f7b2ba6974afef66c146d87ccf4e77119521f8b8f904124c9c62322236",
            ),
            (
                1234567890,
                # Canonical: 1234567890
                "c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646",
            ),
            (
                True,
                # Canonical: true
                "b5bea41b6c623f7c09f1bf24dcae58ebab3c0cdd90ad966bc43a45b44867e12b",
            ),
        ]

        for payload, expected_sha in test_cases:
            actual_sha = compute_payload_hash(payload)
            # Recompute locally using hashlib over canonical json
            recomputed = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            assert actual_sha == recomputed, f"Mismatch with canonical calculation for {payload}"
            assert actual_sha == expected_sha, f"Mismatch with golden vector for {payload}: got {actual_sha}, expected {expected_sha}"

    def test_empty_none_and_whitespace_edge_cases(self):
        """Verifies behavior for None, empty strings, whitespace, empty collections, and nested nulls."""
        # 1. Null / empty string / whitespace must return None
        assert compute_payload_hash(None) is None
        assert compute_payload_hash("") is None
        assert compute_payload_hash("   ") is None
        assert compute_payload_hash("\t\r\n ") is None

        # 2. Empty collections are valid JSON tokens ("{}" and "[]") and must hash deterministically
        expected_empty_dict = hashlib.sha256(b"{}").hexdigest()
        assert compute_payload_hash({}) == expected_empty_dict
        assert compute_payload_hash({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

        expected_empty_list = hashlib.sha256(b"[]").hexdigest()
        assert compute_payload_hash([]) == expected_empty_list
        assert compute_payload_hash([]) == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"

        # 3. Structures with empty/none values inside must hash deterministically
        h_nested_none = compute_payload_hash({"key": None})
        assert h_nested_none is not None
        assert h_nested_none == hashlib.sha256(b'{"key": null}').hexdigest()

        h_nested_empty_str = compute_payload_hash({"key": ""})
        assert h_nested_empty_str is not None
        assert h_nested_empty_str == hashlib.sha256(b'{"key": ""}').hexdigest()

    def test_combinatorial_key_order_invariance(self):
        """Verifies key order invariance across extensive combinatorial permutations."""
        keys_l1 = ["alpha", "beta", "gamma", "delta", "epsilon"]
        keys_l2 = ["one", "two", "three", "four", "five"]
        keys_l3 = ["apple", "banana", "cherry", "date", "elderberry"]

        # Build baseline canonical dictionary
        base_dict = {
            k1: {
                k2: {
                    k3: f"val_{k1}_{k2}_{k3}"
                    for k3 in keys_l3
                }
                for k2 in keys_l2
            }
            for k1 in keys_l1
        }
        baseline_hash = compute_payload_hash(base_dict)
        assert baseline_hash is not None

        # Generate 25 distinct permutations of key insertion order
        for iteration in range(25):
            shuffled_l1 = list(keys_l1)
            random.seed(iteration)
            random.shuffle(shuffled_l1)

            permuted_dict = {}
            for k1 in shuffled_l1:
                shuffled_l2 = list(keys_l2)
                random.shuffle(shuffled_l2)
                inner_l2 = {}
                for k2 in shuffled_l2:
                    shuffled_l3 = list(keys_l3)
                    random.shuffle(shuffled_l3)
                    inner_l3 = {}
                    for k3 in shuffled_l3:
                        inner_l3[k3] = f"val_{k1}_{k2}_{k3}"
                    inner_l2[k2] = inner_l3
                permuted_dict[k1] = inner_l2

            permuted_hash = compute_payload_hash(permuted_dict)
            assert permuted_hash == baseline_hash, (
                f"Iteration {iteration}: Hash differed under key permutation! "
                f"Expected {baseline_hash}, got {permuted_hash}"
            )

    def test_unicode_special_characters_and_byte_integrity(self):
        """Verifies hashing across multi-byte Unicode scripts, medical emojis, and null bytes."""
        payload = {
            "specialties": {
                "japanese": "心臓病学 (Cardiology)",
                "arabic": "أمراض القلب والأوعية الدموية",
                "hindi": "हृदय रोग विशेषज्ञ",
                "russian": "Кардиологическое отделение",
                "greek": "Καρδιολογική κλινική",
            },
            "emojis": "🩺 💊 🩸 🧠 🧬 🚨 💉 🏥",
            "control_chars": "Line1\nLine2\r\nTab\tBackslash\\Quote\"Slash/",
            "null_byte": "embedded\x00null\x00byte",
        }

        h1 = compute_payload_hash(payload)
        h2 = compute_payload_hash(payload)

        assert h1 is not None
        assert len(h1) == 64
        assert h1 == h2, "Hash must be strictly deterministic across calls"

        # Verify against independent canonical computation
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        assert h1 == expected

    def test_deeply_nested_structures_and_large_payloads(self):
        """Verifies resilience and performance on deeply nested structures and high-cardinality payloads."""
        # 1. 30 levels of nested dictionary and list nesting
        nested = {"deep_value": "clinical_finding"}
        for level in range(30):
            nested = {"level": level, "child": [nested]}

        nested_hash = compute_payload_hash(nested)
        assert nested_hash is not None
        assert len(nested_hash) == 64

        # 2. High-cardinality payload (2,500 distinct items)
        large_dict = {f"metric_{i:04d}": i * 1.5 for i in range(2500)}
        large_hash = compute_payload_hash(large_dict)
        assert large_hash is not None
        assert len(large_hash) == 64

    def test_unserializable_and_cyclic_payloads_graceful_handling(self):
        """Verifies that non-standard objects serialize via default=str, and cyclic structures do not crash."""
        # 1. Datetime and custom object with __str__
        class CustomClass:
            def __str__(self):
                return "custom_clinical_spec"

        payload_with_custom = {
            "timestamp": datetime(2026, 10, 12, 1, 0, 0, tzinfo=timezone.utc),
            "custom": CustomClass(),
            "uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        }
        hash_custom = compute_payload_hash(payload_with_custom)
        assert hash_custom is not None
        assert len(hash_custom) == 64

        # 2. Cyclic reference: must catch exception and return None without raising RecursionError
        cyclic: Dict[str, Any] = {"name": "cyclic"}
        cyclic["self"] = cyclic

        cyclic_hash = compute_payload_hash(cyclic)
        assert cyclic_hash is None, "Cyclic structure must be caught gracefully and return None"


# =============================================================================
# 2. SQL DATABASE PERSISTENCE TESTS
# =============================================================================

class TestSqlPersistenceIntegrity:
    """Empirical adversarial tests for relational SQL persistence of audit events."""

    @pytest.mark.asyncio
    async def test_full_schema_field_fidelity(self, adversarial_audit_env):
        """Verifies all 13 columns in audit_events are stored and retrieved with exact fidelity."""
        session_factory = adversarial_audit_env["session_factory"]

        test_user_id = str(uuid.uuid4())
        test_profile_id = str(uuid.uuid4())
        test_event_id = str(uuid.uuid4())
        fixed_ts = datetime(2026, 10, 12, 2, 15, 30, tzinfo=timezone.utc)

        # 1. Prepopulate User and Profile
        async with session_factory() as db:
            user = User(
                id=test_user_id,
                email="fidelity@carefold.test",
                username="fidelity_user",
                hashed_password="hashed_pw",
                role="member",
            )
            profile = Profile(
                id=test_profile_id,
                user_id=test_user_id,
                name="Fidelity Profile",
                relationship="self",
            )
            db.add_all([user, profile])
            await db.commit()

        # 2. Construct AuditEventRecord with EVERY column populated
        raw_detail = {
            "agent_id": "cardiology-guide",
            "skill_id": "cardiology-prep",
            "skill_version": "1.0.0",
            "reason": "Emergency boundary evaluation passed",
            "duration_ms": 245,
            "thread_id": "thread-fidelity-001",
        }
        detail_json = json.dumps(raw_detail)
        payload_hash = "f" * 64

        record = AuditEventRecord(
            id=test_event_id,
            ts=fixed_ts,
            profile_id=test_profile_id,
            actor_user_id=test_user_id,
            principal="agent",
            run_id="run-fidelity-456",
            event="tool",
            tool="attach-read",
            risk="clinical_assist",
            decision="allow",
            payload_hash=payload_hash,
            external_ref="ext-stream-789",
            detail_redacted=detail_json,
        )

        async with session_factory() as db:
            db.add(record)
            await db.commit()

        # 3. Retrieve and assert exact field values
        async with session_factory() as db:
            stmt = select(AuditEventRecord).where(AuditEventRecord.id == test_event_id)
            res = await db.execute(stmt)
            retrieved = res.scalar_one_or_none()

            assert retrieved is not None
            assert retrieved.id == test_event_id
            retrieved_ts_utc = retrieved.ts if retrieved.ts.tzinfo is not None else retrieved.ts.replace(tzinfo=timezone.utc)
            assert retrieved_ts_utc == fixed_ts
            assert retrieved.profile_id == test_profile_id
            assert retrieved.actor_user_id == test_user_id
            assert retrieved.principal == "agent"
            assert retrieved.run_id == "run-fidelity-456"
            assert retrieved.event == "tool"
            assert retrieved.tool == "attach-read"
            assert retrieved.risk == "clinical_assist"
            assert retrieved.decision == "allow"
            assert retrieved.payload_hash == payload_hash
            assert retrieved.external_ref == "ext-stream-789"
            assert retrieved.detail_redacted == detail_json

            # Verify JSON deserializability of detail_redacted
            parsed_meta = json.loads(retrieved.detail_redacted)
            assert parsed_meta["agent_id"] == "cardiology-guide"
            assert parsed_meta["duration_ms"] == 245

    @pytest.mark.asyncio
    async def test_minimal_and_null_optional_fields(self, adversarial_audit_env):
        """Verifies that records with NULL optional fields persist without constraint violations."""
        session_factory = adversarial_audit_env["session_factory"]
        event_id = str(uuid.uuid4())

        record = AuditEventRecord(
            id=event_id,
            principal="orchestrator",
            event="run",
            profile_id=None,
            actor_user_id=None,
            run_id=None,
            tool=None,
            risk=None,
            decision=None,
            payload_hash=None,
            external_ref=None,
            detail_redacted=None,
        )

        async with session_factory() as db:
            db.add(record)
            await db.commit()

        async with session_factory() as db:
            stmt = select(AuditEventRecord).where(AuditEventRecord.id == event_id)
            res = await db.execute(stmt)
            retrieved = res.scalar_one_or_none()

            assert retrieved is not None
            assert retrieved.id == event_id
            assert retrieved.principal == "orchestrator"
            assert retrieved.event == "run"
            assert retrieved.profile_id is None
            assert retrieved.actor_user_id is None
            assert retrieved.tool is None
            assert retrieved.risk is None
            assert retrieved.decision is None
            assert retrieved.payload_hash is None
            assert retrieved.external_ref is None
            assert retrieved.detail_redacted is None

    @pytest.mark.asyncio
    async def test_foreign_key_ondelete_set_null_retention(self, adversarial_audit_env):
        """Verifies audit trail retention: deleting Profile or User sets FK to NULL rather than deleting audit rows."""
        session_factory = adversarial_audit_env["session_factory"]

        user_id = str(uuid.uuid4())
        profile_id = str(uuid.uuid4())
        audit_id = str(uuid.uuid4())

        async with session_factory() as db:
            user = User(
                id=user_id,
                email="retention@carefold.test",
                username="retention_user",
                hashed_password="pw",
                role="member",
            )
            profile = Profile(
                id=profile_id,
                user_id=user_id,
                name="Retention Profile",
                relationship="self",
            )
            db.add_all([user, profile])
            await db.commit()

        # Record audit linked to both
        async with session_factory() as db:
            record = AuditEventRecord(
                id=audit_id,
                profile_id=profile_id,
                actor_user_id=user_id,
                principal="user",
                event="run",
            )
            db.add(record)
            await db.commit()

        # Delete Profile
        async with session_factory() as db:
            await db.execute(delete(Profile).where(Profile.id == profile_id))
            await db.commit()

        # Audit event must still exist with profile_id set to NULL
        async with session_factory() as db:
            stmt = select(AuditEventRecord).where(AuditEventRecord.id == audit_id)
            rec = (await db.execute(stmt)).scalar_one_or_none()
            assert rec is not None, "Audit event must NOT be deleted when Profile is deleted!"
            assert rec.profile_id is None, "profile_id must be SET NULL upon Profile deletion"
            assert rec.actor_user_id == user_id

        # Delete User
        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()

        # Audit event must still exist with actor_user_id set to NULL
        async with session_factory() as db:
            stmt = select(AuditEventRecord).where(AuditEventRecord.id == audit_id)
            rec = (await db.execute(stmt)).scalar_one_or_none()
            assert rec is not None, "Audit event must NOT be deleted when User is deleted!"
            assert rec.actor_user_id is None, "actor_user_id must be SET NULL upon User deletion"

    @pytest.mark.asyncio
    async def test_end_to_end_record_audit_persistence(self, adversarial_audit_env):
        """Verifies record_audit writes cleanly to database with all keyword parameters."""
        session_factory = adversarial_audit_env["session_factory"]

        # Prepopulate user to satisfy foreign key constraint on actor_user_id
        async with session_factory() as db:
            user = User(
                id="user-actor-101",
                email="actor101@carefold.test",
                username="actor101",
                hashed_password="pw",
                role="member",
            )
            db.add(user)
            await db.commit()

        test_payload = {"patient_query": "cardiac symptoms", "urgency": "low"}
        computed_hash = compute_payload_hash(test_payload)

        ev = AuditEvent(
            agent_id="pulmonology-guide",
            event="run",
            allowed=True,
            reason="Clear symptom inquiry",
            duration_ms=88,
        )

        recorded = await record_audit(
            ev,
            payload=test_payload,
            actor_user_id="user-actor-101",
            principal="orchestrator",
            risk="clinical_assist",
            decision="allow",
            external_ref="session-msg-555",
            run_id="run-graph-777",
            session_factory=session_factory,
        )

        assert recorded is not None
        assert recorded.agent_id == "pulmonology-guide"

        # Verify SQL row
        async with session_factory() as db:
            stmt = select(AuditEventRecord).where(AuditEventRecord.run_id == "run-graph-777")
            res = await db.execute(stmt)
            db_row = res.scalar_one_or_none()

            assert db_row is not None
            assert db_row.principal == "orchestrator"
            assert db_row.risk == "clinical_assist"
            assert db_row.decision == "allow"
            assert db_row.external_ref == "session-msg-555"
            assert db_row.payload_hash == computed_hash


# =============================================================================
# 3. NON-BLOCKING FAULT ISOLATION TESTS
# =============================================================================

class TestNonBlockingFaultIsolation:
    """Empirical adversarial tests for non-blocking fault isolation during audit writes."""

    @pytest.mark.asyncio
    async def test_database_disconnection_simulation_is_isolated(self):
        """Simulates an OperationalError database disconnection during audit write."""
        ev = AuditEvent(
            agent_id="cardiology-guide",
            event="tool",
            tool="attach-read",
            allowed=True,
        )

        class DisconnectedSessionFactory:
            def __call__(self):
                raise OperationalError("SELECT 1", {}, Exception("Database connection lost: server closed the connection unexpectedly"))

        # Must not raise any exception
        result = await record_audit(
            ev,
            session_factory=DisconnectedSessionFactory(),
        )
        assert result is not None
        assert result.agent_id == "cardiology-guide"

    @pytest.mark.asyncio
    async def test_session_factory_critical_io_error_is_isolated(self):
        """Simulates disk failure / pool exhaustion in session factory."""
        ev = AuditEvent(
            agent_id="neurology-guide",
            event="run",
            allowed=True,
        )

        class CrashingSessionFactory:
            def __call__(self):
                raise RuntimeError("Disk I/O error: no space left on device")

        result = await record_audit(
            ev,
            session_factory=CrashingSessionFactory(),
        )
        assert result is not None
        assert result.agent_id == "neurology-guide"

    @pytest.mark.asyncio
    async def test_in_flight_commit_failure_is_isolated(self):
        """Simulates an exception during session.commit() on an active DB session."""
        class MockFailingSession:
            def add(self, record):
                pass

            async def commit(self):
                raise SQLAlchemyError("Simulated write conflict / transaction deadlock on commit")

        ev = AuditEvent(
            agent_id="derma-guide",
            event="run",
            allowed=True,
        )

        result = await record_audit(
            ev,
            db=MockFailingSession(),
        )
        assert result is not None
        assert result.agent_id == "derma-guide"

    @pytest.mark.asyncio
    async def test_simultaneous_catastrophic_dual_sink_failure(self, tmp_path: Path):
        """Simulates catastrophic failure of BOTH the database AND the secondary JSONL file sink."""
        ev = AuditEvent(
            agent_id="emergency-guide",
            event="refuse",
            allowed=False,
            reason="Red flag detected",
        )

        class BrokenDB:
            def __call__(self):
                raise ConnectionRefusedError("Database unreachable")

        # Point log_path to a directory instead of a file (triggers IsADirectoryError / PermissionError)
        invalid_log_dir = tmp_path / "directory_not_a_file"
        invalid_log_dir.mkdir(parents=True, exist_ok=True)

        # Both sinks fail: primary application call must STILL not raise
        result = await record_audit(
            ev,
            log_path=invalid_log_dir,
            session_factory=BrokenDB(),
        )
        assert result is not None
        assert result.agent_id == "emergency-guide"
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_primary_clinical_agent_workflow_uninterrupted(self):
        """Simulates a clinical agent execution step that records audit while DB is dead."""
        async def mock_clinical_agent_step(query: str) -> Dict[str, Any]:
            # Simulate clinical prep action
            response_data = {"dossier": f"Visit checklist for: {query}", "status": "ready"}

            # Agent calls audit logger
            class BrokenDB:
                def __call__(self):
                    raise RuntimeError("Database connection pool drained")

            await record_audit(
                {"agent_id": "visit-steward", "event": "run", "allowed": True},
                payload={"query": query},
                session_factory=BrokenDB(),
            )

            # Returns clinical payload safely
            return response_data

        # Execution must succeed completely
        res = await mock_clinical_agent_step("Hypertension follow-up")
        assert res["status"] == "ready"
        assert "Hypertension" in res["dossier"]


# =============================================================================
# 4. SECONDARY JSONL SINK CONCURRENCY AND STRESS TESTS
# =============================================================================

class TestSecondaryJsonlSinkConcurrencyAndStress:
    """Empirical adversarial tests for secondary JSONL sink under high concurrency and load."""

    @pytest.mark.asyncio
    async def test_high_concurrency_async_writes(self, tmp_path: Path):
        """Stress-tests 50 concurrent async tasks writing 500 audit events to the same JSONL file."""
        log_file = tmp_path / "concurrent_stress.jsonl"
        num_tasks = 50
        events_per_task = 10
        total_events = num_tasks * events_per_task

        # Dummy session factory to avoid DB overhead during file sink stress test
        class DummySessionFactory:
            def __call__(self):
                class DummySession:
                    def add(self, r): pass
                    async def commit(self): pass
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return DummySession()

        async def worker(worker_id: int):
            for i in range(events_per_task):
                payload = {"worker": worker_id, "seq": i, "token": uuid.uuid4().hex}
                ev = AuditEvent(
                    agent_id=f"worker-{worker_id}",
                    event="tool",
                    tool="attach-read",
                    allowed=True,
                    reason=f"Event {i}",
                )
                await record_audit(
                    ev,
                    log_path=log_file,
                    payload=payload,
                    session_factory=DummySessionFactory(),
                )

        # Launch all 50 workers concurrently
        tasks = [asyncio.create_task(worker(w_id)) for w_id in range(num_tasks)]
        await asyncio.gather(*tasks)

        # Verify file integrity
        assert log_file.is_file(), "Log file must exist"
        raw_text = log_file.read_text(encoding="utf-8")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        assert len(lines) == total_events, (
            f"Expected exactly {total_events} lines, found {len(lines)}. Data loss or interleaving occurred!"
        )

        # Validate that EVERY line is valid JSON with no corruption or interleaving
        for idx, line in enumerate(lines):
            try:
                parsed = json.loads(line)
            except Exception as err:
                pytest.fail(f"Line {idx} corrupted during concurrent write: {line!r} (Error: {err})")

            assert "agent_id" in parsed
            assert "event" in parsed
            assert "payload_hash" in parsed
            assert len(parsed["payload_hash"]) == 64

    def test_multi_threaded_concurrency_across_os_threads(self, tmp_path: Path):
        """Stress-tests multiple OS threads concurrently writing to the JSONL sink."""
        log_file = tmp_path / "threaded_stress.jsonl"
        num_threads = 10
        writes_per_thread = 20
        total_writes = num_threads * writes_per_thread

        def thread_task(thread_id: int):
            # Run an isolated event loop per OS thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            class DummySessionFactory:
                def __call__(self):
                    class DummySession:
                        def add(self, r): pass
                        async def commit(self): pass
                        async def __aenter__(self): return self
                        async def __aexit__(self, *args): pass
                    return DummySession()

            async def run_writes():
                for seq in range(writes_per_thread):
                    await record_audit(
                        {
                            "agent_id": f"thread-{thread_id}",
                            "event": "run",
                            "allowed": True,
                        },
                        payload={"thread": thread_id, "seq": seq},
                        log_path=log_file,
                        session_factory=DummySessionFactory(),
                    )

            try:
                loop.run_until_complete(run_writes())
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(thread_task, t_id) for t_id in range(num_threads)]
            for fut in futures:
                fut.result()

        # Validate file integrity
        assert log_file.is_file()
        lines = [l.strip() for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == total_writes

        for line in lines:
            parsed = json.loads(line)
            assert parsed["agent_id"].startswith("thread-")
            assert len(parsed["payload_hash"]) == 64

    @pytest.mark.asyncio
    async def test_concurrent_readers_and_writers_no_corruption(self, tmp_path: Path):
        """Verifies concurrent reading while writing does not encounter file locks or JSON errors."""
        log_file = tmp_path / "contention_stress.jsonl"
        stop_event = asyncio.Event()

        class DummySessionFactory:
            def __call__(self):
                class DummySession:
                    def add(self, r): pass
                    async def commit(self): pass
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return DummySession()

        async def writer():
            for i in range(150):
                await record_audit(
                    {"agent_id": "contention-agent", "event": "tool", "tool": "test", "allowed": True},
                    payload={"counter": i},
                    log_path=log_file,
                    session_factory=DummySessionFactory(),
                )
                await asyncio.sleep(0.001)
            stop_event.set()

        read_errors: List[Exception] = []

        async def reader():
            while not stop_event.is_set():
                try:
                    total, events = await get_recent_audit_events(log_path=log_file, limit=20)
                    assert total >= 0
                    assert isinstance(events, list)

                    sync_events = read_recent_audit_events(limit=10, log_path=log_file)
                    assert isinstance(sync_events, list)
                except Exception as err:
                    read_errors.append(err)
                await asyncio.sleep(0.002)

        # Run writer and 3 readers simultaneously
        await asyncio.gather(writer(), reader(), reader(), reader())

        assert len(read_errors) == 0, f"Reader encountered exceptions during active writes: {read_errors}"
