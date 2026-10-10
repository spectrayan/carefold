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

"""Hexagonal StoragePort interface, data schemas, and domain exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
from typing import Any, BinaryIO, Dict, List, Optional, Union

from carefold.tools.sandbox import SandboxSecurityError


# ============================================================================
# Domain Exceptions
# ============================================================================

class StorageError(Exception):
    """Base exception for all storage subsystem operations."""


class StorageFileNotFoundError(StorageError, FileNotFoundError):
    """Raised when a requested storage key does not exist."""


class StorageSecurityError(StorageError, SandboxSecurityError):
    """Raised when an operation violates sandbox containment or path traversal rules."""


# ============================================================================
# Domain Data Schemas
# ============================================================================

@dataclass(frozen=True)
class StorageFileMetadata:
    """Immutable metadata record for a stored file object.

    Attributes:
        storage_key: Canonical relative storage key (e.g. 'lab_results.pdf' or 'user/prof/lab.pdf').
        filename: Sanitized unique filename on physical storage.
        size_bytes: Total file size in bytes.
        content_type: MIME content type (e.g. 'application/pdf', 'text/plain').
        sha256_hash: Hex-encoded SHA-256 cryptographic digest of the file content.
        user_id: Owner user UUID, or None for offline/unscoped storage.
        profile_id: Associated care profile UUID, or None if unassigned.
        created_at: Upload/creation UTC timestamp.
    """

    storage_key: str
    filename: str
    size_bytes: int
    content_type: str
    sha256_hash: str
    user_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def byte_size(self) -> int:
        """Alias for size_bytes for backward compatibility."""
        return self.size_bytes

    @property
    def mime_type(self) -> str:
        """Alias for content_type for backward compatibility."""
        return self.content_type

    def to_dict(self) -> Dict[str, Any]:
        """Serializes metadata to a JSON-compatible dictionary."""
        return {
            "storage_key": self.storage_key,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "sha256_hash": self.sha256_hash,
            "user_id": self.user_id,
            "profile_id": self.profile_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StorageFileMetadata":
        """Reconstructs metadata from a dictionary representation."""
        created_raw = data.get("created_at")
        if isinstance(created_raw, str):
            created_dt = datetime.fromisoformat(created_raw)
        elif isinstance(created_raw, datetime):
            created_dt = created_raw
        else:
            created_dt = datetime.now(timezone.utc)

        return cls(
            storage_key=str(data["storage_key"]),
            filename=str(data["filename"]),
            size_bytes=int(data["size_bytes"]),
            content_type=str(data.get("content_type") or data.get("mime_type") or "application/octet-stream"),
            sha256_hash=str(data["sha256_hash"]),
            user_id=data.get("user_id"),
            profile_id=data.get("profile_id"),
            created_at=created_dt,
        )


@dataclass
class StorageFile:
    """Retrieved file representation carrying metadata and byte content / stream.

    Attributes:
        metadata: Associated StorageFileMetadata.
        content: Raw byte content of the file.
    """

    metadata: StorageFileMetadata
    content: bytes

    @property
    def stream(self) -> io.BytesIO:
        """Returns an in-memory BinaryIO stream over the file bytes."""
        return io.BytesIO(self.content)

    def read(self, size: int = -1) -> bytes:
        """Convenience read method mimicking file-like objects."""
        if size < 0:
            return self.content
        return self.content[:size]


# ============================================================================
# Hexagonal Port Interface
# ============================================================================

class StoragePort(ABC):
    """Hexagonal port defining pluggable file storage operations.

    Implementations must guarantee:
    1. Scoped data partitioning across users and profiles.
    2. Strict containment within the configured storage sandbox.
    3. Calculation and verification of cryptographic SHA-256 digests.
    4. Atomic persistence preventing partial/corrupt files during failure.
    """

    @abstractmethod
    async def save_file(
        self,
        content: Union[bytes, BinaryIO],
        filename: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> StorageFileMetadata:
        """Persists a file into storage, returning its computed metadata.

        Args:
            content: Raw byte payload or readable binary stream.
            filename: Target file name (sanitized by adapter).
            user_id: Optional owner user UUID for multi-tenant isolation.
            profile_id: Optional care profile UUID for family scoping.
            content_type: Optional MIME content type; detected from filename if None.

        Returns:
            StorageFileMetadata describing the newly stored file.

        Raises:
            StorageSecurityError: If filename or path causes a traversal escape.
            StorageError: If disk or underlying I/O operation fails.
        """
        ...

    @abstractmethod
    async def get_file(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> Optional[StorageFile]:
        """Retrieves a file payload and its metadata.

        Args:
            storage_key: File key or filename within the scope.
            user_id: Optional owner user UUID for access scoping.
            profile_id: Optional care profile UUID for access scoping.

        Returns:
            StorageFile instance containing metadata and content, or None if not found.

        Raises:
            StorageSecurityError: If storage_key attempts directory traversal escape.
        """
        ...

    @abstractmethod
    async def delete_file(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> bool:
        """Deletes a file from storage.

        Args:
            storage_key: File key or filename to remove.
            user_id: Optional owner user UUID for access scoping.
            profile_id: Optional care profile UUID for access scoping.

        Returns:
            True if file was deleted, False if file did not exist.

        Raises:
            StorageSecurityError: If storage_key attempts directory traversal escape.
        """
        ...

    @abstractmethod
    async def list_files(
        self,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> List[StorageFileMetadata]:
        """Lists metadata for all files in the specified user and profile partition.

        Args:
            user_id: Optional user filter. If None, lists files in the unscoped partition.
            profile_id: Optional profile filter.

        Returns:
            List of StorageFileMetadata ordered chronologically (newest first).
        """
        ...

    @abstractmethod
    async def get_file_url_or_path(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> str:
        """Returns a physical filesystem path (for local adapters) or download URL (for cloud).

        Args:
            storage_key: File key or filename within the scope.
            user_id: Optional owner user UUID.
            profile_id: Optional care profile UUID.

        Returns:
            Absolute local filesystem path as string, or HTTPS URL.

        Raises:
            StorageFileNotFoundError: If the target file does not exist.
            StorageSecurityError: If storage_key escapes sandbox boundaries.
        """
        ...
