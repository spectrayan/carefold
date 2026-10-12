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

"""Content-Addressed Storage (CAS) engine.

Enforces storage layout:
    <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>

Provides per-profile deduplication and strictly scoped cryptographic storage.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Optional, Tuple
import uuid

from carefold.logging import get_logger

logger = get_logger("carefold.storage.cas")

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
DANGEROUS_CHARS_REGEX = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize_partition_segment(segment: Optional[str], default: str = "default") -> str:
    """Sanitizes user or profile identifiers to ensure sandbox containment."""
    if not segment or not str(segment).strip():
        return default
    raw = str(segment).strip()
    if "/" in raw or "\\" in raw or "\0" in raw or ".." in raw:
        raise ValueError(f"Invalid partition identifier containing traversal sequences: '{segment}'")
    cleaned = DANGEROUS_CHARS_REGEX.sub("_", raw)
    if cleaned in ("", ".", ".."):
        return default
    return cleaned


def get_cas_path(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
) -> Path:
    """Computes the canonical Content-Addressed Storage path for an attachment.

    Hierarchy:
        <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>
    """
    clean_uid = sanitize_partition_segment(user_id)
    clean_pid = sanitize_partition_segment(profile_id)
    clean_hash = str(sha256_hash).strip().lower()

    if not SHA256_HEX_REGEX.match(clean_hash):
        raise ValueError(f"Invalid SHA-256 digest format: '{sha256_hash}'")

    return carefold_home.resolve() / "data" / "files" / clean_uid / clean_pid / clean_hash


def cas_file_exists(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
) -> bool:
    """Checks whether the specified content-addressed file exists on disk."""
    try:
        path = get_cas_path(carefold_home, user_id, profile_id, sha256_hash)
        return path.is_file()
    except ValueError:
        return False


def store_cas_file(
    content: bytes,
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: Optional[str] = None,
) -> Tuple[Path, str, bool]:
    """Stores content in canonical CAS layout with per-profile deduplication.

    Returns:
        Tuple of (canonical_path, sha256_digest, is_deduplicated).
    """
    if sha256_hash is None:
        computed_hash = hashlib.sha256(content).hexdigest().lower()
    else:
        computed_hash = str(sha256_hash).strip().lower()

    canonical_path = get_cas_path(carefold_home, user_id, profile_id, computed_hash)

    # Per-profile deduplication: if exact CAS file exists, skip rewrite
    if canonical_path.is_file() and canonical_path.stat().st_size == len(content):
        logger.debug(
            "cas_deduplication_hit",
            path=str(canonical_path),
            sha256=computed_hash[:8],
            user_id=user_id,
            profile_id=profile_id,
        )
        return canonical_path, computed_hash, True

    # Ensure parent partition exists
    canonical_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write via temporary file
    temp_name = f".{computed_hash}.{uuid.uuid4().hex}.tmp"
    temp_path = canonical_path.parent / temp_name

    try:
        temp_path.write_bytes(content)
        os.replace(temp_path, canonical_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    logger.info(
        "cas_file_stored",
        path=str(canonical_path),
        size=len(content),
        sha256=computed_hash[:8],
        user_id=user_id,
        profile_id=profile_id,
    )
    return canonical_path, computed_hash, False


def read_cas_file(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
) -> bytes:
    """Reads content from CAS storage, raising FileNotFoundError if missing."""
    canonical_path = get_cas_path(carefold_home, user_id, profile_id, sha256_hash)
    if not canonical_path.is_file():
        raise FileNotFoundError(f"CAS file '{sha256_hash}' not found at {canonical_path}")
    return canonical_path.read_bytes()


__all__ = [
    "get_cas_path",
    "cas_file_exists",
    "store_cas_file",
    "read_cas_file",
    "sanitize_partition_segment",
]
