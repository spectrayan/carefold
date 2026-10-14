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

"""Local-Only Email Drafts Service with RFC 6068 mailto: and RFC 5322 .eml Export (AU-60 / E9.3).

Carefold never sends emails automatically in v1. Agents and users prepare local drafts
that the user reviews, edits, and sends via their own email client (`mailto:` URI or
`.eml` download with `X-Unsent: 1`).
"""

from __future__ import annotations

from email.utils import format_datetime
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import AuditEventRecord, EmailDraft, utc_now
from carefold.db.session import get_session_factory

logger = logging.getLogger("carefold.clinical.email_drafts")

VALID_DRAFT_CATEGORIES = ("appointment", "school", "insurance", "general")
NO_AUTO_SEND_NOTICE = "Draft saved locally. Carefold never sends emails automatically in v1."
NON_CLINICAL_EMAIL_HEADER_NOTE = (
    "Prepared locally by Carefold as a non-clinical administrative aid. "
    "Review and verify all details before sending."
)


def _sanitize_header_value(value: Optional[str]) -> str:
    """Strips CR/LF characters to prevent RFC 5322 header injection."""
    if not value:
        return ""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split()).strip()


def build_mailto_uri(draft: EmailDraft) -> str:
    """Builds an RFC 6068 `mailto:` URI with URL-encoded subject and body."""
    recipient_clean = _sanitize_header_value(draft.recipient)
    recipient_encoded = quote(recipient_clean, safe="@._+-") if recipient_clean else ""
    subject_encoded = quote(_sanitize_header_value(draft.subject), safe="")
    body_encoded = quote(str(draft.body or ""), safe="")
    return f"mailto:{recipient_encoded}?subject={subject_encoded}&body={body_encoded}"


def export_draft_as_eml(draft: EmailDraft) -> str:
    """Formats an `EmailDraft` as an RFC 5322 `.eml` message with `X-Unsent: 1`."""
    created_dt = draft.created_at or utc_now()
    date_header = format_datetime(created_dt)
    to_header = _sanitize_header_value(draft.recipient)
    subject_header = _sanitize_header_value(draft.subject) or "Carefold Draft"
    body_text = str(draft.body or "").strip()

    lines = [
        f"Date: {date_header}",
        f"To: {to_header}",
        f"Subject: {subject_header}",
        "X-Unsent: 1",
        f"X-Carefold-Notice: {NO_AUTO_SEND_NOTICE}",
        f"X-Carefold-Disclaimer: {NON_CLINICAL_EMAIL_HEADER_NOTE}",
        "MIME-Version: 1.0",
        'Content-Type: text/plain; charset="utf-8"',
        "Content-Transfer-Encoding: 8bit",
        "",
        body_text,
        "",
        "-- ",
        f"[Note: {NON_CLINICAL_EMAIL_HEADER_NOTE}]",
    ]
    return "\r\n".join(lines) + "\r\n"


