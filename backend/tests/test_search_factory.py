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

"""Unit and integration tests for SearchIndex factory and singleton lifecycle."""

import socket
import pytest

from carefold.search.adapters.spector import SpectorSearchIndex
from carefold.search.adapters.sqlite import SqliteSearchIndex
from carefold.search.factory import (
    create_search_index,
    get_search_index,
    is_spector_reachable,
    reset_search_indexes,
    set_search_index,
)


@pytest.fixture(autouse=True)
def clean_factory_state():
    """Ensures each test starts and ends with clean singleton factory state."""
    reset_search_indexes()
    yield
    reset_search_indexes()


class TestSearchFactoryReachability:
    """Tests socket reachability probe for Spector service."""

    def test_is_spector_reachable_returns_false_for_closed_port(self):
        # Port 59999 is almost certainly closed
        reachable = is_spector_reachable("http://127.0.0.1:59999", timeout=0.1)
        assert reachable is False

    def test_is_spector_reachable_handles_invalid_urls_gracefully(self):
        assert is_spector_reachable("http://nonexistent-host-xyz-999.invalid:7070", timeout=0.1) is False

    def test_is_spector_reachable_returns_true_for_open_socket(self):
        # Spin up a temporary listening socket on localhost
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        try:
            reachable = is_spector_reachable(f"http://127.0.0.1:{port}", timeout=0.5)
            assert reachable is True
        finally:
            server_sock.close()


class TestCreateSearchIndex:
    """Tests adapter instantiation and backend resolution logic."""

    def test_create_search_index_defaults_to_sqlite_when_spector_unreachable(self):
        # Port 59999 unreachable -> returns SqliteSearchIndex
        idx = create_search_index(spector_url="http://127.0.0.1:59999")
        assert isinstance(idx, SqliteSearchIndex)

    def test_create_search_index_explicit_spector_backend(self):
        idx = create_search_index(backend="spector", spector_url="http://localhost:7070")
        assert isinstance(idx, SpectorSearchIndex)

    def test_create_search_index_explicit_sqlite_backend(self, tmp_path):
        db_file = tmp_path / "custom.db"
        idx = create_search_index(backend="sqlite", db_path=db_file)
        assert isinstance(idx, SqliteSearchIndex)
        assert idx._db_path == str(db_file)

    def test_create_search_index_rejects_unsupported_backend(self):
        with pytest.raises(ValueError, match="Unsupported search backend"):
            create_search_index(backend="elasticsearch")


class TestGetSearchIndexSingleton:
    """Tests singleton caching, test double injection, and teardown."""

    def test_get_search_index_returns_cached_singleton(self):
        idx1 = get_search_index()
        idx2 = get_search_index()
        assert idx1 is idx2

    def test_reset_search_indexes_clears_singleton(self):
        idx1 = get_search_index()
        reset_search_indexes()
        idx2 = get_search_index()
        assert idx1 is not idx2

    def test_set_search_index_injects_custom_instance(self, tmp_path):
        custom_idx = SqliteSearchIndex(db_path=tmp_path / "injected.db")
        set_search_index(custom_idx)

        resolved = get_search_index()
        assert resolved is custom_idx

    def test_get_search_index_explicit_use_spector_flag(self):
        class DummyClient:
            pass

        client = DummyClient()
        spector_idx = get_search_index(use_spector=True, spector_client=client)
        assert isinstance(spector_idx, SpectorSearchIndex)

        sqlite_idx = get_search_index(use_spector=False)
        assert isinstance(sqlite_idx, SqliteSearchIndex)
