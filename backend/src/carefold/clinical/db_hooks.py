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

"""Carefold clinical pack registration and non-SQL side-effect hooks for MCP DB Toolbox.

All standard CRUD queries and mutations run natively through `yarvelle_core.tools.mcp_db_toolbox`
using the declarative SQL statements in `carefold/resources/db_tools.yaml` and the dynamic
AST-sandboxed tools (`db_inspect_schema`, `db_execute_query`, `db_mutate_records`).

This module registers Carefold's `db_tools.yaml` and provides hooks strictly for the two
operations that require non-SQL clinical domain logic:
1. `record_vital_reading` — HL7 FHIR R4 LOINC `Observation` synthesis + `check_vitals_red_flags`.
2. `upsert_clinical_note` — `(profile_id, slug)` upsert, search index job enqueueing, and
   optional `workspace/notes/{slug}.md` markdown mirroring.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import yarvelle_core.tools.mcp_db_toolbox as core_toolbox

logger = logging.getLogger(__name__)

CAREFOLD_DB_TOOLS_YAML = (
    Path(__file__).resolve().parents[1] / "resources" / "db_tools.yaml"
)

LOINC_VITAL_MAP: Dict[str, Tuple[str, str, str]] = {
    "blood_pressure": (
        "85354-9",
        "Blood pressure panel with all children optional",
        "mmHg",
    ),
    "heart_rate": ("8867-4", "Heart rate", "bpm"),
    "blood_glucose": ("2339-0", "Glucose [Mass/volume] in Blood", "mg/dL"),
    "spo2": ("2708-6", "Oxygen saturation in Arterial blood", "%"),
    "weight": ("29463-7", "Body weight", "kg"),
    "height": ("8302-2", "Body height", "cm"),
    "temperature": ("8310-5", "Body temperature", "Cel"),
}

_REGISTERED = False


def _parse_iso_datetime(value: Any, fallback: Optional[datetime] = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except Exception:
            pass
    return fallback if fallback is not None else datetime.now(timezone.utc)


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-").lower()
    return cleaned or "note"


async def _hook_upsert_clinical_note(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Upsert a clinical note by (profile_id, slug), enqueue search indexing, and mirror markdown."""
    from carefold.db.models import Job, Note
    from carefold.i18n.locale import normalize_text_nfc

    title = normalize_text_nfc(str(exec_params.get("title") or "").strip())
    content = normalize_text_nfc(str(exec_params.get("content") or "").strip())
    if not title or not content:
        raise ValueError("Both 'title' and 'content' must be non-empty.")

    raw_slug = str(exec_params.get("slug") or "").strip()
    slug = _slugify(raw_slug if raw_slug else title)
    note_type = str(exec_params.get("note_type") or "visit").strip().lower()
    tags_raw = exec_params.get("tags_json")
    if isinstance(tags_raw, list):
        tags_json = json.dumps(tags_raw)
    elif isinstance(tags_raw, str) and tags_raw.strip().startswith("["):
        tags_json = tags_raw.strip()
    else:
        tags_json = "[]"

    existing_note = (
        await session.execute(
            select(Note).where(Note.profile_id == profile_id, Note.slug == slug)
        )
    ).scalar_one_or_none()

    now_dt = _parse_iso_datetime(exec_params.get("now"))
    locale = str(exec_params.get("locale") or "en-US")

    if existing_note is not None:
        existing_note.title = title
        existing_note.type = note_type
        existing_note.content = content
        existing_note.tags_json = tags_json
        existing_note.locale = locale
        if exec_params.get("linked_appointment_id"):
            existing_note.linked_appointment_id = str(
                exec_params["linked_appointment_id"]
            )
        existing_note.updated_at = now_dt
        await session.flush()
        operation = "updated"
        note_id = existing_note.id
    else:
        note_id = str(exec_params.get("id") or uuid.uuid4())
        session.add(
            Note(
                id=note_id,
                user_id=user_id,
                profile_id=profile_id,
                slug=slug,
                title=title,
                type=note_type,
                content=content,
                tags_json=tags_json,
                locale=locale,
                linked_appointment_id=(
                    str(exec_params["linked_appointment_id"])
                    if exec_params.get("linked_appointment_id")
                    else None
                ),
                created_at=now_dt,
                updated_at=now_dt,
            )
        )
        await session.flush()
        operation = "created"

    session.add(
        Job(
            profile_id=profile_id,
            kind="index_doc",
            payload=json.dumps(
                {
                    "doc_id": note_id,
                    "profile_id": profile_id,
                    "source": "clinical_note",
                    "title": title,
                    "content": content,
                }
            ),
            next_run_at=now_dt,
            status="pending",
        )
    )

    ws_root = getattr(exec_params.get("_ctx"), "workspace_root", None)
    if ws_root:
        try:
            notes_dir = Path(ws_root) / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            (notes_dir / f"{slug}.md").write_text(
                (
                    f"---\n"
                    f'title: "{title}"\n'
                    f'created_at: "{now_dt.isoformat()}"\n'
                    f'profile_id: "{profile_id}"\n'
                    f"---\n\n"
                    f"{content}\n"
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Optional workspace markdown mirror skipped: %s", exc)

    record = {
        "id": note_id,
        "profile_id": profile_id,
        "slug": slug,
        "title": title,
        "type": note_type,
        "locale": locale,
        "updated_at": now_dt.isoformat(),
        "operation": operation,
    }
    return {
        "status": "ok",
        "tool": tool_name,
        "entity": "note",
        "record": record,
    }


async def _hook_record_vital_reading(
    tool_name: str,
    exec_params: Dict[str, Any],
    profile_id: Optional[str],
    user_id: Optional[str],
    session: AsyncSession,
) -> Dict[str, Any]:
    """Synthesize an HL7 FHIR R4 LOINC Observation and evaluate clinical vital red flags."""
    from carefold.db.models import HealthResource, Job
    from carefold.safety.vitals import check_vitals_red_flags

    vital_type = str(exec_params.get("vital_type") or "").strip().lower()
    if vital_type not in LOINC_VITAL_MAP:
        raise ValueError(
            f"Unsupported vital_type '{vital_type}'. Must be one of: {', '.join(sorted(LOINC_VITAL_MAP))}."
        )
    loinc_code, display_name, default_unit = LOINC_VITAL_MAP[vital_type]
    unit = str(exec_params.get("unit") or default_unit).strip() or default_unit

    now_dt = _parse_iso_datetime(exec_params.get("now"))
    eff_raw = exec_params.get("effective_at")
    effective_dt = _parse_iso_datetime(eff_raw, fallback=now_dt) if eff_raw else now_dt

    vitals_eval_input: Dict[str, Any] = {}
    if vital_type == "blood_pressure":
        sys_val = exec_params.get("systolic")
        dia_val = exec_params.get("diastolic")
        if sys_val is None or dia_val is None:
            raise ValueError(
                "Both 'systolic' and 'diastolic' are required for blood_pressure."
            )
        sys_f, dia_f = float(sys_val), float(dia_val)
        vitals_eval_input.update({"systolic": sys_f, "diastolic": dia_f})
        fhir_payload: Dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": display_name,
                    }
                ],
                "text": f"Blood Pressure {int(sys_f)}/{int(dia_f)} {unit}",
            },
            "effectiveDateTime": effective_dt.isoformat(),
            "component": [
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "8480-6",
                                "display": "Systolic blood pressure",
                            }
                        ]
                    },
                    "valueQuantity": {"value": sys_f, "unit": unit},
                },
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "8462-4",
                                "display": "Diastolic blood pressure",
                            }
                        ]
                    },
                    "valueQuantity": {"value": dia_f, "unit": unit},
                },
            ],
        }
    else:
        val = exec_params.get("value")
        if val is None:
            raise ValueError(
                f"Numeric 'value' is required for vital_type '{vital_type}'."
            )
        val_f = float(val)
        eval_key = "spo2" if vital_type == "oxygen_saturation" else vital_type
        vitals_eval_input.update({eval_key: val_f, "unit": unit})
        fhir_payload = {
            "resourceType": "Observation",
            "status": "final",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": display_name,
                    }
                ],
                "text": f"{display_name}: {val_f} {unit}",
            },
            "effectiveDateTime": effective_dt.isoformat(),
            "valueQuantity": {"value": val_f, "unit": unit},
        }

    canonical_json = json.dumps(fhir_payload, sort_keys=True)
    content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    rec_id = str(exec_params.get("id") or uuid.uuid4())

    session.add(
        HealthResource(
            id=rec_id,
            profile_id=profile_id,
            resource_type="observation",
            source_type="manual",
            source_ref="mcp_db_toolbox",
            source_id=rec_id,
            content_hash=content_hash,
            data=canonical_json,
            status="active",
            locale=str(exec_params.get("locale") or "en-US"),
            effective_at=effective_dt,
            recorded_at=now_dt,
            created_at=now_dt,
            updated_at=now_dt,
        )
    )
    await session.flush()

    red_flags: List[Dict[str, Any]] = []
    rf_result = check_vitals_red_flags(vitals_eval_input)
    if getattr(rf_result, "triggered", False):
        red_flags.append(
            {
                "triggered": True,
                "category": rf_result.category,
                "severity": rf_result.severity,
                "directive": rf_result.directive,
                "prompt_recheck": rf_result.prompt_recheck,
                "details": rf_result.details,
            }
        )

    session.add(
        Job(
            profile_id=profile_id,
            kind="index_doc",
            payload=json.dumps(
                {
                    "doc_id": rec_id,
                    "profile_id": profile_id,
                    "source": "vital_observation",
                    "title": fhir_payload["code"]["text"],
                    "content": canonical_json,
                }
            ),
            next_run_at=now_dt,
            status="pending",
        )
    )

    record = {
        "id": rec_id,
        "profile_id": profile_id,
        "resource_type": "observation",
        "source_type": "manual",
        "effective_at": effective_dt.isoformat(),
        "status": "active",
    }
    return {
        "status": "ok",
        "tool": tool_name,
        "entity": "health_resource",
        "record": record,
        "fhir_resource": fhir_payload,
        "red_flags": red_flags,
    }


def register_carefold_db_toolbox() -> None:
    """Idempotently register Carefold's declarative YAML and clinical side-effect hooks."""
    global _REGISTERED
    if _REGISTERED:
        return
    if CAREFOLD_DB_TOOLS_YAML.is_file():
        core_toolbox.register_db_tools_yaml(CAREFOLD_DB_TOOLS_YAML)
    core_toolbox.register_db_tool_hook(
        "upsert_clinical_note", _hook_upsert_clinical_note
    )
    core_toolbox.register_db_tool_hook(
        "record_vital_reading", _hook_record_vital_reading
    )
    core_toolbox._DEFAULT_TOOLBOX = None
    _REGISTERED = True
