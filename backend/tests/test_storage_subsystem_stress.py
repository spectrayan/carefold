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

"""Test Suite for Storage Subsystem.

Stress-tests:
1. Path Traversal & Symlink Escapes (directory escapes, null bytes, URI schemes, symlinks outside uploads).
2. Concurrency & Collision (concurrent identical uploads, concurrent delete vs read).
3. Atomic Writes & Corrupted Staging (faulty stream aborts, dangling tmp files, sidecar corruption).
4. SHA-256 Hashing Integrity (known test vectors, single-bit avalanche, chunk boundary alignment).
5. Zero Host Leaks into ~/.carefold (sandbox confinement, environment isolation).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import List, Optional
from unittest.mock import patch
import pytest

from carefold.config import Settings
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
def test_uploads_dir(tmp_path: Path) -> Path:
    """Provides an isolated uploads directory under tmp_path."""
    uploads = tmp_path / "sandbox_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


@pytest.fixture
def storage(test_uploads_dir: Path) -> LocalStorageAdapter:
    """Provides a fresh LocalStorageAdapter rooted in test_uploads_dir."""
    return LocalStorageAdapter(base_dir=test_uploads_dir)


# ============================================================================
# Vector 1: Path Traversal & Symlink Escapes
# ============================================================================

class TestVector1PathTraversalAndSymlinks:
    """Stress-tests path traversal, null bytes, URI schemes, and symlink escapes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("traversal_key", [
        "../../etc/passwd",
        "../../../etc/shadow",
        "....//....//etc/passwd",
        "foo/../../etc/passwd",
        "/etc/passwd",
        "/var/root/secret",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "D:\\data\\secret.key",
        "file:///etc/passwd",
        "http://attacker.com/malware.exe",
        "gopher://evil.com",
        "foo.txt\x00.pdf",
        "\x00/etc/passwd",
        "normal.txt\x00../../etc/passwd",
        "test\\..\\..\\secret",
        "..%2f..%2fetc%2fpasswd",
    ])
    async def test_traversal_keys_blocked_with_security_error(
        self, storage: LocalStorageAdapter, traversal_key: str
    ):
        """Verifies directory escapes, null bytes, and URIs raise StorageSecurityError."""
        with pytest.raises(StorageSecurityError):
            await storage.get_file(traversal_key, user_id="u1", profile_id="p1")

        with pytest.raises(StorageSecurityError):
            await storage.delete_file(traversal_key, user_id="u1", profile_id="p1")

        with pytest.raises(StorageSecurityError):
            await storage.get_file_url_or_path(traversal_key, user_id="u1", profile_id="p1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url_encoded_key", [
        "%2e%2e/etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "%252e%252e%252f",
    ])
    async def test_url_encoded_traversal_contained_in_sandbox(
        self, storage: LocalStorageAdapter, url_encoded_key: str
    ):
        """Verifies that URL-encoded traversal keys never escape the sandbox base_dir."""
        try:
            resolved, clean_key = storage._resolve_safe_path(
                url_encoded_key, user_id="u1", profile_id="p1", must_exist=False
            )
            # Must strictly resolve inside storage.base_dir
            assert storage.base_dir in resolved.parents or resolved == storage.base_dir
            assert not resolved.is_relative_to(Path("/etc"))
        except StorageSecurityError:
            # Rejection with StorageSecurityError is also completely acceptable
            pass

    @pytest.mark.asyncio
    async def test_symlink_pointing_outside_uploads_rejected_on_read(
        self, storage: LocalStorageAdapter, tmp_path: Path
    ):
        """Verifies symlink pointing outside sandbox cannot be read via get_file or get_file_url_or_path."""
        outside_secret = tmp_path / "outside_host_secret.txt"
        outside_secret.write_text("CONFIDENTIAL_SYSTEM_CREDENTIALS")

        part_dir = storage._get_partition_dir(user_id="u1", profile_id="p1")
        symlink_file = part_dir / "evil_symlink.txt"
        os.symlink(outside_secret, symlink_file)

        # get_file must reject the escaping symlink
        with pytest.raises(StorageSecurityError):
            await storage.get_file("evil_symlink.txt", user_id="u1", profile_id="p1")

        # get_file_url_or_path must reject the escaping symlink
        with pytest.raises(StorageSecurityError):
            await storage.get_file_url_or_path("evil_symlink.txt", user_id="u1", profile_id="p1")

    @pytest.mark.asyncio
    async def test_save_file_does_not_overwrite_symlink_target_outside(
        self, storage: LocalStorageAdapter, tmp_path: Path
    ):
        """Verifies saving a file when a symlink already exists does not overwrite the symlink target."""
        outside_file = tmp_path / "external_target.txt"
        outside_file.write_text("ORIGINAL_EXTERNAL_CONTENT")

        part_dir = storage._get_partition_dir(user_id="u1", profile_id="p1")
        symlink_file = part_dir / "target.txt"
        os.symlink(outside_file, symlink_file)

        # Save file with the same name
        meta = await storage.save_file(
            content=b"ATTACKER_OVERWRITE",
            filename="target.txt",
            user_id="u1",
            profile_id="p1",
        )

        # The external target file must NOT be modified
        assert outside_file.read_text() == "ORIGINAL_EXTERNAL_CONTENT"
        # The upload must be auto-renamed away from the symlink
        assert meta.filename != "target.txt" or not symlink_file.is_symlink()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("malicious_id", [
        "../../etc",
        "../..",
        "/etc",
        "..\\..\\windows",
        "user\x00escape",
    ])
    async def test_user_and_profile_id_traversal_contained(
        self, storage: LocalStorageAdapter, malicious_id: str
    ):
        """Verifies malicious user_id or profile_id does not escape base_dir."""
        meta = await storage.save_file(
            content=b"test data",
            filename="safe.txt",
            user_id=malicious_id,
            profile_id=malicious_id,
        )
        file_path_str = await storage.get_file_url_or_path(
            meta.storage_key, user_id=malicious_id, profile_id=malicious_id
        )
        resolved_path = Path(file_path_str).resolve()
        assert storage.base_dir in resolved_path.parents


