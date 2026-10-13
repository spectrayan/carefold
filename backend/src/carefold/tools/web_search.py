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

"""Sandboxed Web Search Tool & Outbound PHI Query Sanitiser (AU-37 / E9.1).

Enforces:
- Outbound PHI/PII query stripping (profile names, household names, DOB, dates,
  SSN, MRN, phone numbers, email addresses, street addresses, and ZIP+4 codes).
- Fail-closed blocking when a query is empty or contains only PHI/PII (< 3 chars remain).
- Host allowlist verification (`DEFAULT_ALLOWED_SEARCH_HOSTS`) before any network I/O.
- Preview-before-send payload generation (`preview_only=True`).
- HTML tag stripping, 400-character snippet truncation, `"trust": "untrusted"` tagging,
  and monotone taint propagation on `ToolContext`.
"""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from carefold.db.models import Profile
from carefold.db.session import get_session_factory
from carefold.engine.tool_exec import EgressBlockedError

logger = logging.getLogger("carefold.tools.web_search")

DEFAULT_ALLOWED_SEARCH_HOSTS: Tuple[str, ...] = (
    "api.search.brave.com",
    "localhost",
    "127.0.0.1",
    "searx.be",
)

MAX_SNIPPET_LENGTH: int = 400

# Precompiled PHI/PII patterns for search query sanitization
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN_LABELED_RE = re.compile(
    r"(?i)(?:\b(?:ssn|social\s*security(?:\s*number)?|soc\s*sec)\b[:\s#-]*)\d{3}[-\s.]?\d{2}[-\s.]?\d{4}\b"
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_SSN_NINE_DIGIT_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")
_MRN_RE = re.compile(
    r"(?i)\b(?:mrn|medical\s*record(?:\s*number|\s*no\.?)?)[:\s#-]*[A-Z0-9][A-Z0-9-]{2,}\b"
)
_DATE_ISO_RE = re.compile(r"\b(?:dob[:\s#-]*)?\d{4}[-/]\d{2}[-/]\d{2}\b", re.IGNORECASE)
_DATE_US_RE = re.compile(r"\b(?:dob[:\s#-]*)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?i)(?:\b(?:phone|tel|telephone|cell|mobile)\b[:\s#-]*)?"
    r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\b\d{3})[\s.-]\d{3}[\s.-]\d{4}\b"
)
_STREET_ADDRESS_RE = re.compile(
    r"(?i)(?:\b(?:address|addr)\b[:\s#-]*)?"
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.\-]+\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b\.?"
)
_ZIP_PLUS_4_RE = re.compile(r"\b\d{5}-\d{4}\b")
_ZIP_LABELED_RE = re.compile(r"(?i)\b(?:zip(?:\s*code)?|postal(?:\s*code)?)[:\s#-]*\d{5}(?:-\d{4})?\b")
_STANDALONE_PHI_LABELS_RE = re.compile(
    r"(?i)\b(?:ssn|mrn|dob|date\s+of\s+birth|social\s+security)\b[:\s#-]*"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Common clinical/medical/query words that should not be accidentally stripped as name tokens
_PROTECTED_CLINICAL_TOKENS = frozenset({
    "in", "on", "at", "to", "for", "of", "by", "or", "and", "the", "is", "as",
    "mg", "ml", "dl", "bp", "hr", "er", "ct", "iv", "gi", "cv", "rx", "dr",
})


def strip_html_tags(text: str) -> str:
    """Strips HTML tags and unescapes HTML entities from untrusted web snippets."""
    if not text:
        return ""
    without_tags = _HTML_TAG_RE.sub("", str(text))
    unescaped = html.unescape(without_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def sanitize_search_query(
    query: str,
    profile_names: Optional[Sequence[str]] = None,
    profile_dob: Optional[str] = None,
) -> Dict[str, Any]:
    """Strips patient PHI/PII from an outbound web search query and fails closed if unsafe.

    Args:
        query: Raw search query string proposed by an agent or user.
        profile_names: Optional sequence of profile and household member names.
        profile_dob: Optional exact profile date of birth string (e.g. 'YYYY-MM-DD').

    Returns:
        Dictionary containing:
        - original_query: Raw input query
        - sanitized_query: Cleaned query with PHI removed
        - redacted_items: List of redacted PHI substrings
        - is_safe: Boolean (True if len(sanitized_query) >= 3)

    Raises:
        ValueError: If fewer than 3 non-redacted characters remain after sanitization.
    """
    raw_query = "" if query is None else str(query)
    working = raw_query
    redacted_items: List[str] = []

    def _sub_and_record(pattern: re.Pattern[str], text: str) -> str:
        def _repl(match: re.Match[str]) -> str:
            val = match.group(0).strip()
            if val:
                redacted_items.append(val)
            return " [REDACTED] "

        return pattern.sub(_repl, text)

    # 1. Exact profile_dob match (if provided)
    if profile_dob and str(profile_dob).strip():
        dob_clean = str(profile_dob).strip()
        dob_pat = re.compile(rf"(?i)(?:\bdob[:\s#-]*)?{re.escape(dob_clean)}")
        working = _sub_and_record(dob_pat, working)

    # 2. Profile and household member names (full names first, then individual tokens >= 2 chars)
    if profile_names:
        full_names: List[str] = []
        name_tokens: List[str] = []
        for raw_name in profile_names:
            if not raw_name or not str(raw_name).strip():
                continue
            clean_name = str(raw_name).strip()
            full_names.append(clean_name)
            for tok in re.split(r"[\s,._-]+", clean_name):
                tok_clean = tok.strip()
                if len(tok_clean) >= 2 and tok_clean.lower() not in _PROTECTED_CLINICAL_TOKENS:
                    name_tokens.append(tok_clean)

        # Sort longest first so full names match before sub-tokens
        for fname in sorted(set(full_names), key=len, reverse=True):
            if len(fname) >= 2 and fname.lower() not in _PROTECTED_CLINICAL_TOKENS:
                pat = re.compile(rf"(?i)\b{re.escape(fname)}(?:'s)?\b")
                working = _sub_and_record(pat, working)

        for tok in sorted(set(name_tokens), key=len, reverse=True):
            pat = re.compile(rf"(?i)\b{re.escape(tok)}(?:'s)?\b")
            working = _sub_and_record(pat, working)

    # 3. Date patterns (YYYY-MM-DD, MM/DD/YYYY, MM-DD-YYYY)
    working = _sub_and_record(_DATE_ISO_RE, working)
    working = _sub_and_record(_DATE_US_RE, working)

    # 4. SSNs, MRNs, Phone numbers, Emails, Street addresses, ZIP+4
    working = _sub_and_record(_EMAIL_RE, working)
    working = _sub_and_record(_SSN_LABELED_RE, working)
    working = _sub_and_record(_SSN_RE, working)
    working = _sub_and_record(_SSN_NINE_DIGIT_RE, working)
    working = _sub_and_record(_MRN_RE, working)
    working = _sub_and_record(_PHONE_RE, working)
    working = _sub_and_record(_STREET_ADDRESS_RE, working)
    working = _sub_and_record(_ZIP_LABELED_RE, working)
    working = _sub_and_record(_ZIP_PLUS_4_RE, working)

    # Strip leftover standalone PHI labels (e.g., "SSN:", "MRN:", "DOB:")
    working = _STANDALONE_PHI_LABELS_RE.sub(" ", working)

    # Remove [REDACTED] markers and collapse whitespace / stray punctuation
    cleaned = re.sub(r"\[REDACTED\]", " ", working, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(" ,;:-/\\|")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Check meaningful alphanumeric character count
    alnum_chars = re.sub(r"[^A-Za-z0-9]", "", cleaned)
    is_safe = len(cleaned) >= 3 and len(alnum_chars) >= 3

    if not is_safe:
        raise ValueError(
            "Search query blocked: query is empty or contains only PHI/PII after sanitization."
        )

    return {
        "original_query": raw_query,
        "sanitized_query": cleaned,
        "redacted_items": redacted_items,
        "is_safe": True,
    }


async def _load_profile_phi_context(
    profile_id: str,
    user_id: Optional[str] = None,
    session_factory: Any = None,
) -> Tuple[List[str], Optional[str]]:
    """Loads profile name, household names, and DOB from database when available."""
    names: List[str] = []
    dob: Optional[str] = None
    try:
        factory = session_factory or get_session_factory()
        async with factory() as session:
            stmt = select(Profile).where(Profile.id == profile_id)
            res = await session.execute(stmt)
            profile = res.scalar_one_or_none()
            if profile is not None:
                if profile.name:
                    names.append(profile.name)
                if getattr(profile, "short_name", None):
                    names.append(profile.short_name)
                if profile.date_of_birth:
                    dob = profile.date_of_birth
                owner_uid = user_id or profile.user_id
                if owner_uid:
                    h_stmt = select(Profile).where(Profile.user_id == owner_uid)
                    h_res = await session.execute(h_stmt)
                    for member in h_res.scalars().all():
                        if member.name and member.name not in names:
                            names.append(member.name)
                        if getattr(member, "short_name", None) and member.short_name not in names:
                            names.append(member.short_name)
    except Exception as exc:
        logger.debug("Could not load profile PHI context from DB (using inline context): %s", exc)
    return names, dob


def _resolve_provider_and_url(args: Dict[str, Any]) -> Tuple[str, str, str]:
    """Resolves search provider, target URL, and verifies host against allowlist."""
    provider = str(args.get("provider") or os.getenv("CAREFOLD_SEARCH_PROVIDER", "searxng")).strip().lower()
    if provider not in ("searxng", "brave"):
        raise ValueError(f"Unsupported search provider '{provider}'. Supported: 'searxng', 'brave'.")

    explicit_url = args.get("url") or args.get("endpoint") or args.get("base_url")
    if explicit_url and str(explicit_url).strip():
        target_url = str(explicit_url).strip()
    elif provider == "brave":
        target_url = os.getenv(
            "CAREFOLD_BRAVE_SEARCH_URL",
            "https://api.search.brave.com/res/v1/web/search",
        )
    else:
        base_searx = os.getenv("CAREFOLD_SEARXNG_URL", "https://searx.be").strip().rstrip("/")
        target_url = base_searx if base_searx.endswith("/search") else f"{base_searx}/search"

    parsed = urlparse(target_url if "://" in target_url else f"https://{target_url}")
    target_host = (parsed.hostname or "").strip().lower()

    allowed = set(h.lower() for h in DEFAULT_ALLOWED_SEARCH_HOSTS)
    env_hosts = os.getenv("CAREFOLD_ALLOWED_SEARCH_HOSTS", "")
    if env_hosts.strip():
        for h in env_hosts.split(","):
            if h.strip():
                allowed.add(h.strip().lower())

    if not target_host or target_host not in allowed:
        raise EgressBlockedError(
            f"Outbound search request to host '{target_host}' blocked by allowlist policy.",
            host=target_host,
            tool="web_search",
        )

    return provider, target_url, target_host


async def _fetch_search_results(
    provider: str,
    target_url: str,
    sanitized_query: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Performs HTTP GET against the allowlisted search provider."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    params: Dict[str, Any] = {"q": sanitized_query}

    if provider == "brave":
        api_key = os.getenv("CAREFOLD_BRAVE_API_KEY") or os.getenv("BRAVE_API_KEY") or ""
        if api_key:
            headers["X-Subscription-Token"] = api_key
        params["count"] = max_results
    else:
        params["format"] = "json"

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        response = await client.get(target_url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

    if provider == "brave":
        raw_items = (payload.get("web") or {}).get("results") or payload.get("results") or []
    else:
        raw_items = payload.get("results") or []

    return list(raw_items)[:max_results]


def _normalize_search_hits(raw_items: Sequence[Dict[str, Any]], max_results: int = 5) -> List[Dict[str, Any]]:
    """Strips HTML tags, truncates snippets to 400 chars, and tags every hit as untrusted."""
    normalized: List[Dict[str, Any]] = []
    for item in list(raw_items)[:max_results]:
        if not isinstance(item, dict):
            continue
        raw_title = str(item.get("title") or "")
        raw_snippet = str(item.get("snippet") or item.get("content") or item.get("description") or "")
        raw_url = str(item.get("url") or item.get("link") or "")

        clean_title = strip_html_tags(raw_title)
        clean_snippet = strip_html_tags(raw_snippet)
        if len(clean_snippet) > MAX_SNIPPET_LENGTH:
            clean_snippet = clean_snippet[:MAX_SNIPPET_LENGTH]

        normalized.append({
            "title": clean_title,
            "url": raw_url,
            "snippet": clean_snippet,
            "trust": "untrusted",
        })
    return normalized


def _mark_context_tainted(ctx: Any) -> None:
    """Propagates monotone taint flag onto ToolContext."""
    if ctx is None:
        return
    taint_obj = getattr(ctx, "taint", None)
    if taint_obj is not None and hasattr(taint_obj, "set"):
        taint_obj.set()
    else:
        try:
            object.__setattr__(ctx, "taint", True)
        except Exception:
            pass


async def execute_web_search(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Executes sandboxed, PHI-sanitized web search with host allowlisting and taint tracking.

    Args:
        args: Tool input dictionary (`query`, optional `provider`, `preview_only`, `max_results`).
        ctx: ToolContext (must contain non-empty `profile_id`).

    Returns:
        Dictionary containing sanitized query, redacted items, and untrusted results (or preview card).
    """
    # 1. Fail-closed context check
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if ctx is None or not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError(
            "Security violation: ToolContext with a non-empty 'profile_id' is required for web_search."
        )
    clean_profile_id = profile_id.strip()
    user_id = getattr(ctx, "user_id", None)

    if not isinstance(args, dict):
        raise ValueError("Search arguments must be a dictionary.")

    raw_query = str(args.get("query") or "")

    # 2. Verify provider and target host allowlist before any network activity
    provider, target_url, target_host = _resolve_provider_and_url(args)

    # 3. Collect profile PHI context (names + DOB) from DB and optional context/args
    session_factory = getattr(ctx, "session_factory", None) or (
        ctx.extra.get("session_factory") if isinstance(getattr(ctx, "extra", None), dict) else None
    )
    db_names, db_dob = await _load_profile_phi_context(
        clean_profile_id,
        user_id=user_id,
        session_factory=session_factory,
    )

    extra_names = list(args.get("profile_names") or [])
    ctx_extra = getattr(ctx, "extra", None)
    if isinstance(ctx_extra, dict) and ctx_extra.get("profile_names"):
        extra_names.extend(ctx_extra["profile_names"])
    if getattr(ctx, "profile_name", None):
        extra_names.append(str(getattr(ctx, "profile_name")))

    all_names = list(dict.fromkeys([*db_names, *extra_names]))
    effective_dob = (
        args.get("profile_dob")
        or (ctx_extra.get("profile_dob") if isinstance(ctx_extra, dict) else None)
        or getattr(ctx, "profile_dob", None)
        or db_dob
    )

    # 4. Sanitize search query (fails closed with ValueError if < 3 chars remain)
    sanitized = sanitize_search_query(
        raw_query,
        profile_names=all_names,
        profile_dob=effective_dob,
    )
    sanitized_query = sanitized["sanitized_query"]
    redacted_items = sanitized["redacted_items"]

    # 5. Preview-before-send card support
    preview_only = bool(args.get("preview_only", False))
    if preview_only:
        return {
            "type": "web_search_preview",
            "original_query": raw_query,
            "sanitized_query": sanitized_query,
            "provider": provider,
            "target_host": target_host,
            "redacted_items": redacted_items,
            "trust": "untrusted",
        }

    # 6. Execute outbound search request
    try:
        max_results = max(1, min(int(args.get("max_results", 5)), 20))
    except (TypeError, ValueError):
        max_results = 5

    raw_hits = await _fetch_search_results(
        provider=provider,
        target_url=target_url,
        sanitized_query=sanitized_query,
        max_results=max_results,
    )
    cleaned_hits = _normalize_search_hits(raw_hits, max_results=max_results)

    # 7. Monotone taint escalation on ToolContext
    _mark_context_tainted(ctx)

    return {
        "query": raw_query,
        "sanitized_query": sanitized_query,
        "redacted_items": redacted_items,
        "provider": provider,
        "target_host": target_host,
        "results": cleaned_hits,
        "trust": "untrusted",
    }


__all__ = [
    "DEFAULT_ALLOWED_SEARCH_HOSTS",
    "MAX_SNIPPET_LENGTH",
    "execute_web_search",
    "sanitize_search_query",
    "strip_html_tags",
]
