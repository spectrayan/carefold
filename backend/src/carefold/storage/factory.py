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

"""Storage adapter factory and FastAPI dependency lifecycle management."""

from __future__ import annotations

import logging
import os
from typing import Optional

from carefold.config import Settings, settings as global_settings
from carefold.storage.adapters.local_adapter import LocalStorageAdapter
from carefold.storage.ports.storage_port import StoragePort

logger = logging.getLogger("carefold.storage.factory")

STORAGE_BACKEND_LOCAL = "local"
STORAGE_BACKEND_S3 = "s3"
STORAGE_BACKEND_GCS = "gcs"

SUPPORTED_STORAGE_BACKENDS = frozenset({
    STORAGE_BACKEND_LOCAL,
    STORAGE_BACKEND_S3,
    STORAGE_BACKEND_GCS,
})

ENV_STORAGE_BACKEND = "CAREFOLD_STORAGE_BACKEND"
DEFAULT_STORAGE_BACKEND = STORAGE_BACKEND_LOCAL

_CACHED_STORAGE_ADAPTER: Optional[StoragePort] = None
_IS_MANUALLY_SET: bool = False


def create_storage_adapter(
    settings: Optional[Settings] = None,
    backend: Optional[str] = None,
) -> StoragePort:
    """Instantiates a new StoragePort adapter based on configured backend.

    Args:
        settings: Optional Settings instance. Defaults to global settings.
        backend: Optional backend override ('local', 's3', 'gcs').

    Returns:
        Instance implementing StoragePort.

    Raises:
        NotImplementedError: If requested backend is 's3' or 'gcs'.
        ValueError: If requested backend is unrecognized.
    """
    cfg = settings or global_settings
    selected_backend = (backend or os.getenv(ENV_STORAGE_BACKEND, DEFAULT_STORAGE_BACKEND)).lower().strip()

    if selected_backend not in SUPPORTED_STORAGE_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_STORAGE_BACKENDS))
        raise ValueError(
            f"Unsupported storage backend: '{selected_backend}'. Supported backends: {supported}."
        )

    if selected_backend == STORAGE_BACKEND_LOCAL:
        return LocalStorageAdapter(settings=cfg)
    elif selected_backend in (STORAGE_BACKEND_S3, STORAGE_BACKEND_GCS):
        raise NotImplementedError(
            f"Storage backend '{selected_backend}' is planned for future milestones. "
            "Please use 'local' backend."
        )
    else:
        raise ValueError(f"Unrecognized storage backend: '{selected_backend}'")


def get_storage_adapter(settings: Optional[Settings] = None) -> StoragePort:
    """Returns the singleton StoragePort instance, instantiating it on first call.

    Args:
        settings: Optional Settings instance to initialize with.
    """
    global _CACHED_STORAGE_ADAPTER
    cfg = settings or global_settings

    if _CACHED_STORAGE_ADAPTER is not None:
        if not _IS_MANUALLY_SET and hasattr(_CACHED_STORAGE_ADAPTER, "base_dir"):
            expected_dir = cfg.get_uploads_dir().resolve()
            if getattr(_CACHED_STORAGE_ADAPTER, "base_dir") != expected_dir:
                _CACHED_STORAGE_ADAPTER = create_storage_adapter(settings=cfg)
                return _CACHED_STORAGE_ADAPTER
        return _CACHED_STORAGE_ADAPTER

    _CACHED_STORAGE_ADAPTER = create_storage_adapter(settings=cfg)
    return _CACHED_STORAGE_ADAPTER


def set_storage_adapter(adapter: StoragePort) -> None:
    """Overrides the global StoragePort singleton for testing or custom adapters."""
    global _CACHED_STORAGE_ADAPTER, _IS_MANUALLY_SET
    _CACHED_STORAGE_ADAPTER = adapter
    _IS_MANUALLY_SET = True


def reset_storage_adapter() -> None:
    """Resets the cached StoragePort singleton reference to None for test isolation."""
    global _CACHED_STORAGE_ADAPTER, _IS_MANUALLY_SET
    _CACHED_STORAGE_ADAPTER = None
    _IS_MANUALLY_SET = False


reset_storage_adapters = reset_storage_adapter


# ============================================================================
# FastAPI Dependency Injection
# ============================================================================

def get_storage() -> StoragePort:
    """FastAPI dependency provider resolving the active StoragePort singleton."""
    return get_storage_adapter()
