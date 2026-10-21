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
from carefold.scope.context import DEFAULT_SCOPE

logger = get_logger("carefold.storage.cas")

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
DANGEROUS_CHARS_REGEX = re.compile(r"[^a-zA-Z0-9._-]")


SINGLE_USER_PARTITION = "default"
"""User partition used only in local single-user mode (auth disabled)."""

UNSCOPED_PROFILE_PARTITION = "default"
"""Profile partition for files not tied to a profile, inside the owner's own partition."""


class CasPartitionError(ValueError):
    """Raised when a CAS partition cannot be resolved safely (fail-closed)."""


def sanitize_partition_segment(segment: Optional[str], default: Optional[str] = None) -> str:
    """Sanitizes a user, profile or scope identifier to ensure sandbox containment.

    A missing or empty identifier is only replaced when the caller passes an
    explicit ``default``; otherwise it is rejected so that no request is
    silently routed into a shared bucket.
    """
    if not segment or not str(segment).strip():
        if default is None:
            raise CasPartitionError("Missing CAS partition identifier (fail-closed).")
        return default
    raw = str(segment).strip()
    if "/" in raw or "\\" in raw or "\0" in raw or ".." in raw:
        raise ValueError(f"Invalid partition identifier containing traversal sequences: '{segment}'")
    cleaned = DANGEROUS_CHARS_REGEX.sub("_", raw)
    if cleaned in ("", ".", ".."):
        if default is None:
            raise CasPartitionError(f"Invalid CAS partition identifier: '{segment}'")
        return default
    return cleaned


def _single_user_mode() -> bool:
    from carefold.config import settings

    return str(getattr(settings, "auth_provider", "local") or "local").strip().lower() == "disabled"


def resolve_user_partition(user_id: Optional[str]) -> str:
    """Resolves the per-user CAS partition.

    Without a user id the shared single-user partition is only used when
    authentication is disabled (one local steward owns all data). In
    multi-user mode a missing user id is refused instead of falling back to
    a bucket other users could also resolve to.
    """
    if user_id is not None and str(user_id).strip():
        return sanitize_partition_segment(user_id)
    if _single_user_mode():
        return SINGLE_USER_PARTITION
    raise CasPartitionError("CAS access without a user id is refused in multi-user mode (fail-closed).")


def get_cas_path(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Path:
    """Computes the canonical Content-Addressed Storage path for an attachment.

    Hierarchy:
        <carefold_home>/data/files/<user_id>/<profile_id>/<scope>/<sha256>
    or legacy (when scope is None):
        <carefold_home>/data/files/<user_id>/<profile_id>/<sha256>
    """
    clean_uid = resolve_user_partition(user_id)
    clean_pid = sanitize_partition_segment(profile_id, default=UNSCOPED_PROFILE_PARTITION)
    clean_hash = str(sha256_hash).strip().lower()

    if not SHA256_HEX_REGEX.match(clean_hash):
        raise ValueError(f"Invalid SHA-256 digest format: '{sha256_hash}'")

    if scope is None:
        return carefold_home.resolve() / "data" / "files" / clean_uid / clean_pid / clean_hash

    clean_scope = sanitize_partition_segment(scope, default=DEFAULT_SCOPE)
    return carefold_home.resolve() / "data" / "files" / clean_uid / clean_pid / clean_scope / clean_hash


def resolve_cas_path(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Path:
    """Resolves existing CAS file with fallback to legacy path for default scope."""
    scoped_path = get_cas_path(carefold_home, user_id, profile_id, sha256_hash, scope=scope)
    if scoped_path.is_file():
        return scoped_path

    # Fallback to legacy path for default domain
    if scope is None or scope == DEFAULT_SCOPE or scope.startswith(f"{DEFAULT_SCOPE}."):
        legacy_path = get_cas_path(carefold_home, user_id, profile_id, sha256_hash, scope=None)
        if legacy_path.is_file():
            return legacy_path

    return scoped_path


def cas_file_exists(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> bool:
    """Checks whether the specified content-addressed file exists on disk."""
    try:
        path = resolve_cas_path(carefold_home, user_id, profile_id, sha256_hash, scope=scope)
        return path.is_file()
    except ValueError:
        return False


def store_cas_file(
    content: bytes,
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: Optional[str] = None,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Tuple[Path, str, bool]:
    """Stores content in canonical CAS layout with per-profile, per-scope deduplication.

    Returns:
        Tuple of (canonical_path, sha256_digest, is_deduplicated).
    """
    if sha256_hash is None:
        computed_hash = hashlib.sha256(content).hexdigest().lower()
    else:
        computed_hash = str(sha256_hash).strip().lower()

    canonical_path = get_cas_path(carefold_home, user_id, profile_id, computed_hash, scope=scope)

    # Scoped deduplication: if exact CAS file exists within this scope partition, skip rewrite
    if canonical_path.is_file() and canonical_path.stat().st_size == len(content):
        logger.debug(
            "cas_deduplication_hit",
            path=str(canonical_path),
            sha256=computed_hash[:8],
            user_id=user_id,
            profile_id=profile_id,
            scope=scope,
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
        scope=scope,
    )
    return canonical_path, computed_hash, False


def read_cas_file(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> bytes:
    """Reads content from CAS storage, raising FileNotFoundError if missing."""
    canonical_path = resolve_cas_path(carefold_home, user_id, profile_id, sha256_hash, scope=scope)
    if not canonical_path.is_file():
        raise FileNotFoundError(f"CAS file '{sha256_hash}' not found at {canonical_path}")
    return canonical_path.read_bytes()


__all__ = [
    "CasPartitionError",
    "SINGLE_USER_PARTITION",
    "UNSCOPED_PROFILE_PARTITION",
    "resolve_user_partition",
    "get_cas_path",
    "resolve_cas_path",
    "cas_file_exists",
    "store_cas_file",
    "read_cas_file",
    "sanitize_partition_segment",
]
