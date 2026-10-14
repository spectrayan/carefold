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

"""Unit and integration tests for Sandboxed Web Search & PHI Query Sanitiser (AU-37 / E9.1)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from carefold.db.base import Base
from carefold.db.models import Profile, User
from carefold.engine.tool_exec import EgressBlockedError, TaintFlag, ToolContext
from carefold.tools.web_search import (
    DEFAULT_ALLOWED_SEARCH_HOSTS,
    MAX_SNIPPET_LENGTH,
    execute_web_search,
    sanitize_search_query,
)


@pytest.fixture
async def db_session_factory():
    """Provides an in-memory SQLite async session factory for profile PHI lookups."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_sanitize_search_query_strips_names_and_dob():
    """Verifies profile names, individual name tokens, and DOB are stripped while clinical terms remain."""
    raw = "Maya Patel 1988-11-23 lisinopril 10mg cough side effects"
    result = sanitize_search_query(
        raw,
        profile_names=["Maya Patel", "Leo Patel"],
        profile_dob="1988-11-23",
    )
    assert result["is_safe"] is True
    sanitized = result["sanitized_query"]
    assert "Maya" not in sanitized
    assert "Patel" not in sanitized
    assert "1988-11-23" not in sanitized
    assert "lisinopril 10mg cough side effects" in sanitized
    assert len(result["redacted_items"]) >= 2


def test_sanitize_search_query_strips_ssn_mrn_phone_email_address_zip():
    """Verifies SSN, MRN, phone, email, street address, dates, and ZIP+4 are removed."""
    raw = (
        "SSN 123-45-6789 MRN: AB-998877 phone (555) 234-5678 "
        "maya.patel@example.com 742 Evergreen Street 62704-1234 "
        "04/15/1990 metformin lactic acidosis risk"
    )
    result = sanitize_search_query(raw)
    sanitized = result["sanitized_query"]
    assert "123-45-6789" not in sanitized
    assert "998877" not in sanitized
    assert "234-5678" not in sanitized
    assert "maya.patel@example.com" not in sanitized
    assert "742 Evergreen Street" not in sanitized
    assert "62704-1234" not in sanitized
    assert "04/15/1990" not in sanitized
    assert "metformin lactic acidosis risk" in sanitized
    assert result["is_safe"] is True


def test_sanitize_search_query_fails_closed_when_only_phi():
    """Verifies ValueError is raised when query is empty or contains only PHI/PII after sanitization."""
    with pytest.raises(ValueError, match="Search query blocked"):
        sanitize_search_query(
            "John Doe 1985-04-12 SSN 123-45-6789 MRN-44912",
            profile_names=["John Doe"],
            profile_dob="1985-04-12",
        )

    with pytest.raises(ValueError, match="Search query blocked"):
        sanitize_search_query("   ")


@pytest.mark.asyncio
async def test_execute_web_search_fails_closed_without_profile_context():
    """Verifies execute_web_search rejects missing ctx or empty profile_id."""
    with pytest.raises(ValueError, match="profile_id"):
        await execute_web_search({"query": "atorvastatin muscle pain"}, ctx=None)

    empty_ctx = SimpleNamespace(profile_id="", user_id="u-1")
    with pytest.raises(ValueError, match="profile_id"):
        await execute_web_search({"query": "atorvastatin muscle pain"}, ctx=empty_ctx)


@pytest.mark.asyncio
async def test_execute_web_search_blocks_disallowed_host():
    """Verifies PermissionError (EgressBlockedError) is raised if target URL host is not allowlisted."""
    ctx = ToolContext(user_id="user-1", profile_id="prof-1")
    with pytest.raises(PermissionError) as exc_info:
        await execute_web_search(
            {
                "query": "hypertension dietary guidelines",
                "provider": "searxng",
                "url": "https://untrusted-tracker.example.org/search",
            },
            ctx=ctx,
        )
    assert isinstance(exc_info.value, EgressBlockedError)
    assert "api.search.brave.com" in DEFAULT_ALLOWED_SEARCH_HOSTS


@pytest.mark.asyncio
async def test_execute_web_search_preview_only_loads_db_profile_phi(db_session_factory):
    """Verifies preview_only=True loads profile PHI from DB and returns a preview card without network I/O."""
    user_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    async with db_session_factory() as session:
        user = User(
            id=user_id,
            email="steward@example.com",
            username="steward_user",
            hashed_password="hashed_password",
        )
        profile = Profile(
            id=profile_id,
            user_id=user_id,
            name="Eleanor Vance",
            short_name="Ellie",
            date_of_birth="1979-08-14",
        )
        sibling = Profile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name="Arthur Vance",
            date_of_birth="2016-05-02",
        )
        session.add_all([user, profile, sibling])
        await session.commit()

    ctx = ToolContext(
        user_id=user_id,
        profile_id=profile_id,
        extra={"session_factory": db_session_factory},
    )

    preview = await execute_web_search(
        {
            "query": "Eleanor Vance 1979-08-14 Arthur Ellie guidelines for stage 1 hypertension",
            "provider": "brave",
            "preview_only": True,
        },
        ctx=ctx,
    )

    assert preview["type"] == "web_search_preview"
    assert preview["provider"] == "brave"
    assert preview["target_host"] == "api.search.brave.com"
    assert preview["trust"] == "untrusted"
    assert "Eleanor" not in preview["sanitized_query"]
    assert "Vance" not in preview["sanitized_query"]
    assert "Arthur" not in preview["sanitized_query"]
    assert "Ellie" not in preview["sanitized_query"]
    assert "1979-08-14" not in preview["sanitized_query"]
    assert "guidelines for stage 1 hypertension" in preview["sanitized_query"]
    # Preview mode does not execute outbound search or taint the run yet
    assert bool(ctx.taint) is False


@pytest.mark.asyncio
async def test_execute_web_search_strips_html_truncates_and_sets_taint(monkeypatch):
    """Verifies live execution strips HTML tags, truncates snippets to 400 chars, and sets taint."""
    captured_call: Dict[str, Any] = {}

    async def _fake_fetch(provider: str, target_url: str, sanitized_query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        captured_call["provider"] = provider
        captured_call["target_url"] = target_url
        captured_call["sanitized_query"] = sanitized_query
        long_body = "<b>Important</b> clinical overview: " + ("A" * 500)
        return [
            {
                "title": "<em>AHA</em> Blood Pressure <span>Guidelines</span>",
                "url": "https://www.heart.org/en/health-topics/high-blood-pressure",
                "snippet": long_body,
            }
        ]

    monkeypatch.setattr("carefold.tools.web_search._fetch_search_results", _fake_fetch)

    ctx = ToolContext(
        user_id="user-1",
        profile_id="prof-1",
        taint=TaintFlag(False),
        extra={"profile_names": ["Sarah Connor"], "profile_dob": "1984-05-12"},
    )

    res = await execute_web_search(
        {
            "query": "Sarah Connor 1984-05-12 AHA blood pressure categories",
            "provider": "searxng",
        },
        ctx=ctx,
    )

    assert captured_call["sanitized_query"] == "AHA blood pressure categories"
    assert res["trust"] == "untrusted"
    assert len(res["results"]) == 1
    hit = res["results"][0]
    assert hit["title"] == "AHA Blood Pressure Guidelines"
    assert "<b>" not in hit["snippet"]
    assert len(hit["snippet"]) == MAX_SNIPPET_LENGTH
    assert hit["trust"] == "untrusted"
    assert bool(ctx.taint) is True
    assert ctx.taint.is_tainted is True
