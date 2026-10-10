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

"""Unit tests for Settings memory additions, factory resolution, and adapter instantiation."""

from pathlib import Path
import pytest

from carefold.config import Settings
from carefold.constants.paths import DEFAULT_CATALOG_DB
from carefold.memory.factory import (
    create_catalog_port,
    create_memory_port,
    get_catalog_port,
    get_memory_port,
    reset_memory_ports,
    set_catalog_port,
    set_memory_port,
)
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.memory.ports.memory_port import MemoryPort


class TestSettingsMemoryAdditions:
    """Verifies Settings schema, default attributes, and path resolution."""

    def test_settings_default_values(self) -> None:
        settings = Settings()
        assert settings.memory_backend == "sqlite"
        assert settings.spector_url == "http://localhost:7070"
        assert settings.catalog_db_path is None
        assert settings.get_catalog_db_path() == settings.home_dir / DEFAULT_CATALOG_DB

    def test_settings_custom_catalog_db_path(self, tmp_path: Path) -> None:
        custom_file = tmp_path / "custom_catalog.db"
        settings = Settings(catalog_db_path=custom_file)
        assert settings.catalog_db_path == custom_file
        assert settings.get_catalog_db_path() == custom_file

    def test_settings_env_var_overrides(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        env_db = str(tmp_path / "env_catalog.db")
        monkeypatch.setenv("CAREFOLD_MEMORY_BACKEND", "sqlite")
        monkeypatch.setenv("CAREFOLD_SPECTOR_URL", "http://spector.internal:9090")
        monkeypatch.setenv("CAREFOLD_CATALOG_DB_PATH", env_db)

        settings = Settings()
        assert settings.memory_backend == "sqlite"
        assert settings.spector_url == "http://spector.internal:9090"
        assert settings.get_catalog_db_path() == Path(env_db)


class TestMemoryFactoryResolution:
    """Verifies adapter resolution, singleton caching, and exception semantics."""

    def setup_method(self) -> None:
        reset_memory_ports()

    def teardown_method(self) -> None:
        reset_memory_ports()

    def test_factory_resolves_sqlite_by_default(self, tmp_path: Path) -> None:
        test_settings = Settings(catalog_db_path=tmp_path / "factory_test.db")
        mem_port = get_memory_port(test_settings)
        cat_port = get_catalog_port(test_settings)

        assert isinstance(mem_port, MemoryPort)
        assert isinstance(cat_port, CatalogPort)

    def test_factory_singleton_behavior(self, tmp_path: Path) -> None:
        test_settings = Settings(catalog_db_path=tmp_path / "singleton_test.db")
        p1 = get_memory_port(test_settings)
        p2 = get_memory_port()
        assert p1 is p2

        c1 = get_catalog_port(test_settings)
        c2 = get_catalog_port()
        assert c1 is c2

    def test_factory_reset_memory_ports(self, tmp_path: Path) -> None:
        test_settings = Settings(catalog_db_path=tmp_path / "reset_test.db")
        p1 = get_memory_port(test_settings)
        reset_memory_ports()
        p2 = get_memory_port(test_settings)
        assert p1 is not p2

    def test_factory_explicit_set_ports(self, tmp_path: Path) -> None:
        custom_mem = create_memory_port(db_path=tmp_path / "explicit_mem.db")
        custom_cat = create_catalog_port(db_path=tmp_path / "explicit_cat.db")

        set_memory_port(custom_mem)
        set_catalog_port(custom_cat)

        assert get_memory_port() is custom_mem
        assert get_catalog_port() is custom_cat

    def test_factory_spector_backend_creates_memory_port(self) -> None:
        spector_settings = Settings(
            memory_backend="spector",
            spector_url="http://localhost:7070",
        )

        mem = get_memory_port(spector_settings)
        assert isinstance(mem, MemoryPort)
        assert hasattr(mem, "store")

        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(spector_settings)
        assert "Spector" in str(exc_cat.value) or "spector" in str(exc_cat.value)

    def test_factory_postgres_backend_raises_not_implemented_error(self) -> None:
        postgres_settings = Settings(memory_backend="postgres")

        with pytest.raises(NotImplementedError) as exc_mem:
            get_memory_port(postgres_settings)
        assert "PostgreSQL" in str(exc_mem.value) or "postgres" in str(exc_mem.value)

        with pytest.raises(NotImplementedError) as exc_cat:
            get_catalog_port(postgres_settings)
        assert "PostgreSQL" in str(exc_cat.value) or "postgres" in str(exc_cat.value)

    def test_factory_unsupported_backend_raises_value_error(self) -> None:
        invalid_settings = Settings(memory_backend="unsupported_engine")

        with pytest.raises(ValueError) as exc_info:
            get_memory_port(invalid_settings)
        assert "unsupported_engine" in str(exc_info.value)
        assert "sqlite" in str(exc_info.value)

    def test_create_ports_with_explicit_overrides(self, tmp_path: Path) -> None:
        explicit_db = tmp_path / "explicit.db"
        mem = create_memory_port(db_path=explicit_db)
        cat = create_catalog_port(db_path=explicit_db)

        assert isinstance(mem, MemoryPort)
        assert isinstance(cat, CatalogPort)
