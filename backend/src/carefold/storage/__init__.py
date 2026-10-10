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