# ============================================================================
# Vector 2: Concurrency & Collision Stress
# ============================================================================

class TestVector2ConcurrencyAndCollision:
    """Stress-tests concurrent uploads with identical names and concurrent read vs delete."""

    @pytest.mark.asyncio
    async def test_concurrent_uploads_identical_filename_no_clobbering(
        self, storage: LocalStorageAdapter
    ):
        """Stress-test: 20 concurrent uploads of the same filename must NOT silently overwrite each other.

        Every uploaded file must be preserved with a unique filename and matching SHA-256 hash.
        """
        num_tasks = 20
        payloads = [f"Unique Patient Dossier Version {i}".encode() for i in range(num_tasks)]
        expected_hashes = [hashlib.sha256(p).hexdigest() for p in payloads]

        async def upload_task(idx: int) -> StorageFileMetadata:
            return await storage.save_file(
                content=payloads[idx],
                filename="clinical_summary.txt",
                user_id="user_race",
                profile_id="prof_race",
            )

        # Launch all 20 uploads simultaneously
        results: List[StorageFileMetadata] = await asyncio.gather(
            *[upload_task(i) for i in range(num_tasks)]
        )

        # Verify that all 20 uploads resulted in distinct filenames
        saved_filenames = [r.filename for r in results]
        unique_filenames = set(saved_filenames)

        # CHALLENGE ASSERTION: If unique_filenames < num_tasks, uploads were clobbered!
        assert len(unique_filenames) == num_tasks, (
            f"Concurrency Failure: {num_tasks} concurrent uploads produced only "
            f"{len(unique_filenames)} unique filenames. Filenames: {saved_filenames}. "
            f"Files were clobbered due to non-atomic path reservation race condition!"
        )

        # Verify each saved file exists on disk with its exact matching payload
        for i, meta in enumerate(results):
            retrieved = await storage.get_file(
                meta.storage_key, user_id="user_race", profile_id="prof_race"
            )
            assert retrieved is not None, f"File {meta.filename} missing on disk"
            assert retrieved.content == payloads[i], (
                f"File content clobbered for {meta.filename}: expected {payloads[i]!r}, "
                f"got {retrieved.content!r}"
            )
            assert retrieved.metadata.sha256_hash == expected_hashes[i]

    @pytest.mark.asyncio
    async def test_concurrent_delete_vs_read_graceful_no_unhandled_exception(
        self, storage: LocalStorageAdapter
    ):
        """Stress-test: get_file must return None (not raise FileNotFoundError) during concurrent deletion.

        StoragePort.get_file contract explicitly states:
        'Returns: StorageFile instance containing metadata and content, or None if not found.'
        """
        # Save an initial file
        await storage.save_file(
            content=b"Transient Medical Report",
            filename="transient.txt",
            user_id="u_race",
            profile_id="p_race",
        )

        caught_unhandled_exceptions: List[Exception] = []

        async def reader():
            for _ in range(40):
                try:
                    res = await storage.get_file(
                        "transient.txt", user_id="u_race", profile_id="p_race"
                    )
                    assert res is None or isinstance(res, StorageFile)
                except Exception as err:
                    caught_unhandled_exceptions.append(err)
                await asyncio.sleep(0.001)

        async def deleter_recreator():
            for _ in range(40):
                await storage.delete_file("transient.txt", user_id="u_race", profile_id="p_race")
                await storage.save_file(
                    b"New Transient Version",
                    "transient.txt",
                    user_id="u_race",
                    profile_id="p_race",
                )
                await asyncio.sleep(0.001)

        await asyncio.gather(reader(), deleter_recreator())

        # CHALLENGE ASSERTION: get_file must never leak raw FileNotFoundError
        raw_fnf_errors = [e for e in caught_unhandled_exceptions if isinstance(e, FileNotFoundError)]
        assert len(raw_fnf_errors) == 0, (
            f"Concurrency Failure: get_file raised {len(raw_fnf_errors)} unhandled "
            f"FileNotFoundError exceptions instead of returning None when file was unlinked: "
            f"{raw_fnf_errors}"
        )


