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

"""CAS partitioning fails closed: no shared bucket for requests without an owner."""

from __future__ import annotations

from pathlib import Path

import pytest

from carefold.config import settings
from carefold.storage.cas import (
    SINGLE_USER_PARTITION,
    CasPartitionError,
    get_cas_path,
    read_cas_file,
    resolve_user_partition,
    sanitize_partition_segment,
    store_cas_file,
)

DIGEST = "a" * 64


def test_missing_segment_without_explicit_default_is_rejected() -> None:
    with pytest.raises(CasPartitionError):
        sanitize_partition_segment(None)
    with pytest.raises(CasPartitionError):
        sanitize_partition_segment("   ")
    assert sanitize_partition_segment(None, default="default") == "default"


def test_multi_user_mode_refuses_ownerless_cas_access(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "auth_provider", "local")
    with pytest.raises(CasPartitionError):
        resolve_user_partition(None)
    with pytest.raises(CasPartitionError):
        get_cas_path(tmp_path, None, "prof-1", DIGEST)
    with pytest.raises(CasPartitionError):
        store_cas_file(b"secret", carefold_home=tmp_path, user_id=None, profile_id="prof-1")

    # A file planted in the single-user bucket is not reachable without an owner.
    shared = tmp_path / "data" / "files" / SINGLE_USER_PARTITION / "prof-1"
    shared.mkdir(parents=True)
    with pytest.raises(CasPartitionError):
        read_cas_file(carefold_home=tmp_path, user_id=None, profile_id="prof-1", sha256_hash=DIGEST)


def test_users_are_isolated_and_profileless_files_stay_in_owner_partition(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "auth_provider", "local")
    path_a, digest, _ = store_cas_file(b"alpha", carefold_home=tmp_path, user_id="user-a", profile_id=None)
    assert path_a.relative_to(tmp_path.resolve()).parts[:3] == ("data", "files", "user-a")
    with pytest.raises(FileNotFoundError):
        read_cas_file(carefold_home=tmp_path, user_id="user-b", profile_id=None, sha256_hash=digest)
    assert read_cas_file(carefold_home=tmp_path, user_id="user-a", profile_id=None, sha256_hash=digest) == b"alpha"


def test_single_user_mode_keeps_local_steward_partition(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "auth_provider", "disabled")
    assert resolve_user_partition(None) == SINGLE_USER_PARTITION
    path, digest, _ = store_cas_file(b"local", carefold_home=tmp_path, user_id=None, profile_id="prof-1")
    assert SINGLE_USER_PARTITION in path.parts
    assert read_cas_file(carefold_home=tmp_path, user_id=None, profile_id="prof-1", sha256_hash=digest) == b"local"
