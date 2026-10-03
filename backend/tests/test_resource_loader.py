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

"""Resource Loader and Constants Concurrency & Stress Test Suite.

Adversarially stress-tests:
1. Concurrency: race conditions in get_resource_loader() cold-start, multi-threaded
   load_yaml, regex compilation stampede, and cache clearing.
2. Corrupted and missing resources: missing files, missing directories, invalid YAML syntax,
   empty files, non-dict payloads, malformed regex patterns, missing format keys, and path traversal.
3. Constants boundary values & immutability: defaults.py, paths.py, api.py, models.py.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Dict, List
import pytest
import yaml

import carefold.constants.api as api_const
import carefold.constants.defaults as def_const
import carefold.constants.models as mod_const
import carefold.constants.paths as paths_const
from carefold.resources.loader import (
    ResourceLoader,
    _LOADER_INSTANCE,
    get_resource_loader,
)


# ============================================================================
# Domain 1: Concurrency & Thread-Safety Stress Tests
# ============================================================================

class TestConcurrencyResourceLoader:
    """Stress tests concurrent access, thread safety, and race conditions."""

    def test_concurrent_get_resource_loader_singleton_race(self):
        """EMPIRICAL CHALLENGE: Verify if get_resource_loader() is thread-safe on cold start.
        
        When 50 threads concurrently invoke get_resource_loader() without a lock,
        does it return a single unique singleton instance or multiple divergent instances?
        """
        import carefold.resources.loader as loader_mod

        num_threads = 50
        barrier = threading.Barrier(num_threads)
        instances: List[int] = []
        errors: List[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=5.0)
                inst = loader_mod.get_resource_loader()
                instances.append(id(inst))
            except Exception as e:
                errors.append(e)

        # Reset singleton to simulate cold start
        loader_mod._LOADER_INSTANCE = None

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread execution errors: {errors}"
        assert len(instances) == num_threads

        unique_instances = set(instances)
        assert len(unique_instances) == 1, (
            f"Cold-start singleton violation: spawned {len(unique_instances)} instances across {num_threads} threads"
        )

    def test_concurrent_load_yaml_multi_thread_safety(self):
        """Verify that concurrent calls to load_yaml on a shared loader succeed without crash."""
        loader = ResourceLoader()
        num_threads = 30
        barrier = threading.Barrier(num_threads)
        results: List[Dict[str, Any]] = []
        errors: List[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=5.0)
                data = loader.load_yaml("disclaimers.yaml")
                results.append(data)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent load_yaml failed with errors: {errors}"
        assert len(results) == num_threads
        for res in results:
            assert "intended_use" in res
            assert res == results[0]

    def test_concurrent_regex_compilation_stampede(self):
        """Verify concurrent calls to get_compiled_refusal_patterns do not crash or corrupt state."""
        loader = ResourceLoader()
        num_threads = 30
        barrier = threading.Barrier(num_threads)
        patterns_list: List[Any] = []
        errors: List[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=5.0)
                p = loader.get_compiled_refusal_patterns()
                patterns_list.append(p)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent pattern compilation failed: {errors}"
        assert len(patterns_list) == num_threads
        for p in patterns_list:
            assert len(p) == 34
            assert all(hasattr(item, "regex") for item in p)

    def test_concurrent_cache_invalidation_stability(self):
        """Stress test concurrent cache readers and clear_cache() invalidations."""
        loader = ResourceLoader()
        stop = False
        errors: List[str] = []

        def reader_disclaimers():
            while not stop:
                try:
                    d = loader.get_disclaimers()
                    assert "intended_use" in d
                except Exception as e:
                    errors.append(f"reader_disclaimers: {type(e).__name__}: {e}")

        def reader_patterns():
            while not stop:
                try:
                    p = loader.get_compiled_refusal_patterns()
                    assert len(p) > 0
                except Exception as e:
                    errors.append(f"reader_patterns: {type(e).__name__}: {e}")

        def invalidator():
            import time
            while not stop:
                try:
                    loader.clear_cache()
                    time.sleep(0.002)
                except Exception as e:
                    errors.append(f"invalidator: {type(e).__name__}: {e}")

        threads = [
            threading.Thread(target=reader_disclaimers),
            threading.Thread(target=reader_disclaimers),
            threading.Thread(target=reader_patterns),
            threading.Thread(target=invalidator),
        ]

        for t in threads:
            t.start()

        import time
        time.sleep(0.3)
        stop = True

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent invalidation: {errors[:5]}"


# ============================================================================
# Domain 2: Corrupted, Malformed, and Missing Resource Handling
# ============================================================================

class TestCorruptedAndMissingResources:
    """Stress tests handling of corrupted files, missing resources, and malformed syntax."""

    def test_missing_resource_file_raises_filenotfound(self):
        loader = ResourceLoader()
        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load_yaml("nonexistent_clinical_resource.yaml")
        assert "not found" in str(exc_info.value).lower()

    def test_missing_resources_directory_raises_filenotfound(self):
        nonexistent_dir = Path("/tmp/nonexistent_dir_carefold_987654")
        loader = ResourceLoader(resources_dir=nonexistent_dir)
        with pytest.raises(FileNotFoundError):
            loader.get_disclaimers()

    def test_corrupted_yaml_syntax_raises_yamlerror(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            bad_yaml = tmp_path / "bad_syntax.yaml"
            bad_yaml.write_text("key: [unclosed_list\n  bad_indent:\n\t- tab_char", encoding="utf-8")

            loader = ResourceLoader(resources_dir=tmp_path)
            with pytest.raises(yaml.YAMLError):
                loader.load_yaml("bad_syntax.yaml")

    def test_empty_yaml_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            empty_file = tmp_path / "empty.yaml"
            empty_file.write_text("", encoding="utf-8")

            loader = ResourceLoader(resources_dir=tmp_path)
            data = loader.load_yaml("empty.yaml")
            assert data == {}

    def test_non_dict_yaml_content_handling(self):
        """When YAML parses to a list or scalar, load_yaml returns it."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            list_yaml = tmp_path / "list.yaml"
            list_yaml.write_text("- item1\n- item2\n", encoding="utf-8")

            loader = ResourceLoader(resources_dir=tmp_path)
            data = loader.load_yaml("list.yaml")
            assert isinstance(data, list)
            assert data == ["item1", "item2"]

    def test_corrupted_regex_in_refusal_patterns_raises_re_error(self):
        """If a pattern in refusal_patterns.yaml has invalid regex syntax, re.error is raised."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            corrupt_patterns = tmp_path / "refusal_patterns.yaml"
            corrupt_patterns.write_text(
                yaml.dump({
                    "building_blocks": {},
                    "refusal_patterns": [
                        {
                            "category": "Test",
                            "pattern": "(unclosed_parenthesis_syntax[a-z",
                            "description": "Corrupt regex test"
                        }
                    ]
                }),
                encoding="utf-8"
            )

            loader = ResourceLoader(resources_dir=tmp_path)
            with pytest.raises(re.error):
                loader.get_compiled_refusal_patterns()

    def test_unresolved_building_block_tag_preserved(self):
        """When a pattern contains <UNKNOWN_TAG>, tag is left literally without crash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            patterns_file = tmp_path / "refusal_patterns.yaml"
            patterns_file.write_text(
                yaml.dump({
                    "building_blocks": {},
                    "refusal_patterns": [
                        {
                            "category": "Test",
                            "pattern": "foo <UNKNOWN_TAG> bar",
                            "description": "Unknown tag test"
                        }
                    ]
                }),
                encoding="utf-8"
            )

            loader = ResourceLoader(resources_dir=tmp_path)
            compiled = loader.get_compiled_refusal_patterns()
            assert len(compiled) == 1
            assert compiled[0].regex.pattern == "foo <UNKNOWN_TAG> bar"

    def test_missing_keys_in_prompts_yaml_fallbacks(self):
        """Verify behavior when prompts.yaml is empty or missing expected sections."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            prompts_file = tmp_path / "prompts.yaml"
            prompts_file.write_text("{}", encoding="utf-8")

            loader = ResourceLoader(resources_dir=tmp_path)
            assert loader.get_safety_preamble_template() == ""
            # For unknown agents, global default chips are returned
            unknown_chips = loader.get_follow_up_suggestions("unknown-agent")
            assert len(unknown_chips) == 3

            # For known agent personas (e.g. visit-steward), when prompts.yaml is empty,
            # it falls back to global default chips as well
            bundled_chips = loader.get_follow_up_suggestions("visit-steward")
            assert len(bundled_chips) == 3
            assert bundled_chips == unknown_chips

    def test_errors_yaml_missing_key_status_code_fallback(self):
        """When an unknown error key is queried, status code defaults to 500."""
        loader = ResourceLoader()
        code = loader.get_error_status_code("completely_nonexistent_error_key_12345")
        assert code == 500

    def test_errors_yaml_format_error_missing_placeholder_safe(self):
        """Verify format_error does not crash if required template placeholders are omitted."""
        loader = ResourceLoader()
        # 'invalid_input' message template is: "Invalid request parameter: {detail}"
        # Omitting 'detail' kwarg safely falls back without raising KeyError
        formatted = loader.format_error("invalid_input")
        assert "Invalid request parameter:" in formatted
        # Partially provided kwargs
        formatted_partial = loader.format_error("missing_api_key", provider="openai")
        assert "openai" in formatted_partial

    def test_load_yaml_path_traversal_blocked(self):
        """Verify load_yaml prevents path traversal outside resources_dir."""
        loader = ResourceLoader()
        with pytest.raises(PermissionError):
            loader.load_yaml("../config.py")
        with pytest.raises(PermissionError):
            loader.load_yaml("/etc/hosts")


# ============================================================================
# Domain 3: Boundary Values & Immutability in Constants
# ============================================================================

class TestBoundaryValuesConstants:
    """Stress tests boundary values, types, and invariants in carefold.constants."""

    def test_defaults_numerical_boundaries(self):
        # File size: exactly 10MB
        assert def_const.MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024
        assert def_const.MAX_FILE_SIZE_BYTES == 10485760
        assert def_const.MAX_ATTACHMENT_SIZE == def_const.MAX_FILE_SIZE_BYTES

        # Retries: must be positive integer <= 10
        assert 1 <= def_const.DEFAULT_MAX_RETRIES <= 10
        assert def_const.DEFAULT_MAX_RETRIES == def_const.MAX_REFLECTION_RETRIES

        # Pagination & Audit boundaries: MIN <= DEFAULT <= MAX
        assert def_const.MIN_AUDIT_LIMIT == 1
        assert def_const.MAX_AUDIT_LIMIT == 1000
        assert def_const.MIN_AUDIT_LIMIT <= def_const.DEFAULT_PAGE_SIZE <= def_const.MAX_AUDIT_LIMIT
        assert def_const.MIN_AUDIT_LIMIT <= def_const.DEFAULT_AUDIT_LIMIT <= def_const.MAX_AUDIT_LIMIT

        # Tool output limits: positive integer >= 1000
        assert def_const.MAX_TOOL_OUTPUT_CHARS == 100_000
        assert def_const.MAX_NOTE_SLUG_LENGTH == 80

        # SQLite bounds: positive values
        assert def_const.SQLITE_BUSY_TIMEOUT_MS == 10000
        assert def_const.SQLITE_CONNECT_TIMEOUT_SECONDS == 30.0

        # Network port: valid port range (1 - 65535)
        assert 1 <= def_const.DEFAULT_PORT <= 65535
        assert def_const.DEFAULT_PORT == 8000

    def test_defaults_immutability(self):
        """Verify that collections in defaults are immutable frozensets/tuples."""
        assert isinstance(def_const.ALLOWED_TEXT_EXTENSIONS, frozenset)
        assert isinstance(def_const.ALLOWED_ATTACHMENT_EXTENSIONS, frozenset)
        assert isinstance(def_const.ALLOWED_SKILL_DOC_EXTENSIONS, frozenset)
        assert isinstance(def_const.BUNDLED_AGENT_IDS, frozenset)
        assert isinstance(def_const.BUNDLED_SKILL_IDS, frozenset)
        assert isinstance(def_const.PHASE_0_TOOLS, frozenset)
        assert isinstance(def_const.DEFAULT_FORBIDDEN_INTENTS, tuple)
        assert isinstance(def_const.DEFAULT_CORS_ORIGINS, tuple)

        # Confirm mutation attempts raise AttributeError
        with pytest.raises(AttributeError):
            def_const.ALLOWED_TEXT_EXTENSIONS.add(".exe")  # type: ignore

    def test_defaults_extension_subsets_and_formatting(self):
        # Every text extension must be allowed in attachments
        assert def_const.ALLOWED_TEXT_EXTENSIONS.issubset(def_const.ALLOWED_ATTACHMENT_EXTENSIONS)
        # PDF is in attachments but not text
        assert ".pdf" in def_const.ALLOWED_ATTACHMENT_EXTENSIONS
        assert ".pdf" not in def_const.ALLOWED_TEXT_EXTENSIONS

        # All extensions must start with dot and be lowercase
        for ext in def_const.ALLOWED_ATTACHMENT_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()

    def test_paths_constants_invariants(self):
        # All path constants must be non-empty strings with no leading/trailing whitespace
        all_paths = [
            paths_const.DEFAULT_WORKSPACE_ROOT,
            paths_const.WORKSPACE_DIR,
            paths_const.AGENTS_DIR,
            paths_const.SKILLS_DIR,
            paths_const.ATTACHMENTS_DIR,
            paths_const.NOTES_DIR,
            paths_const.LOGS_DIR,
            paths_const.CHATS_DIR,
            paths_const.RESOURCES_DIR,
            paths_const.REFERENCES_DIR,
            paths_const.AUDIT_LOG_FILENAME,
            paths_const.SQLITE_DB_FILENAME,
            paths_const.AGENT_MANIFEST_FILENAME,
            paths_const.SKILL_MANIFEST_FILENAME,
            paths_const.CAREFOLD_YAML_FILENAME,
            paths_const.DISCLAIMERS_YAML,
            paths_const.REFUSAL_PATTERNS_YAML,
            paths_const.PROMPTS_YAML,
            paths_const.ERRORS_YAML,
        ]
        for p in all_paths:
            assert isinstance(p, str) and len(p) > 0
            assert p == p.strip()

        # Environment variable names must be valid uppercase identifiers
        env_vars = [
            paths_const.ENV_WORKSPACE_ROOT,
            paths_const.ENV_DB_PATH,
            paths_const.ENV_AUDIT_LOG_PATH,
        ]
        for ev in env_vars:
            assert ev.isupper()
            assert ev.isidentifier()

    def test_api_constants_invariants(self):
        # API endpoints must start with /api
        assert api_const.API_PREFIX == "/api"
        assert api_const.API_HEALTH == "/api/health"
        assert api_const.API_CHAT == "/api/chat"
        assert api_const.API_AGENTS == "/api/agents"
        assert api_const.API_SKILLS == "/api/skills"
        assert api_const.API_AUDIT == "/api/audit"

        # HTTP status codes must be standard integers
        assert api_const.HTTP_OK == 200
        assert api_const.HTTP_BAD_REQUEST == 400
        assert api_const.HTTP_FORBIDDEN == 403
        assert api_const.HTTP_NOT_FOUND == 404
        assert api_const.HTTP_INTERNAL_SERVER_ERROR == 500

        # SSE event names must be valid alphanumeric/underscore strings
        for event in (
            api_const.SSE_EVENT_MESSAGE,
            api_const.SSE_EVENT_TOKEN,
            api_const.SSE_EVENT_TOOL_START,
            api_const.SSE_EVENT_TOOL_END,
            api_const.SSE_EVENT_TOOL_CALL,
            api_const.SSE_EVENT_REFUSAL,
            api_const.SSE_EVENT_SUGGESTIONS,
            api_const.SSE_EVENT_DONE,
            api_const.SSE_EVENT_ERROR,
        ):
            assert event.islower()
            assert " " not in event

        # SSE_DONE_MARKER format
        assert api_const.SSE_DONE_MARKER == "[DONE]"

    def test_models_constants_determinism_and_boundaries(self):
        # Critical clinical safety invariant: default temperature MUST be 0.0 for determinism
        assert mod_const.DEFAULT_TEMPERATURE == 0.0
        assert mod_const.DEFAULT_DETERMINISTIC_TEMPERATURE == 0.0

        # Timeout must be reasonable (> 5.0 seconds)
        assert mod_const.DEFAULT_TIMEOUT_SECONDS >= 5.0

        # Max tokens must be positive integer >= 256
        assert mod_const.DEFAULT_MAX_TOKENS >= 256

        # Providers: supported list contains all core providers
        for p in ["ollama", "google", "anthropic", "openai", "custom"]:
            assert p in mod_const.SUPPORTED_PROVIDERS

        # Provider aliases: all alias values must be in supported or mock
        for alias, target in mod_const.PROVIDER_ALIASES.items():
            assert target in mod_const.SUPPORTED_PROVIDERS or target == mod_const.PROVIDER_MOCK

        # Default models: every supported provider has a default model
        for p in mod_const.SUPPORTED_PROVIDERS:
            assert p in mod_const.DEFAULT_MODELS
            assert len(mod_const.DEFAULT_MODELS[p]) > 0