# ============================================================================
# Vector 3: Atomic Writes & Corrupted Staging
# ============================================================================

class TestVector3AtomicWritesAndStaging:
    """Tests failure recovery during staging and atomic replacement guarantees."""

    @pytest.mark.asyncio
    async def test_stream_read_interruption_leaves_zero_orphaned_tmp_files(
        self, storage: LocalStorageAdapter
    ):
        """Verifies that an I/O abort during stream writing leaves no partial or .tmp files."""
        class FaultyNetworkStream(io.BytesIO):
            def __init__(self, data: bytes, fail_after_bytes: int):
                super().__init__(data)
                self.fail_after_bytes = fail_after_bytes
                self.bytes_read = 0

            def read(self, size: int = -1) -> bytes:
                if self.bytes_read >= self.fail_after_bytes:
                    raise IOError("Simulated network stream disconnect during upload")
                chunk = super().read(min(size, self.fail_after_bytes - self.bytes_read) if size > 0 else size)
                self.bytes_read += len(chunk)
                return chunk

        stream = FaultyNetworkStream(b"Valid prefix " * 1000, fail_after_bytes=500)

        with pytest.raises(StorageError):
            await storage.save_file(
                content=stream,
                filename="aborted_upload.pdf",
                user_id="u_atomic",
                profile_id="p_atomic",
            )

        part_dir = storage._get_partition_dir("u_atomic", "p_atomic")
        target_file = part_dir / "aborted_upload.pdf"
        assert not target_file.exists(), "Target file was created despite abort!"

        # Verify no .tmp files were left behind
        dangling_tmp = list(part_dir.glob("*.tmp"))
        assert len(dangling_tmp) == 0, f"Found orphaned temp files: {dangling_tmp}"

    @pytest.mark.asyncio
    async def test_atomic_replace_failure_preserves_original_file(
        self, storage: LocalStorageAdapter
    ):
        """Verifies that if os.replace fails, any existing target file is not corrupted."""
        original_payload = b"Original Immutable Medical Record"
        await storage.save_file(
            content=original_payload,
            filename="record.txt",
            user_id="u_atomic",
            profile_id="p_atomic",
        )

        part_dir = storage._get_partition_dir("u_atomic", "p_atomic")
        target_path = part_dir / "record.txt"

        # Mock os.replace to raise OSError (e.g. disk write failure)
        with patch("os.replace", side_effect=OSError("Disk full or permission denied")):
            with pytest.raises(StorageError):
                await storage.save_file(
                    content=b"New Corrupting Content",
                    filename="record_force.txt",
                    user_id="u_atomic",
                    profile_id="p_atomic",
                )

        # Original file must remain completely intact
        assert target_path.read_bytes() == original_payload

    @pytest.mark.asyncio
    async def test_corrupt_sidecar_metadata_recalculated_safely(
        self, storage: LocalStorageAdapter
    ):
        """Verifies get_file and list_files gracefully recover if .meta.json sidecar is corrupt."""
        payload = b"Payload with corrupt sidecar test"
        meta = await storage.save_file(payload, "sidecar_test.txt", user_id="u_sc", profile_id="p_sc")

        part_dir = storage._get_partition_dir("u_sc", "p_sc")
        sidecar = part_dir / ".sidecar_test.txt.meta.json"
        assert sidecar.exists()

        # Overwrite sidecar with malformed JSON
        sidecar.write_text("{malformed_json: true, unterminated", encoding="utf-8")

        # get_file must recover and recalculate hash from raw file
        retrieved = await storage.get_file("sidecar_test.txt", user_id="u_sc", profile_id="p_sc")
        assert retrieved is not None
        assert retrieved.content == payload
        assert retrieved.metadata.sha256_hash == hashlib.sha256(payload).hexdigest()

        # list_files must also recover
        files = await storage.list_files(user_id="u_sc", profile_id="p_sc")
        assert len(files) == 1
        assert files[0].sha256_hash == hashlib.sha256(payload).hexdigest()


# ============================================================================
# Vector 4: SHA-256 Hashing Integrity
# ============================================================================

