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

"""SqliteMemoryAdapter Payload Fidelity and Factory Test Suite.

Adversarial stress-testing of SqliteMemoryAdapter and factory.py:
1. Payload type fidelity (JSON string vs dict, int vs str, bool vs str, float vs str, etc.)
2. reinforce() with non-finite floats (NaN, +Inf, -Inf -> ValueError) and boundary deltas
3. create_memory_port / create_catalog_port with whitespace ("  "), None, and unsupported backend strings
4. Delimiter isolation and disk persistence type preservation
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from carefold.config import Settings
from carefold.memory.adapters.sqlite.catalog_adapter import SqliteCatalogAdapter
from carefold.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from carefold.memory.factory import (
    create_catalog_port,
    create_memory_port,
    get_catalog_port,
    get_memory_port,
    reset_memory_ports,
)
from carefold.memory.ports.memory_port import MemoryPort, MemoryTier


# ==============================================================================
# 1. Payload Type Fidelity Challenge Suite
# ==============================================================================

class TestPayloadTypeFidelity:
    """Stress-test type preservation across remember(), recall(), and get()."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "memory_type_fidelity.db"
        ad = SqliteMemoryAdapter(db_path=db_file)
        yield ad
        await ad.close()

    @pytest.mark.asyncio
    async def test_string_containing_json_preserved_as_str(self, adapter: SqliteMemoryAdapter):
        """Store string containing JSON ('{"user": "alice"}'), verify recall returns str."""
        raw_json_str = '{"user": "alice"}'
        await adapter.remember("json_str_key", raw_json_str, MemoryTier.WORKING, namespace="fidelity_ns")

        # Verify via get()
        item = await adapter.get("json_str_key", namespace="fidelity_ns")
        assert item is not None
        assert isinstance(item["value"], str), f"Expected str, got {type(item['value']).__name__}"
        assert item["value"] == raw_json_str
        assert item["value"] != {"user": "alice"}

        # Verify via recall() with empty query
        recalled = await adapter.recall("", namespace="fidelity_ns")
        assert len(recalled) == 1
        assert isinstance(recalled[0]["value"], str), f"Expected str, got {type(recalled[0]['value']).__name__}"
        assert recalled[0]["value"] == raw_json_str

        # Verify via recall() with FTS query matching content
        fts_recalled = await adapter.recall("alice", namespace="fidelity_ns")
        assert len(fts_recalled) == 1
        assert isinstance(fts_recalled[0]["value"], str)
        assert fts_recalled[0]["value"] == raw_json_str

    @pytest.mark.asyncio
    async def test_dict_preserved_as_dict(self, adapter: SqliteMemoryAdapter):
        """Store dict ({"user": "alice"}), verify recall returns dict."""
        payload_dict = {"user": "alice"}
        await adapter.remember("dict_key", payload_dict, MemoryTier.WORKING, namespace="fidelity_ns")

        # Verify via get()
        item = await adapter.get("dict_key", namespace="fidelity_ns")
        assert item is not None
        assert isinstance(item["value"], dict), f"Expected dict, got {type(item['value']).__name__}"
        assert item["value"] == payload_dict
        assert item["value"]["user"] == "alice"

        # Verify via recall()
        recalled = await adapter.recall("", namespace="fidelity_ns")
        assert len(recalled) == 1
        assert isinstance(recalled[0]["value"], dict), f"Expected dict, got {type(recalled[0]['value']).__name__}"
        assert recalled[0]["value"] == payload_dict

        # Verify via recall() with FTS query
        fts_recalled = await adapter.recall("alice", namespace="fidelity_ns")
        assert len(fts_recalled) == 1
        assert isinstance(fts_recalled[0]["value"], dict)
        assert fts_recalled[0]["value"] == payload_dict

    @pytest.mark.asyncio
    async def test_int_vs_string_int_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store int (42) and string ("42"), verify strict type distinction."""
        await adapter.remember("int_key", 42, MemoryTier.SEMANTIC, namespace="fidelity_ns")
        await adapter.remember("str_int_key", "42", MemoryTier.SEMANTIC, namespace="fidelity_ns")

        # Check int_key
        item_int = await adapter.get("int_key", namespace="fidelity_ns")
        assert item_int is not None
        assert type(item_int["value"]) is int, f"Expected int, got {type(item_int['value']).__name__}"
        assert item_int["value"] == 42
        assert item_int["value"] is not "42"

        # Check str_int_key
        item_str = await adapter.get("str_int_key", namespace="fidelity_ns")
        assert item_str is not None
        assert type(item_str["value"]) is str, f"Expected str, got {type(item_str['value']).__name__}"
        assert item_str["value"] == "42"

        # Check recall
        recalled = await adapter.recall("", namespace="fidelity_ns", limit=10)
        by_key = {r["key"]: r["value"] for r in recalled}
        assert type(by_key["int_key"]) is int
        assert by_key["int_key"] == 42
        assert type(by_key["str_int_key"]) is str
        assert by_key["str_int_key"] == "42"

    @pytest.mark.asyncio
    async def test_bool_vs_string_bool_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store bool (True) and string ("True"), verify strict type distinction."""
        await adapter.remember("bool_key", True, MemoryTier.EPISODIC, namespace="fidelity_ns")
        await adapter.remember("str_bool_key", "True", MemoryTier.EPISODIC, namespace="fidelity_ns")
        await adapter.remember("bool_false_key", False, MemoryTier.EPISODIC, namespace="fidelity_ns")
        await adapter.remember("str_false_key", "false", MemoryTier.EPISODIC, namespace="fidelity_ns")

        # Check bool_key
        item_bool = await adapter.get("bool_key", namespace="fidelity_ns")
        assert item_bool is not None
        assert type(item_bool["value"]) is bool, f"Expected bool, got {type(item_bool['value']).__name__}"
        assert item_bool["value"] is True

        # Check str_bool_key
        item_str = await adapter.get("str_bool_key", namespace="fidelity_ns")
        assert item_str is not None
        assert type(item_str["value"]) is str, f"Expected str, got {type(item_str['value']).__name__}"
        assert item_str["value"] == "True"

        # Check bool_false_key
        item_false = await adapter.get("bool_false_key", namespace="fidelity_ns")
        assert item_false is not None
        assert type(item_false["value"]) is bool
        assert item_false["value"] is False

        # Check str_false_key
        item_str_false = await adapter.get("str_false_key", namespace="fidelity_ns")
        assert item_str_false is not None
        assert type(item_str_false["value"]) is str
        assert item_str_false["value"] == "false"

        # Check recall
        recalled = await adapter.recall("", namespace="fidelity_ns", limit=10)
        by_key = {r["key"]: r["value"] for r in recalled}
        assert type(by_key["bool_key"]) is bool and by_key["bool_key"] is True
        assert type(by_key["str_bool_key"]) is str and by_key["str_bool_key"] == "True"
        assert type(by_key["bool_false_key"]) is bool and by_key["bool_false_key"] is False
        assert type(by_key["str_false_key"]) is str and by_key["str_false_key"] == "false"

    @pytest.mark.asyncio
    async def test_float_vs_string_float_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store float (3.14159) and string ("3.14159"), verify strict type distinction."""
        await adapter.remember("float_key", 3.14159, MemoryTier.WORKING, namespace="fidelity_ns")
        await adapter.remember("str_float_key", "3.14159", MemoryTier.WORKING, namespace="fidelity_ns")

        item_float = await adapter.get("float_key", namespace="fidelity_ns")
        assert item_float is not None
        assert type(item_float["value"]) is float
        assert math.isclose(item_float["value"], 3.14159)

        item_str = await adapter.get("str_float_key", namespace="fidelity_ns")
        assert item_str is not None
        assert type(item_str["value"]) is str
        assert item_str["value"] == "3.14159"

    @pytest.mark.asyncio
    async def test_list_vs_string_list_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store list ([1, 2, "three"]) and string ('[1, 2, "three"]'), verify distinction."""
        lst = [1, 2, "three"]
        str_lst = '[1, 2, "three"]'
        await adapter.remember("list_key", lst, MemoryTier.PROCEDURAL, namespace="fidelity_ns")
        await adapter.remember("str_list_key", str_lst, MemoryTier.PROCEDURAL, namespace="fidelity_ns")

        item_list = await adapter.get("list_key", namespace="fidelity_ns")
        assert item_list is not None
        assert isinstance(item_list["value"], list)
        assert item_list["value"] == lst

        item_str = await adapter.get("str_list_key", namespace="fidelity_ns")
        assert item_str is not None
        assert isinstance(item_str["value"], str)
        assert item_str["value"] == str_lst

    @pytest.mark.asyncio
    async def test_none_vs_string_none_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store None, 'null', and 'None', verify distinction."""
        await adapter.remember("none_key", None, MemoryTier.WORKING, namespace="fidelity_ns")
        await adapter.remember("str_null_key", "null", MemoryTier.WORKING, namespace="fidelity_ns")
        await adapter.remember("str_none_key", "None", MemoryTier.WORKING, namespace="fidelity_ns")

        item_none = await adapter.get("none_key", namespace="fidelity_ns")
        assert item_none is not None
        assert item_none["value"] is None

        item_null = await adapter.get("str_null_key", namespace="fidelity_ns")
        assert item_null is not None
        assert type(item_null["value"]) is str
        assert item_null["value"] == "null"

        item_str_none = await adapter.get("str_none_key", namespace="fidelity_ns")
        assert item_str_none is not None
        assert type(item_str_none["value"]) is str
        assert item_str_none["value"] == "None"


# ==============================================================================
# 2. reinforce() Float & Boundary Handling Challenge Suite
# ==============================================================================

class TestReinforceAdversarial:
    """Stress-test reinforce() validation of floats and boundary deltas."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "reinforce_test.db"
        ad = SqliteMemoryAdapter(db_path=db_file)
        await ad.remember("test_mem", "baseline_value", MemoryTier.EPISODIC, namespace="reinforce_ns")
        yield ad
        await ad.close()

    @pytest.mark.asyncio
    async def test_reinforce_nan_raises_value_error(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with NaN: must raise ValueError."""
        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=float("nan"))

        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=math.nan)

    @pytest.mark.asyncio
    async def test_reinforce_positive_inf_raises_value_error(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with +Inf: must raise ValueError."""
        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=float("inf"))

        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=math.inf)

    @pytest.mark.asyncio
    async def test_reinforce_negative_inf_raises_value_error(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with -Inf: must raise ValueError."""
        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=float("-inf"))

        with pytest.raises(ValueError, match="delta must be a finite float"):
            await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=-math.inf)

    @pytest.mark.asyncio
    async def test_reinforce_zero_delta(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with zero delta (0.0): salience unchanged, access_count incremented."""
        item_before = await adapter.get("test_mem", namespace="reinforce_ns")
        assert item_before is not None
        initial_salience = item_before["salience"]
        initial_count = item_before["access_count"]

        await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=0.0)

        item_after = await adapter.get("test_mem", namespace="reinforce_ns")
        assert item_after is not None
        assert math.isclose(item_after["salience"], initial_salience)
        assert item_after["access_count"] == initial_count + 1
        assert item_after["last_accessed_at"] is not None

    @pytest.mark.asyncio
    async def test_reinforce_negative_delta_within_bounds(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with negative delta that decays salience but remains > 0."""
        # Initial salience is 1.0. Delta = -0.4 -> new salience should be 0.6.
        await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=-0.4)

        item = await adapter.get("test_mem", namespace="reinforce_ns")
        assert item is not None
        assert math.isclose(item["salience"], 0.6, abs_tol=1e-5)
        assert item["access_count"] == 1

    @pytest.mark.asyncio
    async def test_reinforce_negative_delta_clamped_at_zero(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with large negative delta: must clamp strictly at 0.0."""
        await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=-100.0)

        item = await adapter.get("test_mem", namespace="reinforce_ns")
        assert item is not None
        assert item["salience"] == 0.0

    @pytest.mark.asyncio
    async def test_reinforce_large_positive_delta(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with large positive delta: salience increases cleanly without overflow."""
        await adapter.reinforce("test_mem", namespace="reinforce_ns", delta=1_000_000.0)

        item = await adapter.get("test_mem", namespace="reinforce_ns")
        assert item is not None
        assert math.isclose(item["salience"], 1_000_001.0, abs_tol=1e-3)
        assert item["access_count"] == 1

    @pytest.mark.asyncio
    async def test_reinforce_non_existent_key_graceful(self, adapter: SqliteMemoryAdapter):
        """Challenge reinforce() with non-existent key: does not crash or raise error."""
        await adapter.reinforce("does_not_exist", namespace="reinforce_ns", delta=0.5)
        item = await adapter.get("does_not_exist", namespace="reinforce_ns")
        assert item is None


# ==============================================================================
# 3. Factory Backend String Validation Challenge Suite
# ==============================================================================

class TestFactoryValidationAdversarial:
    """Stress-test create_memory_port and create_catalog_port validation."""

    def test_create_memory_port_whitespace_strings_raise_value_error(self):
        """Challenge create_memory_port with whitespace strings: must raise ValueError."""
        whitespace_cases = ["  ", " ", "\t", "\n", " \t \n "]
        for ws in whitespace_cases:
            with pytest.raises(ValueError, match="Unsupported memory backend"):
                create_memory_port(backend=ws)

    def test_create_catalog_port_whitespace_strings_raise_value_error(self):
        """Challenge create_catalog_port with whitespace strings: must raise ValueError."""
        whitespace_cases = ["  ", " ", "\t", "\n", " \t \n "]
        for ws in whitespace_cases:
            with pytest.raises(ValueError, match="Unsupported catalog backend"):
                create_catalog_port(backend=ws)

    def test_create_memory_port_empty_string_raises_value_error(self):
        """Challenge create_memory_port with empty string "": must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported memory backend"):
            create_memory_port(backend="")

    def test_create_catalog_port_empty_string_raises_value_error(self):
        """Challenge create_catalog_port with empty string "": must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported catalog backend"):
            create_catalog_port(backend="")

    def test_create_memory_port_none_returns_sqlite_default(self):
        """Challenge create_memory_port with backend=None: returns SqliteMemoryAdapter."""
        port = create_memory_port(backend=None)
        assert isinstance(port, SqliteMemoryAdapter)

    def test_create_catalog_port_none_returns_sqlite_default(self):
        """Challenge create_catalog_port with backend=None: returns SqliteCatalogAdapter."""
        port = create_catalog_port(backend=None)
        assert isinstance(port, SqliteCatalogAdapter)

    def test_create_memory_port_unsupported_strings_raise_value_error(self):
        """Challenge create_memory_port with unsupported backend names."""
        unsupported = ["redis", "mongo", "dynamodb", "unsupported_xyz", "sqlite_fts5"]
        for backend_name in unsupported:
            with pytest.raises(ValueError, match="Unsupported memory backend"):
                create_memory_port(backend=backend_name)

    def test_create_catalog_port_unsupported_strings_raise_value_error(self):
        """Challenge create_catalog_port with unsupported backend names."""
        unsupported = ["redis", "mongo", "dynamodb", "unsupported_xyz", "sqlite_fts5"]
        for backend_name in unsupported:
            with pytest.raises(ValueError, match="Unsupported catalog backend"):
                create_catalog_port(backend=backend_name)

    def test_create_memory_port_spector_and_postgres_not_implemented(self):
        """Challenge spector and postgres backends: spector succeeds, postgres raises NotImplementedError."""
        port = create_memory_port(backend="spector")
        assert isinstance(port, MemoryPort)
        assert hasattr(port, "store")
        assert port.store is not None

        with pytest.raises(NotImplementedError, match="Backend 'postgres' is not yet implemented"):
            create_memory_port(backend="postgres")

    def test_create_catalog_port_spector_and_postgres_not_implemented(self):
        """Challenge spector and postgres backends: must raise NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Backend 'spector' is not yet implemented"):
            create_catalog_port(backend="spector")

        with pytest.raises(NotImplementedError, match="Backend 'postgres' is not yet implemented"):
            create_catalog_port(backend="postgres")

    def test_settings_with_whitespace_backend_raises_value_error(self):
        """Challenge factory when Settings itself contains whitespace memory_backend."""
        settings = Settings(memory_backend="   ")
        with pytest.raises(ValueError, match="Unsupported memory backend"):
            create_memory_port(settings=settings)

        with pytest.raises(ValueError, match="Unsupported catalog backend"):
            create_catalog_port(settings=settings)

    def test_case_insensitivity_and_padding_for_valid_backends(self):
        """Verify that valid backends with case variations or surrounding whitespace succeed."""
        port_mem = create_memory_port(backend="  SQLITE  ")
        assert isinstance(port_mem, SqliteMemoryAdapter)

        port_cat = create_catalog_port(backend="  SqLiTe  ")
        assert isinstance(port_cat, SqliteCatalogAdapter)


# ==============================================================================
# 4. Multi-Tenant Delimiter Safety & Disk Persistence Suite
# ==============================================================================

class TestNamespaceIsolationAndPersistence:
    """Stress-test namespace delimiter isolation and SQLite disk persistence."""

    @pytest.mark.asyncio
    async def test_namespace_colon_collision_prevention(self, tmp_path: Path):
        """Verify namespace colon collision: 'user:1'/'rec' cannot collide with 'user'/'1:rec'."""
        db_file = tmp_path / "ns_isolation.db"
        adapter = SqliteMemoryAdapter(db_path=db_file)

        # Store payload in namespace 'user:1', key 'rec'
        payload_1 = {"tenant": "tenant_1", "role": "admin"}
        await adapter.remember("rec", payload_1, MemoryTier.WORKING, namespace="user:1")

        # Store payload in namespace 'user', key '1:rec'
        payload_2 = {"tenant": "tenant_2", "role": "guest"}
        await adapter.remember("1:rec", payload_2, MemoryTier.WORKING, namespace="user")

        # Verify tenant 1 receives its untouched payload
        item_1 = await adapter.get("rec", namespace="user:1")
        assert item_1 is not None
        assert item_1["value"] == payload_1
        assert item_1["namespace"] == "user:1"

        # Verify tenant 2 receives its untouched payload
        item_2 = await adapter.get("1:rec", namespace="user")
        assert item_2 is not None
        assert item_2["value"] == payload_2
        assert item_2["namespace"] == "user"

        # Verify recall for tenant 1 does not leak tenant 2
        recalled_1 = await adapter.recall("", namespace="user:1")
        assert len(recalled_1) == 1
        assert recalled_1[0]["value"] == payload_1

        # Forget tenant 2's key, ensure tenant 1's key remains
        deleted = await adapter.forget("1:rec", namespace="user")
        assert deleted is True

        item_1_after = await adapter.get("rec", namespace="user:1")
        assert item_1_after is not None
        assert item_1_after["value"] == payload_1

        await adapter.close()

    @pytest.mark.asyncio
    async def test_persistence_across_adapter_reinstantiation(self, tmp_path: Path):
        """Verify all types survive across independent adapter instances reading same SQLite file."""
        db_file = tmp_path / "persistent_fidelity.db"

        # Adapter 1: Store multiple types
        ad1 = SqliteMemoryAdapter(db_path=db_file)
        await ad1.remember("str_json", '{"key": "val"}', MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.remember("actual_dict", {"key": "val"}, MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.remember("int_val", 999, MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.remember("str_int", "999", MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.remember("bool_val", True, MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.remember("str_bool", "True", MemoryTier.SEMANTIC, namespace="persisted")
        await ad1.close()

        # Adapter 2: Open and read back
        ad2 = SqliteMemoryAdapter(db_path=db_file)

        item_str_json = await ad2.get("str_json", namespace="persisted")
        assert type(item_str_json["value"]) is str
        assert item_str_json["value"] == '{"key": "val"}'

        item_dict = await ad2.get("actual_dict", namespace="persisted")
        assert type(item_dict["value"]) is dict
        assert item_dict["value"] == {"key": "val"}

        item_int = await ad2.get("int_val", namespace="persisted")
        assert type(item_int["value"]) is int
        assert item_int["value"] == 999

        item_str_int = await ad2.get("str_int", namespace="persisted")
        assert type(item_str_int["value"]) is str
        assert item_str_int["value"] == "999"

        item_bool = await ad2.get("bool_val", namespace="persisted")
        assert type(item_bool["value"]) is bool
        assert item_bool["value"] is True

        item_str_bool = await ad2.get("str_bool", namespace="persisted")
        assert type(item_str_bool["value"]) is str
        assert item_str_bool["value"] == "True"

        await ad2.close()


# ==============================================================================
# 5. Advanced Adversarial Injection, Concurrency & Unicode Stress Suite
# ==============================================================================

class TestAdvancedAdversarialEdgeCases:
    """Stress-test SQL/FTS injection resilience, empty strings, sequential salience, and concurrency."""

    @pytest.fixture
    async def adapter(self, tmp_path: Path):
        db_file = tmp_path / "advanced_adversarial.db"
        ad = SqliteMemoryAdapter(db_path=db_file)
        yield ad
        await ad.close()

    @pytest.mark.asyncio
    async def test_empty_string_value_fidelity(self, adapter: SqliteMemoryAdapter):
        """Store empty string '', verify get and recall preserve empty str (not None)."""
        await adapter.remember("empty_key", "", MemoryTier.WORKING, namespace="empty_ns")

        item = await adapter.get("empty_key", namespace="empty_ns")
        assert item is not None
        assert type(item["value"]) is str
        assert item["value"] == ""

        recalled = await adapter.recall("", namespace="empty_ns")
        assert len(recalled) == 1
        assert type(recalled[0]["value"]) is str
        assert recalled[0]["value"] == ""

    @pytest.mark.asyncio
    async def test_sql_injection_in_namespace_and_key(self, adapter: SqliteMemoryAdapter):
        """Challenge SQL injection payloads in namespace and key parameters."""
        malicious_ns = "ns'; DROP TABLE memories; --"
        malicious_key = "key'; DELETE FROM memories WHERE '1'='1'; --"
        payload = {"safe": True, "notes": "' OR '1'='1"}

        await adapter.remember(malicious_key, payload, MemoryTier.SEMANTIC, namespace=malicious_ns)

        # Retrieve should succeed safely via parameterization
        item = await adapter.get(malicious_key, namespace=malicious_ns)
        assert item is not None
        assert item["value"] == payload
        assert item["namespace"] == malicious_ns
        assert item["key"] == malicious_key

        # Table must still exist and be intact
        all_items = await adapter.recall("", namespace=malicious_ns)
        assert len(all_items) == 1

        # Delete using malicious key
        deleted = await adapter.forget(malicious_key, namespace=malicious_ns)
        assert deleted is True

        item_after = await adapter.get(malicious_key, namespace=malicious_ns)
        assert item_after is None

    @pytest.mark.asyncio
    async def test_fts_query_syntax_no_crash(self, adapter: SqliteMemoryAdapter):
        """Challenge FTS5 parser with malformed, unbalanced, and syntax-breaking queries."""
        await adapter.remember("doc1", "clinical cardiology examination", MemoryTier.SEMANTIC, namespace="fts_ns")

        adversarial_queries = [
            '""',
            '"""',
            '*',
            '***',
            'AND NOT OR',
            'NEAR/3',
            '(((( unclosed parens',
            '-- comment injection',
            "'; DROP TABLE memories_fts; --",
            '^ $ % @ ! #',
            'MATCH "nested" quote',
        ]

        for query in adversarial_queries:
            # Must never raise sqlite3.OperationalError or crash
            results = await adapter.recall(query, namespace="fts_ns")
            assert isinstance(results, list)

        # Sanity check: valid query matches
        valid_results = await adapter.recall("cardiology", namespace="fts_ns")
        assert len(valid_results) == 1
        assert valid_results[0]["key"] == "doc1"

    @pytest.mark.asyncio
    async def test_sequential_salience_transitions(self, adapter: SqliteMemoryAdapter):
        """Verify sequential reinforce calls track salience and access_count precisely."""
        await adapter.remember("seq_mem", "seq_val", MemoryTier.EPISODIC, namespace="seq_ns")

        # Initial: salience = 1.0, access_count = 0
        m0 = await adapter.get("seq_mem", namespace="seq_ns")
        assert m0["salience"] == 1.0
        assert m0["access_count"] == 0

        # +0.5 -> 1.5, access_count = 1
        await adapter.reinforce("seq_mem", namespace="seq_ns", delta=0.5)
        m1 = await adapter.get("seq_mem", namespace="seq_ns")
        assert math.isclose(m1["salience"], 1.5)
        assert m1["access_count"] == 1

        # -2.0 -> clamped at 0.0, access_count = 2
        await adapter.reinforce("seq_mem", namespace="seq_ns", delta=-2.0)
        m2 = await adapter.get("seq_mem", namespace="seq_ns")
        assert m2["salience"] == 0.0
        assert m2["access_count"] == 2

        # +0.25 -> 0.25, access_count = 3
        await adapter.reinforce("seq_mem", namespace="seq_ns", delta=0.25)
        m3 = await adapter.get("seq_mem", namespace="seq_ns")
        assert math.isclose(m3["salience"], 0.25)
        assert m3["access_count"] == 3

    @pytest.mark.asyncio
    async def test_multilingual_unicode_fidelity(self, adapter: SqliteMemoryAdapter):
        """Verify complex unicode, emojis, CJK, and RTL strings retain exact fidelity."""
        ns = "🩺_clinique_🏥"
        key = "patient_佐藤_123"
        payload = {
            "diagnostic": "Hypertension 高血圧",
            "notes": "مرحبا بالعالم - سلام",
            "emoji_list": ["💉", "💊", "🧬"],
            "math_symbols": "∑ ∫ √ π ≠ ∞",
        }

        await adapter.remember(key, payload, MemoryTier.SEMANTIC, namespace=ns)

        item = await adapter.get(key, namespace=ns)
        assert item is not None
        assert item["value"] == payload
        assert item["value"]["diagnostic"] == "Hypertension 高血圧"
        assert item["value"]["notes"] == "مرحبا بالعالم - سلام"

    @pytest.mark.asyncio
    async def test_concurrent_asyncio_workload(self, adapter: SqliteMemoryAdapter):
        """Verify 50 concurrent writes and reads succeed without lock contention or corruption."""
        import asyncio

        num_tasks = 50

        async def worker(i: int):
            k = f"conc_key_{i}"
            val = {"task_id": i, "data": f"content_{i}"}
            await adapter.remember(k, val, MemoryTier.WORKING, namespace="conc_ns")
            item = await adapter.get(k, namespace="conc_ns")
            assert item is not None
            assert item["value"] == val
            await adapter.reinforce(k, namespace="conc_ns", delta=0.1)

        tasks = [worker(i) for i in range(num_tasks)]
        await asyncio.gather(*tasks)

        all_items = await adapter.recall("", namespace="conc_ns", limit=100)
        assert len(all_items) == num_tasks

