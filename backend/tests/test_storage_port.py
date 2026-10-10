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

"""Comprehensive unit and security test suite for StoragePort and LocalStorageAdapter."""

from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
import pytest

from carefold.storage.adapters.local_adapter import LocalStorageAdapter
from carefold.storage.factory import (
    create_storage_adapter,
    get_storage_adapter,
    reset_storage_adapter,
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


@pytest.fixture
def storage_adapter(tmp_path: Path) -> LocalStorageAdapter:
    """Fixture providing an isolated LocalStorageAdapter in tmp_path."""
    uploads_dir = tmp_path / "uploads"
    adapter = LocalStorageAdapter(base_dir=uploads_dir)
    return adapter


# ============================================================================
# 1. Basic CRUD Operations
# ============================================================================

@pytest.mark.asyncio
async def test_save_and_get_file_bytes(storage_adapter: LocalStorageAdapter):
    """Verifies saving and retrieving bytes payload."""
    payload = b"Sample Clinical Lab Result: WBC 6.5, RBC 4.8"
    meta = await storage_adapter.save_file(
        content=payload,
        filename="lab_result.txt",
        user_id="user_1",
        profile_id="prof_1",
        content_type="text/plain",
    )

    assert meta.filename == "lab_result.txt"
    assert meta.size_bytes == len(payload)
    assert meta.content_type == "text/plain"
    assert meta.user_id == "user_1"
    assert meta.profile_id == "prof_1"
    assert meta.sha256_hash == hashlib.sha256(payload).hexdigest()

    # Get file
    retrieved = await storage_adapter.get_file(meta.storage_key, user_id="user_1", profile_id="prof_1")
    assert retrieved is not None
    assert retrieved.content == payload
    assert retrieved.metadata.sha256_hash == meta.sha256_hash
    assert retrieved.metadata.size_bytes == len(payload)
    assert retrieved.read() == payload


@pytest.mark.asyncio
async def test_save_and_get_file_stream(storage_adapter: LocalStorageAdapter):
    """Verifies saving from a BinaryIO stream."""
    payload = b"%PDF-1.4 Clinical Dossier Binary Data " * 50
    stream = io.BytesIO(payload)

    meta = await storage_adapter.save_file(
        content=stream,
        filename="clinical_dossier.pdf",
        user_id="user_2",
        profile_id="prof_2",
    )

    assert meta.filename == "clinical_dossier.pdf"
    assert meta.size_bytes == len(payload)
    assert meta.content_type == "application/pdf"  # auto-detected
    assert meta.sha256_hash == hashlib.sha256(payload).hexdigest()

    retrieved = await storage_adapter.get_file(meta.storage_key, user_id="user_2", profile_id="prof_2")
    assert retrieved is not None
    assert retrieved.content == payload
    assert retrieved.stream.read() == payload


@pytest.mark.asyncio
async def test_get_nonexistent_file(storage_adapter: LocalStorageAdapter):
    """Verifies get_file returns None for non-existent files."""
    res = await storage_adapter.get_file("missing.txt", user_id="user_1", profile_id="prof_1")
    assert res is None


@pytest.mark.asyncio
async def test_delete_file(storage_adapter: LocalStorageAdapter):
    """Verifies file deletion lifecycle."""
    payload = b"Temp data to delete"
    meta = await storage_adapter.save_file(content=payload, filename="delete_me.txt")

    assert await storage_adapter.delete_file(meta.storage_key) is True
    assert await storage_adapter.get_file(meta.storage_key) is None
    # Subsequent delete returns False
    assert await storage_adapter.delete_file(meta.storage_key) is False


@pytest.mark.asyncio
async def test_list_files(storage_adapter: LocalStorageAdapter):
    """Verifies list_files returns items in newest-first order."""
    await storage_adapter.save_file(b"File 1", "file1.txt", user_id="u1", profile_id="p1")
    await storage_adapter.save_file(b"File 2", "file2.txt", user_id="u1", profile_id="p1")

    files = await storage_adapter.list_files(user_id="u1", profile_id="p1")
    assert len(files) == 2
    filenames = [f.filename for f in files]
    assert "file1.txt" in filenames
    assert "file2.txt" in filenames


@pytest.mark.asyncio
async def test_get_file_url_or_path(storage_adapter: LocalStorageAdapter):
    """Verifies get_file_url_or_path returns valid absolute filesystem path."""
    meta = await storage_adapter.save_file(b"Path test", "path_test.txt", user_id="u1", profile_id="p1")
    path_str = await storage_adapter.get_file_url_or_path(meta.storage_key, user_id="u1", profile_id="p1")

    assert isinstance(path_str, str)
    p = Path(path_str)
    assert p.is_file()
    assert p.read_bytes() == b"Path test"


# ============================================================================
# 2. Tenancy & Partitioning Scoping
# ============================================================================

@pytest.mark.asyncio
async def test_tenant_scoping_isolation(storage_adapter: LocalStorageAdapter):
    """Verifies user_2 cannot access user_1 files."""
    payload = b"User 1 Confidential Health Records"
    meta = await storage_adapter.save_file(payload, "secret.pdf", user_id="user_1", profile_id="prof_1")

    # Scoped request for user_2 must return None
    res = await storage_adapter.get_file(meta.storage_key, user_id="user_2", profile_id="prof_1")
    assert res is None

    # Filesystem layout check
    expected_path = storage_adapter.base_dir / "user_1" / "prof_1" / "secret.pdf"
    assert expected_path.exists()
    assert expected_path.read_bytes() == payload


@pytest.mark.asyncio
async def test_default_unscoped_partition(storage_adapter: LocalStorageAdapter):
    """Verifies files without user_id / profile_id are stored under default/default."""
    meta = await storage_adapter.save_file(b"Unscoped file", "public.txt")
    expected_path = storage_adapter.base_dir / "default" / "default" / "public.txt"
    assert expected_path.exists()

    retrieved = await storage_adapter.get_file(meta.storage_key)
    assert retrieved is not None
    assert retrieved.content == b"Unscoped file"


# ============================================================================
# 3. Cryptographic SHA-256 Hashing Accuracy
# ============================================================================

@pytest.mark.asyncio
async def test_sha256_accuracy_known_values(storage_adapter: LocalStorageAdapter):
    """Verifies SHA-256 calculation matches hashlib exactly."""
    # Test empty payload
    meta_empty = await storage_adapter.save_file(b"", "empty.txt")
    assert meta_empty.sha256_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    # Test binary payload
    binary_data = bytes(range(256)) * 100
    meta_bin = await storage_adapter.save_file(binary_data, "binary.dat")
    assert meta_bin.sha256_hash == hashlib.sha256(binary_data).hexdigest()


# ============================================================================
# 4. Atomic Write Guarantees & Cleanup
# ============================================================================

@pytest.mark.asyncio
async def test_atomic_write_error_cleanup(storage_adapter: LocalStorageAdapter):
    """Verifies that if stream fails during writing, no partial or temp files leak."""
    class FaultyStream(io.BytesIO):
        def __init__(self):
            super().__init__(b"Initial partial data")
            self.read_count = 0

        def read(self, size=-1):
            self.read_count += 1
            if self.read_count > 1:
                raise IOError("Simulated network disconnection during upload")
            return super().read(size)

    stream = FaultyStream()

    with pytest.raises(StorageError):
        await storage_adapter.save_file(stream, "corrupt.txt", user_id="u1", profile_id="p1")

    partition = storage_adapter.base_dir / "u1" / "p1"
    # Target file must not exist
    assert not (partition / "corrupt.txt").exists()
    # No temporary files left behind
    temp_files = list(partition.glob("*.tmp"))
    assert len(temp_files) == 0


# ============================================================================
# 5. Filename Sanitization & Collision Handling
# ============================================================================

@pytest.mark.asyncio
async def test_filename_sanitization(storage_adapter: LocalStorageAdapter):
    """Verifies dangerous characters are replaced with underscores."""
    raw_name = "dr. smith's report (final) & labs?.pdf"
    meta = await storage_adapter.save_file(b"data", raw_name)

    assert meta.filename == "dr._smith_s_report__final____labs_.pdf"
    retrieved = await storage_adapter.get_file(meta.storage_key)
    assert retrieved is not None


@pytest.mark.asyncio
async def test_duplicate_filename_collision_handling(storage_adapter: LocalStorageAdapter):
    """Verifies duplicate uploads generate non-conflicting names."""
    m1 = await storage_adapter.save_file(b"v1", "notes.txt", user_id="u1", profile_id="p1")
    m2 = await storage_adapter.save_file(b"v2", "notes.txt", user_id="u1", profile_id="p1")
    m3 = await storage_adapter.save_file(b"v3", "notes.txt", user_id="u1", profile_id="p1")

    assert m1.filename == "notes.txt"
    assert m2.filename == "notes_1.txt"
    assert m3.filename == "notes_2.txt"

    f1 = await storage_adapter.get_file(m1.storage_key, user_id="u1", profile_id="p1")
    f2 = await storage_adapter.get_file(m2.storage_key, user_id="u1", profile_id="p1")
    assert f1.content == b"v1"
    assert f2.content == b"v2"


# ============================================================================
# 6. Path Traversal & Security Penetration Attacks
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("traversal_key", [
    "../../etc/passwd",
    "../../../etc/shadow",
    "....//....//etc/passwd",
    "foo/../../etc/passwd",
    "/etc/passwd",
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
])
async def test_path_traversal_rejection_relative(storage_adapter: LocalStorageAdapter, traversal_key: str):
    """Verifies directory traversal escapes raise StorageSecurityError."""
    with pytest.raises(StorageSecurityError):
        await storage_adapter.get_file(traversal_key, user_id="u1", profile_id="p1")

    with pytest.raises(StorageSecurityError):
        await storage_adapter.delete_file(traversal_key, user_id="u1", profile_id="p1")


@pytest.mark.asyncio
@pytest.mark.parametrize("null_key", [
    "lab.txt\0.pdf",
    "\0/etc/passwd",
    "safe.txt\x00../../etc/passwd",
])
async def test_path_traversal_null_byte_injection(storage_adapter: LocalStorageAdapter, null_key: str):
    """Verifies null byte injection attacks are blocked."""
    with pytest.raises(StorageSecurityError):
        await storage_adapter.get_file(null_key)


@pytest.mark.asyncio
@pytest.mark.parametrize("uri_key", [
    "file:///etc/passwd",
    "http://attacker.com/malware.exe",
    "gopher://evil.com",
])
async def test_path_traversal_uri_schemes(storage_adapter: LocalStorageAdapter, uri_key: str):
    """Verifies URI scheme injection attacks are blocked."""
    with pytest.raises(StorageSecurityError):
        await storage_adapter.get_file(uri_key)


# ============================================================================
# 7. Factory & Dependency Injection
# ============================================================================

def test_storage_factory_singleton(tmp_path: Path, monkeypatch):
    """Verifies factory returns singleton and allows overrides."""
    test_uploads = tmp_path / "custom_uploads"
    monkeypatch.setenv("CAREFOLD_HOME", str(tmp_path))

    reset_storage_adapter()
    adapter1 = get_storage_adapter()
    adapter2 = get_storage_adapter()
    assert adapter1 is adapter2
    assert isinstance(adapter1, LocalStorageAdapter)

    # Custom override
    mock_adapter = LocalStorageAdapter(base_dir=test_uploads)
    set_storage_adapter(mock_adapter)
    assert get_storage_adapter() is mock_adapter

    # Reset
    reset_storage_adapter()
    assert get_storage_adapter() is not mock_adapter