class TestVector4SHA256HashingIntegrity:
    """Verifies cryptographic hash correctness, chunk boundaries, and avalanche effect."""

    @pytest.mark.asyncio
    async def test_nist_known_test_vectors(self, storage: LocalStorageAdapter):
        """Verifies SHA-256 against standard NIST test vectors."""
        # Vector 1: Empty string
        m_empty = await storage.save_file(b"", "empty.txt")
        assert m_empty.sha256_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        # Vector 2: 'abc'
        m_abc = await storage.save_file(b"abc", "abc.txt")
        assert m_abc.sha256_hash == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

        # Vector 3: 56-byte standard vector
        vec56 = b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
        m_vec56 = await storage.save_file(vec56, "vec56.txt")
        assert m_vec56.sha256_hash == "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"

    @pytest.mark.asyncio
    async def test_single_bit_flip_avalanche_effect(self, storage: LocalStorageAdapter):
        """Verifies that altering a single bit in the input causes a drastic hash divergence."""
        original = b"Critical Patient Lab Result: Hemoglobin 14.2 g/dL"
        flipped = bytearray(original)
        flipped[0] ^= 0x01  # Flip 1 bit in first byte

        m_orig = await storage.save_file(bytes(original), "orig.txt")
        m_flip = await storage.save_file(bytes(flipped), "flipped.txt")

        hash1 = m_orig.sha256_hash
        hash2 = m_flip.sha256_hash

        assert hash1 != hash2

        # Compute bit-level Hamming distance between the two hashes
        bin1 = bin(int(hash1, 16))[2:].zfill(256)
        bin2 = bin(int(hash2, 16))[2:].zfill(256)
        differing_bits = sum(b1 != b2 for b1, b2 in zip(bin1, bin2))

        # Cryptographic avalanche property: ~50% (128 bits) of output bits should change (>= 80 bits)
        assert differing_bits >= 80, (
            f"Insufficient avalanche effect: only {differing_bits}/256 bits changed!"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload_size", [
        64 * 1024 - 1,   # 65535 bytes (chunk boundary - 1)
        64 * 1024,       # 65536 bytes (exact 64KB chunk boundary)
        64 * 1024 + 1,   # 65537 bytes (chunk boundary + 1)
        256 * 1024 + 13, # 262157 bytes (multi-chunk odd size)
    ])
    async def test_streaming_chunk_boundary_integrity(
        self, storage: LocalStorageAdapter, payload_size: int
    ):
        """Verifies streaming SHA-256 calculation across 64KB chunk boundaries."""
        payload = os.urandom(payload_size)
        expected_hash = hashlib.sha256(payload).hexdigest()

        stream = io.BytesIO(payload)
        meta = await storage.save_file(stream, f"chunk_{payload_size}.bin")

        assert meta.size_bytes == payload_size
        assert meta.sha256_hash == expected_hash

        # Verify on-disk file has exact content and matching hash
        retrieved = await storage.get_file(meta.storage_key)
        assert retrieved is not None
        assert retrieved.content == payload
        assert hashlib.sha256(retrieved.content).hexdigest() == expected_hash


# ============================================================================
# Vector 5: Zero Host Leaks into ~/.carefold
# ============================================================================

class TestVector5ZeroHostLeaks:
    """Verifies that no test or storage operations leak files into ~/.carefold on the host."""

    def test_host_carefold_directory_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verifies operations execute strictly inside test sandbox, never host ~/.carefold."""
        host_home = Path.home() / ".carefold"
        existed_before = host_home.exists()

        # Isolate environment
        sandbox_home = tmp_path / "sandbox_home"
        monkeypatch.setenv("CAREFOLD_HOME", str(sandbox_home))

        reset_storage_adapter()
        cfg = Settings()
        adapter = LocalStorageAdapter(settings=cfg)

        assert adapter.base_dir.is_relative_to(sandbox_home)
        assert not str(adapter.base_dir).startswith(str(host_home))

        # Check host ~/.carefold was not created if it did not exist before
        if not existed_before:
            assert not host_home.exists(), "LEAK DETECTED: host ~/.carefold was created during test!"

    @pytest.mark.asyncio
    async def test_factory_singleton_isolation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verifies get_storage_adapter() respects CAREFOLD_HOME and does not leak."""
        test_dir1 = tmp_path / "env1"
        monkeypatch.setenv("CAREFOLD_HOME", str(test_dir1))
        reset_storage_adapter()

        adapter1 = get_storage_adapter(Settings())
        assert adapter1.base_dir.is_relative_to(test_dir1)

        test_dir2 = tmp_path / "env2"
        monkeypatch.setenv("CAREFOLD_HOME", str(test_dir2))
        reset_storage_adapter()

        adapter2 = get_storage_adapter(Settings())
        assert adapter2.base_dir.is_relative_to(test_dir2)
        assert adapter1 is not adapter2
