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

"""Closed tool: create_typed_note (AU-35).

Creates and persists a typed clinical or navigation note across 7 canonical categories
with optional appointment linking, tag categorization, search indexing, and audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select

from carefold.clinical.notes import VALID_NOTE_TYPES, validate_note_type
from carefold.db.models import Appointment, Job, Note
from carefold.db.session import get_session_factory
from carefold.schemas.tool import ToolResult

logger = logging.getLogger("carefold.tools.notes")


def _slugify(text: str) -> str:
    """Generates a URL-safe alphanumeric slug."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\s]", "", text.strip())
    slug = re.sub(r"\s+", "-", clean).lower()
    return slug[:64] or "note"


async def execute_create_typed_note(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a typed note with fail-closed security, appointment linking, and indexing."""
    # 1. Fail-closed profile verification
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_typed_note rejected: invalid or missing profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_typed_note.",
        )
    clean_profile_id = profile_id.strip()

    # 2. Parameter validation
    if not isinstance(args, dict):
        return ToolResult(
            success=False,
            output=None,
            error="Parameters must be provided as a dictionary.",
        )

    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return ToolResult(
            success=False,
            output=None,
            error="Parameters 'title' and 'content' must be non-empty strings.",
        )

    raw_type = str(args.get("type", "general")).strip()
    try:
        note_type = validate_note_type(raw_type)
    except ValueError as type_err:
        return ToolResult(
            success=False,
            output=None,
            error=str(type_err),
        )

    linked_appt_id = args.get("linked_appointment_id")
    if linked_appt_id is not None:
        linked_appt_id = str(linked_appt_id).strip() or None

    raw_tags = args.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags_list: List[str] = [
        str(t).strip().lower() for t in raw_tags if str(t).strip()
    ]

    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    base_slug = _slugify(title)
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    try:
        factory = get_session_factory()
        async with factory() as session:
            # 3. Validate appointment belongs to profile if linked
            if linked_appt_id:
                appt_stmt = select(Appointment).where(
                    Appointment.id == linked_appt_id,
                    Appointment.profile_id == clean_profile_id,
                )
                appt_res = await session.execute(appt_stmt)
                if appt_res.scalar_one_or_none() is None:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="Security violation: Linked appointment does not exist or does not belong to profile.",
                    )

            # 4. Insert Note
            new_note = Note(
                id=note_id,
                type=note_type,
                user_id=user_id,
                profile_id=clean_profile_id,
                slug=unique_slug,
                title=title,
                content=content,
                tags_json=json.dumps(tags_list),
                linked_appointment_id=linked_appt_id,
                created_at=now,
                updated_at=now,
            )
            session.add(new_note)

            # 5. Enqueue search index job (AU-27)
            content_hash = hashlib.sha256((new_note.content or "").encode("utf-8")).hexdigest()[:12]
            index_job = Job(
                id=str(uuid.uuid4()),
                profile_id=clean_profile_id,
                kind="index_doc",
                payload=json.dumps({
                    "document_id": new_note.id,
                    "profile_id": clean_profile_id,
                    "doc_type": "note",
                }),
                timezone="UTC",
                next_run_at=now,
                idempotency_key=f"index:note:{new_note.id}:{content_hash}",
                status="pending",
            )
            session.add(index_job)

            await session.commit()

            # 6. Audit Logging for Undoability
            try:
                from carefold.audit.logger import record_audit
                await record_audit(
                    {
                        "profile_id": clean_profile_id,
                        "action": "create",
                        "tool": "create_typed_note",
                        "risk": "write_local",
                        "external_ref": f"note:{new_note.id}",
                        "details": {
                            "note_id": new_note.id,
                            "title": new_note.title,
                            "type": new_note.type,
                            "linked_appointment_id": new_note.linked_appointment_id,
                        },
                    },
                    actor_user_id=user_id or "user",
                    risk="write_local",
                )
            except Exception as audit_err:
                logger.debug("Audit logging failed during typed note creation: %s", audit_err)

            return ToolResult(
                success=True,
                output={
                    "id": new_note.id,
                    "profile_id": clean_profile_id,
                    "slug": new_note.slug,
                    "title": new_note.title,
                    "type": new_note.type,
                    "content": new_note.content,
                    "linked_appointment_id": new_note.linked_appointment_id,
                    "tags": tags_list,
                    "created_at": new_note.created_at.isoformat(),
                    "updated_at": new_note.updated_at.isoformat(),
                    "undo_reference": f"note:{new_note.id}",
                },
                metadata={
                    "entity": "note",
                    "id": new_note.id,
                    "undoable": True,
                    "risk": "write_local",
                },
            )

    except Exception as exc:
        logger.exception("create_typed_note failed: %s", exc)
        return ToolResult(
            success=False,
            output=None,
            error=f"create_typed_note failed: {exc}",
        )


__all__ = ["execute_create_typed_note"]
