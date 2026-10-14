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

"""Carefold Hexagonal Storage Port & Pluggable Architecture."""

from carefold.storage.adapters.local_adapter import LocalStorageAdapter
from carefold.storage.factory import (
    create_storage_adapter,
    get_storage,
    get_storage_adapter,
    reset_storage_adapter,
    reset_storage_adapters,
    set_storage_adapter,
)
from carefold.storage.ports.storage_port import (
    StorageError,
    StorageFile,
    StorageFileMetadata,
    StorageFileNotFoundError,
    StoragePort,
    StorageSecurityError,
)

__all__ = [
    "StoragePort",
    "StorageFileMetadata",
    "StorageFile",
    "StorageError",
    "StorageFileNotFoundError",
    "StorageSecurityError",
    "LocalStorageAdapter",
    "create_storage_adapter",
    "get_storage_adapter",
    "set_storage_adapter",
    "reset_storage_adapter",
    "reset_storage_adapters",
    "get_storage",
]
