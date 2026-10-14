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

"""Test fixtures and harness configurations for Autonomy Batch 1 E2E suite."""

from __future__ import annotations

import os
from typing import Any, Dict, Generator, Optional
import pytest

from tests.e2e_autonomy.contracts import (
    ApprovalStore,
    InMemoryProfileKeyStore,
    JobRunner,
    TaintFlag,
    ToolContext,
    ToolSpecRegistry,
    create_default_registry,
)


@pytest.fixture
def mock_keyring() -> Dict[str, str]:
    """In-memory mock OS keychain mapping service keys to secrets."""
    return {"carefold_kek": os.urandom(32).hex()}


@pytest.fixture
def sample_kek() -> bytes:
    """Standard 32-byte (256-bit) Key Encryption Key for tests."""
    return b"\x01" * 32


@pytest.fixture
def sample_profile_id() -> str:
    return "prof-cardio-9988"


@pytest.fixture
def sample_user_id() -> str:
    return "user-alex-001"


@pytest.fixture
def sample_connection_id() -> str:
    return "conn-epic-ehr-01"


@pytest.fixture
def profile_key_store() -> InMemoryProfileKeyStore:
    return InMemoryProfileKeyStore()


@pytest.fixture
def tool_registry() -> ToolSpecRegistry:
    return create_default_registry()


@pytest.fixture
def approval_store() -> ApprovalStore:
    return ApprovalStore()


@pytest.fixture
def job_runner() -> JobRunner:
    return JobRunner()


@pytest.fixture
def make_context(sample_user_id: str, sample_profile_id: str):
    """Factory fixture for ToolContext instances."""
    def _builder(
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        autonomy: str = "A1",
        tainted: bool = False,
        principal: str = "user",
    ) -> ToolContext:
        tf = TaintFlag(initial=tainted)
        return ToolContext(
            user_id=user_id or sample_user_id,
            profile_id=profile_id or sample_profile_id,
            autonomy=autonomy,  # type: ignore
            taint=tf,
            principal=principal,  # type: ignore
        )
    return _builder