def serialize_email_draft(draft: EmailDraft) -> Dict[str, Any]:
    """Serializes an `EmailDraft` into a JSON-compatible dictionary."""
    return {
        "id": draft.id,
        "draft_id": draft.id,
        "profile_id": draft.profile_id,
        "created_by_user_id": draft.created_by_user_id,
        "recipient": draft.recipient,
        "subject": draft.subject,
        "body": draft.body,
        "category": draft.category,
        "status": draft.status,
        "mailto_uri": build_mailto_uri(draft),
        "auto_send": False,
        "notice": NO_AUTO_SEND_NOTICE,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


async def create_email_draft(
    session: AsyncSession,
    profile_id: str,
    subject: str,
    body: str,
    recipient: Optional[str] = None,
    category: str = "general",
    created_by_user_id: Optional[str] = None,
) -> EmailDraft:
    """Persists a local `EmailDraft` (`status="draft"`) and logs an `AuditEventRecord`."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required to create an email draft.")

    clean_subject = _sanitize_header_value(subject)
    if not clean_subject:
        raise ValueError("Email draft subject must not be empty.")

    clean_body = str(body or "").strip()
    if not clean_body:
        raise ValueError("Email draft body must not be empty.")

    clean_recipient = _sanitize_header_value(recipient) or None
    clean_category = (category or "general").strip().lower()
    if clean_category not in VALID_DRAFT_CATEGORIES:
        clean_category = "general"

    now = utc_now()
    draft = EmailDraft(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        created_by_user_id=created_by_user_id,
        recipient=clean_recipient,
        subject=clean_subject[:500],
        body=clean_body,
        category=clean_category,
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(draft)

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "recipient": clean_recipient,
                "subject": clean_subject[:500],
                "category": clean_category,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=created_by_user_id,
        principal="user" if created_by_user_id else "agent",
        event="tool",
        tool="create_email_draft",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"email_draft:{draft.id}",
        detail_redacted=json.dumps({
            "draft_id": draft.id,
            "category": clean_category,
            "has_recipient": bool(clean_recipient),
            "auto_send": False,
        }),
    )
    session.add(audit)

    await session.commit()
    await session.refresh(draft)
    return draft


async def list_email_drafts(
    session: AsyncSession,
    profile_id: str,
    category: Optional[str] = None,
) -> List[EmailDraft]:
    """Lists `EmailDraft` rows for `profile_id` ordered newest-first."""
    stmt = select(EmailDraft).where(EmailDraft.profile_id == profile_id.strip())
    if category and category.strip():
        stmt = stmt.where(EmailDraft.category == category.strip().lower())
    stmt = stmt.order_by(EmailDraft.created_at.desc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_email_draft(
    session: AsyncSession,
    profile_id: str,
    draft_id: str,
) -> Optional[EmailDraft]:
    """Fetches a single `EmailDraft` scoped to `profile_id`."""
    stmt = select(EmailDraft).where(
        EmailDraft.id == draft_id.strip(),
        EmailDraft.profile_id == profile_id.strip(),
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def delete_email_draft(
    session: AsyncSession,
    profile_id: str,
    draft_id: str,
) -> bool:
    """Deletes a local `EmailDraft` scoped to `profile_id`."""
    draft = await get_email_draft(session, profile_id=profile_id, draft_id=draft_id)
    if draft is None:
        return False
    await session.delete(draft)
    await session.commit()
    return True


async def execute_create_email_draft(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Tool executor (`risk_tier="write_local"`) for creating a local-only email draft.

    Enforces fail-closed `ctx.profile_id` verification and never sends email over the network.
    """
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if ctx is None or not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError(
            "Security violation: ToolContext with a non-empty 'profile_id' is required for create_email_draft."
        )

    if not isinstance(args, dict):
        raise ValueError("Arguments must be provided as a dictionary.")

    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()
    recipient = args.get("recipient") or args.get("to")
    category = str(args.get("category") or "general").strip()
    user_id = getattr(ctx, "user_id", None)

    explicit_session = args.get("session") or getattr(ctx, "session", None)
    if explicit_session is not None:
        draft = await create_email_draft(
            session=explicit_session,
            profile_id=profile_id.strip(),
            subject=subject,
            body=body,
            recipient=str(recipient) if recipient else None,
            category=category,
            created_by_user_id=user_id,
        )
    else:
        session_factory = (
            getattr(ctx, "session_factory", None)
            or (ctx.extra.get("session_factory") if isinstance(getattr(ctx, "extra", None), dict) else None)
            or get_session_factory()
        )
        async with session_factory() as session:
            draft = await create_email_draft(
                session=session,
                profile_id=profile_id.strip(),
                subject=subject,
                body=body,
                recipient=str(recipient) if recipient else None,
                category=category,
                created_by_user_id=user_id,
            )

    payload = serialize_email_draft(draft)
    payload["external_ref"] = f"email_draft:{draft.id}"
    return payload


__all__ = [
    "NON_CLINICAL_EMAIL_HEADER_NOTE",
    "NO_AUTO_SEND_NOTICE",
    "VALID_DRAFT_CATEGORIES",
    "build_mailto_uri",
    "create_email_draft",
    "delete_email_draft",
    "execute_create_email_draft",
    "export_draft_as_eml",
    "get_email_draft",
    "list_email_drafts",
    "serialize_email_draft",
]
