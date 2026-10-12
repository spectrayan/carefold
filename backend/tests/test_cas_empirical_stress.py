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

"""Empirical adversarial stress test suite for Content-Addressed Storage CAS (R3).

Tests:
1. CAS storage layout <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>.
2. Content deduplication: saving identical content under the same profile deduplicates
   correctly and returns correct metadata.
3. Corrupted file handling: truncated/tampered disk files, hash mismatch semantics.
4. Zero-byte file handling: canonical SHA-256 digest, round-trip read, and deduplication.
5. Concurrent saves of the same content: race condition resilience, no collisions.
6. Atomic writes: no partial reads observed by concurrent readers, temp file cleanup.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
from pathlib import Path
import threading
import time
from typing import List, Tuple
import uuid
import pytest

from carefold.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    sanitize_partition_segment,
    store_cas_file,
)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ============================================================================
# 1. CAS STORAGE LAYOUT & PARTITION ISOLATION
# ============================================================================

class TestCasStorageLayoutAndPartitionIsolation:
    """Verifies layout <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>."""

    def test_cas_path_canonical_structure(self, tmp_path: Path):
        """Path structure must be exactly data/files/<user_id>/<profile_id>/<sha256>."""
        user_id = "user_alpha_01"
        profile_id = "prof_omega_99"
        dummy_hash = "abcdef0123456789" * 4

        path = get_cas_path(tmp_path, user_id, profile_id, dummy_hash)
        expected = tmp_path.resolve() / "data" / "files" / user_id / profile_id / dummy_hash

        assert path == expected
        assert path.name == dummy_hash
        assert path.parent.name == profile_id
        assert path.parent.parent.name == user_id
        assert path.parent.parent.parent.name == "files"
        assert path.parent.parent.parent.parent.name == "data"

    def test_cas_path_uuid_and_complex_identifiers(self, tmp_path: Path):
        """Handles UUIDs, dots, hyphens, and underscores correctly."""
        uid = str(uuid.uuid4())
        pid = str(uuid.uuid4())
        sha = hashlib.sha256(b"diagnostic test").hexdigest()

        path = get_cas_path(tmp_path, uid, pid, sha)
        assert path.parent.name == pid
        assert path.parent.parent.name == uid

    def test_cas_path_sha256_case_insensitivity(self, tmp_path: Path):
        """Uppercase hex SHA-256 is converted to lowercase canonical filename."""
        raw_sha = "A1B2C3D4E5F6" + "0" * 52
        expected_lower = raw_sha.lower()

        path = get_cas_path(tmp_path, "u1", "p1", raw_sha)
        assert path.name == expected_lower

    @pytest.mark.parametrize("invalid_hash", [
        "",
        "short",
        "a" * 63,
        "a" * 65,
        "g" * 64,  # non-hex
        "z" * 64,  # non-hex
        " " * 64,
        "a" * 63 + "!",
        "a" * 32 + "/" + "b" * 31,
        "a" * 32 + "\n" + "b" * 31,
    ])
    def test_cas_path_invalid_hash_rejection(self, tmp_path: Path, invalid_hash: str):
        """Any non-64-hex SHA-256 must raise ValueError immediately."""
        with pytest.raises(ValueError) as exc:
            get_cas_path(tmp_path, "user", "profile", invalid_hash)
        assert "Invalid SHA-256" in str(exc.value)

    def test_cas_path_whitespace_stripping(self, tmp_path: Path):
        """Leading/trailing whitespace on SHA-256 is stripped and normalized."""
        clean = "a" * 64
        padded = f"  \n\t{clean}\t\n  "
        path = get_cas_path(tmp_path, "user", "profile", padded)
        assert path.name == clean

    @pytest.mark.parametrize("traversal_segment", [
        "../evil",
        "..\\evil",
        "evil/../../root",
        "/etc/passwd",
        "\\Windows\\System32",
        "profile\0nullbyte",
        "..",
        ".",
    ])
    def test_cas_path_directory_traversal_rejection(self, tmp_path: Path, traversal_segment: str):
        """Directory traversal attempts in user_id or profile_id are blocked."""
        valid_sha = "0" * 64
        # Test in user_id
        if any(c in traversal_segment for c in ("/", "\\", "\0", "..")):
            with pytest.raises(ValueError):
                get_cas_path(tmp_path, traversal_segment, "valid_prof", valid_sha)

            with pytest.raises(ValueError):
                get_cas_path(tmp_path, "valid_user", traversal_segment, valid_sha)

    def test_cas_partition_strict_isolation(self, tmp_path: Path):
        """Identical content stored in different partitions creates physically isolated files."""
        content = b"Shared Sensitive Clinical Observation"
        sha = hashlib.sha256(content).hexdigest()

        # User 1, Profile A
        path_1a, sha_1a, dedup_1a = store_cas_file(content, tmp_path, "user_1", "prof_a")
        # User 1, Profile B (same user, different profile)
        path_1b, sha_1b, dedup_1b = store_cas_file(content, tmp_path, "user_1", "prof_b")
        # User 2, Profile A (different user, same profile name)
        path_2a, sha_2a, dedup_2a = store_cas_file(content, tmp_path, "user_2", "prof_a")

        assert sha_1a == sha_1b == sha_2a == sha
        # None of them were deduplicated across partitions
        assert dedup_1a is False
        assert dedup_1b is False
        assert dedup_2a is False

        # Paths must be distinct
        assert len({path_1a, path_1b, path_2a}) == 3
        assert path_1a.exists() and path_1b.exists() and path_2a.exists()

        # Modifying or unlinking path_1a does not affect path_1b or path_2a
        path_1a.unlink()
        assert not path_1a.exists()
        assert path_1b.exists() and path_1b.read_bytes() == content
        assert path_2a.exists() and path_2a.read_bytes() == content


# ============================================================================
# 2. CONTENT DEDUPLICATION & METADATA INTEGRITY
# ============================================================================

class TestCasContentDeduplication:
    """Verifies per-profile deduplication and metadata consistency."""

    def test_deduplication_exact_match(self, tmp_path: Path):
        """Second save of identical content returns is_deduplicated=True with same path."""
        content = b"Patient vitals: BP 120/80, HR 72, SpO2 99%"
        expected_sha = hashlib.sha256(content).hexdigest()

        # 1st save
        path1, sha1, dedup1 = store_cas_file(content, tmp_path, "u_test", "p_test")
        assert sha1 == expected_sha
        assert dedup1 is False
        assert path1.is_file()
        assert path1.read_bytes() == content

        # 2nd save
        path2, sha2, dedup2 = store_cas_file(content, tmp_path, "u_test", "p_test")
        assert sha2 == expected_sha
        assert dedup2 is True
        assert path2 == path1
        assert path2.read_bytes() == content

    def test_deduplication_does_not_modify_mtime(self, tmp_path: Path):
        """Deduplicated store skips disk write, leaving st_mtime untouched."""
        content = b"Telemetry stream chunk: EKG Lead II nominal"
        path1, _, _ = store_cas_file(content, tmp_path, "u_mtime", "p_mtime")
        initial_mtime = path1.stat().st_mtime_ns

        # Sleep briefly to ensure resolution difference if rewritten
        time.sleep(0.01)

        path2, _, dedup = store_cas_file(content, tmp_path, "u_mtime", "p_mtime")
        assert dedup is True
        assert path2.stat().st_mtime_ns == initial_mtime

    def test_deduplication_across_multiple_iterations(self, tmp_path: Path):
        """Repeated stores across 10 iterations remain cleanly deduplicated."""
        content = b"Repeated clinical note hash validation"
        expected_sha = hashlib.sha256(content).hexdigest()

        for i in range(10):
            path, sha, dedup = store_cas_file(content, tmp_path, "u_iter", "p_iter")
            assert sha == expected_sha
            if i == 0:
                assert dedup is False
            else:
                assert dedup is True
            assert path.read_bytes() == content


# ============================================================================
# 3. ZERO-BYTE FILE HANDLING
# ============================================================================

class TestCasZeroByteHandling:
    """Verifies edge case: empty file b"" in CAS storage."""

    def test_zero_byte_store_and_read(self, tmp_path: Path):
        """Empty bytes are stored under the standard empty SHA-256 digest."""
        empty_content = b""
        path, sha, dedup = store_cas_file(empty_content, tmp_path, "u_zero", "p_zero")

        assert sha == EMPTY_SHA256
        assert dedup is False
        assert path.is_file()
        assert path.stat().st_size == 0
        assert path.name == EMPTY_SHA256

        # Read back
        read_back = read_cas_file(tmp_path, "u_zero", "p_zero", EMPTY_SHA256)
        assert read_back == b""
        assert len(read_back) == 0

    def test_zero_byte_deduplication(self, tmp_path: Path):
        """Zero-byte file deduplicates cleanly on second store."""
        empty_content = b""
        path1, sha1, dedup1 = store_cas_file(empty_content, tmp_path, "u_zero_dup", "p_zero_dup")
        assert dedup1 is False

        path2, sha2, dedup2 = store_cas_file(empty_content, tmp_path, "u_zero_dup", "p_zero_dup")
        assert dedup2 is True
        assert path1 == path2
        assert path2.stat().st_size == 0

    def test_zero_byte_exists_check(self, tmp_path: Path):
        """cas_file_exists reports True for stored zero-byte file."""
        assert not cas_file_exists(tmp_path, "u_zero_ex", "p_zero_ex", EMPTY_SHA256)
        store_cas_file(b"", tmp_path, "u_zero_ex", "p_zero_ex")
        assert cas_file_exists(tmp_path, "u_zero_ex", "p_zero_ex", EMPTY_SHA256)


# ============================================================================
# 4. CORRUPTED FILE HANDLING & HEALING
# ============================================================================

class TestCasCorruptedFileHandling:
    """Verifies behavior when files on disk are corrupted, truncated, or tampered."""

    def test_truncated_corrupt_file_is_healed_on_store(self, tmp_path: Path):
        """If a file on disk has size mismatch (e.g. truncated), store_cas_file re-writes it cleanly."""
        full_content = b"Full Lab Report: Sodium 140, Potassium 4.2, Chloride 102, CO2 24"
        sha = hashlib.sha256(full_content).hexdigest()

        canonical_path = get_cas_path(tmp_path, "u_heal", "p_heal", sha)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)

        # Corrupt file on disk: truncate to only 10 bytes
        truncated_bytes = full_content[:10]
        canonical_path.write_bytes(truncated_bytes)
        assert canonical_path.stat().st_size == 10

        # Now call store_cas_file with the full content
        path, returned_sha, dedup = store_cas_file(full_content, tmp_path, "u_heal", "p_heal")

        # Because size was different, dedup must be False and file must be repaired
        assert dedup is False
        assert returned_sha == sha
        assert path.stat().st_size == len(full_content)
        assert path.read_bytes() == full_content

    def test_enlarged_corrupt_file_is_healed_on_store(self, tmp_path: Path):
        """If a file on disk has extra appended bytes, store_cas_file re-writes it cleanly."""
        content = b"Baseline Prescription"
        sha = hashlib.sha256(content).hexdigest()

        canonical_path = get_cas_path(tmp_path, "u_enlarge", "p_enlarge", sha)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)

        # Appended corrupt bytes
        canonical_path.write_bytes(content + b"EXTRA_CORRUPT_BYTES_TRAILING")
        assert canonical_path.stat().st_size > len(content)

        path, returned_sha, dedup = store_cas_file(content, tmp_path, "u_enlarge", "p_enlarge")

        assert dedup is False
        assert path.stat().st_size == len(content)
        assert path.read_bytes() == content

    def test_read_missing_file_raises_filenotfound(self, tmp_path: Path):
        """Reading a non-existent file raises FileNotFoundError."""
        missing_sha = "f" * 64
        with pytest.raises(FileNotFoundError) as exc:
            read_cas_file(tmp_path, "u_miss", "p_miss", missing_sha)
        assert "not found" in str(exc.value)

    def test_read_with_invalid_sha_raises_valueerror(self, tmp_path: Path):
        """Reading with an invalid hash format raises ValueError."""
        with pytest.raises(ValueError):
            read_cas_file(tmp_path, "u_val", "p_val", "bad_hash")


# ============================================================================
# 5. ATOMIC WRITES & TEMPORARY FILE CLEANUP
# ============================================================================

class TestCasAtomicWrites:
    """Verifies atomic rename semantics and cleanup of temporary files."""

    def test_temp_file_created_in_same_partition_and_cleaned(self, tmp_path: Path):
        """Atomic write creates .<sha>.<uuid>.tmp in same directory and leaves no orphan tmp."""
        content = b"Atomic Write Payload Diagnostic"
        path, sha, _ = store_cas_file(content, tmp_path, "u_atom", "p_atom")

        # After store, parent directory must contain ONLY the canonical file
        parent_dir = path.parent
        files_in_dir = list(parent_dir.iterdir())

        assert len(files_in_dir) == 1
        assert files_in_dir[0] == path
        # No .tmp files left
        tmp_files = [f for f in parent_dir.iterdir() if f.name.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_cleanup_of_temp_file_on_simulated_failure(self, tmp_path: Path, monkeypatch):
        """If os.replace raises an error, the temporary file is unlinked in finally block."""
        content = b"Failure Simulation Payload"
        sha = hashlib.sha256(content).hexdigest()
        canonical_path = get_cas_path(tmp_path, "u_fail", "p_fail", sha)

        def mock_replace(src, dst):
            raise OSError("Simulated atomic rename failure (e.g. disk quota or permission)")

        monkeypatch.setattr(os, "replace", mock_replace)

        with pytest.raises(OSError):
            store_cas_file(content, tmp_path, "u_fail", "p_fail")

        # Check if parent directory exists and contains any leftover .tmp files
        if canonical_path.parent.exists():
            tmp_files = [f for f in canonical_path.parent.iterdir() if f.name.endswith(".tmp")]
            assert len(tmp_files) == 0


# ============================================================================
# 6. CONCURRENCY STRESS TESTING
# ============================================================================

class TestCasConcurrencyStress:
    """Stress tests: 50 concurrent threads writing identical/distinct content."""

    def test_concurrent_same_content_writes_resilience(self, tmp_path: Path):
        """50 concurrent threads storing the exact same 256KB payload simultaneously."""
        payload_chunk = b"CLINICAL_DISCHARGE_SUMMARY_LONG_TEXT_ROW\n" * 6000  # ~252 KB
        expected_sha = hashlib.sha256(payload_chunk).hexdigest()
        user_id = "user_concurrent_same"
        profile_id = "prof_concurrent_same"

        concurrency = 50
        results: List[Tuple[Path, str, bool]] = []
        errors: List[Exception] = []

        def worker_task(thread_idx: int):
            try:
                res = store_cas_file(payload_chunk, tmp_path, user_id, profile_id)
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Zero exceptions across all 50 threads
        assert len(errors) == 0, f"Encountered concurrency errors: {errors}"
        assert len(results) == concurrency

        # All threads must report the exact same path and SHA-256
        for path, sha, is_dedup in results:
            assert sha == expected_sha
            assert path.is_file()

        # The final file on disk must be complete and uncorrupted
        canonical_path = results[0][0]
        assert canonical_path.stat().st_size == len(payload_chunk)
        assert canonical_path.read_bytes() == payload_chunk

        # Parent directory must contain ONLY the single canonical file (0 leftover .tmp files)
        leftover_tmp = [f for f in canonical_path.parent.iterdir() if f.name.endswith(".tmp")]
        assert len(leftover_tmp) == 0

    def test_concurrent_distinct_content_writes(self, tmp_path: Path):
        """50 concurrent threads storing 50 distinct payloads under the same profile."""
        user_id = "user_concurrent_distinct"
        profile_id = "prof_concurrent_distinct"
        concurrency = 50

        results: List[Tuple[Path, str, bool]] = []
        errors: List[Exception] = []

        def worker_task(idx: int):
            try:
                unique_payload = f"Unique patient file data for record #{idx}: {uuid.uuid4().hex}".encode("utf-8")
                res = store_cas_file(unique_payload, tmp_path, user_id, profile_id)
                results.append(res)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker_task, i) for i in range(concurrency)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0
        assert len(results) == concurrency

        # All 50 files must exist and be distinct
        stored_paths = {r[0] for r in results}
        assert len(stored_paths) == concurrency

        for path, sha, _ in results:
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == sha

        # Zero leftover .tmp files
        parent_dir = tmp_path / "data" / "files" / user_id / profile_id
        leftover_tmp = [f for f in parent_dir.iterdir() if f.name.endswith(".tmp")]
        assert len(leftover_tmp) == 0

    def test_concurrent_readers_and_writers_atomic_integrity(self, tmp_path: Path):
        """Concurrent readers must NEVER observe a partially-written or corrupt file.

        20 writer threads repeatedly saving/rewriting payload while 20 reader threads
        continuously read and verify checksum integrity.
        """
        payload = b"GENOMIC_SEQUENCE_ANALYSIS_DATA_FRAGMENT_" * 5000  # ~200 KB
        expected_sha = hashlib.sha256(payload).hexdigest()
        user_id = "user_rw_stress"
        profile_id = "prof_rw_stress"

        stop_event = threading.Event()
        reader_errors: List[str] = []
        writer_errors: List[str] = []
        successful_reads = [0]
        successful_writes = [0]

        def writer_loop():
            while not stop_event.is_set():
                try:
                    # Write payload
                    store_cas_file(payload, tmp_path, user_id, profile_id)
                    successful_writes[0] += 1
                except Exception as e:
                    writer_errors.append(f"Writer error: {e}")
                time.sleep(0.001)

        def reader_loop():
            while not stop_event.is_set():
                try:
                    data = read_cas_file(tmp_path, user_id, profile_id, expected_sha)
                    if len(data) != len(payload):
                        reader_errors.append(f"Partial read! Got {len(data)} bytes, expected {len(payload)}")
                    if hashlib.sha256(data).hexdigest() != expected_sha:
                        reader_errors.append("Corrupt checksum observed during read!")
                    successful_reads[0] += 1
                except FileNotFoundError:
                    # Permissible before first write completes
                    pass
                except Exception as e:
                    reader_errors.append(f"Reader error: {e}")
                time.sleep(0.001)

        # Pre-seed one write
        store_cas_file(payload, tmp_path, user_id, profile_id)

        # Launch 10 writers and 10 readers
        threads = []
        for _ in range(10):
            threads.append(threading.Thread(target=writer_loop))
        for _ in range(10):
            threads.append(threading.Thread(target=reader_loop))

        for t in threads:
            t.start()

        # Let the stress test run for 1 second under high contention
        time.sleep(1.0)
        stop_event.set()

        for t in threads:
            t.join()

        assert len(writer_errors) == 0, f"Writer errors encountered: {writer_errors}"
        assert len(reader_errors) == 0, f"Atomic read violations encountered: {reader_errors}"
        assert successful_reads[0] > 10, f"Expected active reads, got {successful_reads[0]}"
        assert successful_writes[0] > 10, f"Expected active writes, got {successful_writes[0]}"


# ============================================================================
# 7. ADVERSARIAL EDGE CASES & INTEGRITY PHENOMENA
# ============================================================================

class TestCasAdversarialEdgeCases:
    """Explores boundary conditions, hash verification, and deduplication lifecycle."""

    def test_store_with_mismatched_sha256_argument_empirical(self, tmp_path: Path):
        """Empirically observes whether store_cas_file validates sha256_hash against content.

        Observation: If caller explicitly passes a sha256_hash that does not match content,
        store_cas_file accepts the provided argument without re-computing or cross-validating.
        """
        real_content = b"Authentic Clinical Blood Panel"
        true_sha = hashlib.sha256(real_content).hexdigest()
        bogus_sha = "0" * 64

        path, returned_sha, dedup = store_cas_file(
            real_content,
            tmp_path,
            "u_bogus",
            "p_bogus",
            sha256_hash=bogus_sha,
        )

        assert returned_sha == bogus_sha
        assert path.name == bogus_sha
        # Content on disk is the real content, but stored under a mismatched hash
        assert path.read_bytes() == real_content
        assert hashlib.sha256(path.read_bytes()).hexdigest() != bogus_sha
        assert hashlib.sha256(path.read_bytes()).hexdigest() == true_sha

    def test_bitrot_same_length_tampering_dedup_behavior(self, tmp_path: Path):
        """Empirically observes deduplication behavior when disk file has same size but altered content.

        Observation: store_cas_file relies on stat().st_size == len(content) as a fast-path
        heuristic for deduplication. If a file of the same length exists on disk with altered bytes,
        it reports a deduplication hit without re-hashing the disk content.
        """
        original_content = b"Original Patient Allergy: Amoxicillin (38 bytes)"
        expected_sha = hashlib.sha256(original_content).hexdigest()
        canonical_path = get_cas_path(tmp_path, "u_bitrot", "p_bitrot", expected_sha)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)

        # Pre-seed disk file with altered content of the EXACT SAME length
        tampered_bytes = b"TAMPERED Patient Allergy: None Known  (38 bytes)"
        assert len(tampered_bytes) == len(original_content)
        canonical_path.write_bytes(tampered_bytes)

        # Call store_cas_file
        path, returned_sha, dedup = store_cas_file(original_content, tmp_path, "u_bitrot", "p_bitrot")

        # Because st_size matches len(original_content), dedup is True (heuristic hit)
        assert dedup is True
        # The disk file remains the tampered content because write was skipped
        assert path.read_bytes() == tampered_bytes

    def test_api_deduplicated_attachment_deletion_shared_cas(self, client, tmp_path: Path):
        """Empirically observe whether deleting one duplicate attachment unlinks the shared CAS file.

        Observation: When two attachments share the same CAS hash under the same profile, deleting
        the first attachment unlinks the CAS file on disk without checking for other DB records.
        However, the download of the second attachment still succeeds via StoragePort fallback.
        """
        import io
        from carefold.config import settings

        payload = b"Shared Deduplicated Clinical Note Between Documents"

        # 1. Upload doc 1
        res1 = client.post(
            "/api/attachments",
            files={"file": ("doc1.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res1.status_code == 201
        data1 = res1.json()
        att1_id = data1["id"]
        sha = data1["sha256"]
        assert data1["is_deduplicated"] is False

        # 2. Upload doc 2 with identical payload
        res2 = client.post(
            "/api/attachments",
            files={"file": ("doc2.txt", io.BytesIO(payload), "text/plain")},
        )
        assert res2.status_code == 201
        data2 = res2.json()
        att2_id = data2["id"]
        assert data2["is_deduplicated"] is True

        # 3. Verify CAS file exists
        assert cas_file_exists(settings.home_dir, data1.get("user_id"), data1.get("profile_id"), sha)

        # 4. Delete doc 1
        del_res = client.delete(f"/api/attachments/{att1_id}")
        assert del_res.status_code == 200

        # 5. Check physical CAS file state:
        # Reference counting preserves the shared CAS file because doc2 still references it
        cas_survived = cas_file_exists(settings.home_dir, data1.get("user_id"), data1.get("profile_id"), sha)
        assert cas_survived is True, "CAS file must be retained while doc2 still references it"

        # 6. Verify doc 2 download succeeds cleanly with 200 OK
        dl2_res = client.get(f"/api/attachments/{att2_id}/download")
        assert dl2_res.status_code == 200
        assert dl2_res.content == payload
        assert dl2_res.headers["content-length"] == str(len(payload))

