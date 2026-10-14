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

"""Review-Before-Save clinical & wearable file import staging and commit service (AU-38).

Implements:
- Format auto-detection (`fhir_r4`, `ccda`, `apple_health`).
- CAS attachment archival (`Attachment` with `source="import"`).
- Staging into `ImportBatch` (`status="staged"`) with zero `HealthResource` rows written
  until explicit user confirmation.
- Selective or full commit (`commit_import_batch`) with idempotent `HealthResource` upsert,
  `index_doc` background `Job` enqueueing, and `AuditEventRecord` creation.
- Discard workflow (`discard_import_batch`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Union
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.config import settings
from carefold.db.models import (
    Attachment,
    AuditEventRecord,
    HealthResource,
    ImportBatch,
    Job,
    Profile,
    utc_now,
)
from carefold.importers.apple_health import parse_apple_health_export
from carefold.importers.ccda import parse_ccda_xml
from carefold.importers.fhir_bundle import parse_fhir_bundle
from carefold.importers.iis_pdf import parse_iis_immunisation_text
from carefold.importers.smart_health_card import verify_and_parse_smart_health_card
from carefold.storage.cas import store_cas_file

logger = logging.getLogger("carefold.importers.service")

SUPPORTED_IMPORT_FORMATS = frozenset({
    "fhir_r4",
    "ccda",
    "apple_health",
    "iis_pdf",
    "smart_health_card",
})


def detect_import_format(filename: str, content: Union[bytes, str], fmt: Optional[str] = None) -> str:
    """Auto-detects or validates the clinical import format ('fhir_r4', 'ccda', 'apple_health', 'iis_pdf', 'smart_health_card')."""
    if fmt and str(fmt).strip():
        clean_fmt = str(fmt).strip().lower()
        aliases = {
            "fhir": "fhir_r4",
            "fhir_bundle": "fhir_r4",
            "fhir_r4": "fhir_r4",
            "ccda": "ccda",
            "c-cda": "ccda",
            "cda": "ccda",
            "apple": "apple_health",
            "apple_health": "apple_health",
            "healthkit": "apple_health",
            "iis": "iis_pdf",
            "iis_pdf": "iis_pdf",
            "immunization_pdf": "iis_pdf",
            "immunisation_pdf": "iis_pdf",
            "shc": "smart_health_card",
            "smart_health_card": "smart_health_card",
            "smart-health-card": "smart_health_card",
        }
        resolved = aliases.get(clean_fmt)
        if not resolved:
            raise ValueError(
                f"Unsupported import format '{fmt}'. Supported formats: {sorted(SUPPORTED_IMPORT_FORMATS)}."
            )
        return resolved

    raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    fname_lower = (filename or "").strip().lower()

    if fname_lower.endswith(".smart-health-card"):
        return "smart_health_card"
    if raw_bytes[:4] == b"PK\x03\x04" or fname_lower.endswith(".zip"):
        return "apple_health"
    if raw_bytes[:4] == b"%PDF" or fname_lower.endswith(".pdf"):
        return "iis_pdf"

    head = raw_bytes[:4096].decode("utf-8", errors="ignore").lstrip()
    if head.lower().startswith("shc:/"):
        return "smart_health_card"
    if head.startswith("eyJ") and head.count(".") == 2:
        return "smart_health_card"
    if head.startswith("{"):
        if '"verifiableCredential"' in head:
            return "smart_health_card"
        return "fhir_r4"
    if "<HealthData" in head or "HKQuantityTypeIdentifier" in head or "apple_health" in fname_lower:
        return "apple_health"
    if "<ClinicalDocument" in head or "urn:hl7-org:v3" in head or fname_lower.endswith(".xml"):
        return "ccda"
    if fname_lower.endswith(".json"):
        return "fhir_r4"
    head_lower = head.lower()
    if (
        "immunization" in head_lower
        or "immunisation" in head_lower
        or "iis" in fname_lower
        or "vaccine" in head_lower
    ):
        return "iis_pdf"

    raise ValueError(
        "Unable to auto-detect clinical import format from filename or content. "
        "Expected FHIR R4 Bundle JSON, C-CDA XML, Apple Health export XML/ZIP, State IIS PDF, or SMART Health Card."
    )


def _parse_iso_datetime(raw_iso: Optional[str]) -> datetime:
    """Parses ISO-8601 string into timezone-aware UTC datetime."""
    if not raw_iso or not isinstance(raw_iso, str):
        return utc_now()
    clean = raw_iso.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return utc_now()


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "import.dat")
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return cleaned if cleaned not in ("", ".", "..") else "import.dat"


async def stage_import(
    session: AsyncSession,
    profile_id: str,
    filename: str,
    content: Union[bytes, str],
    source_name: Optional[str] = None,
    fmt: Optional[str] = None,
    user_id: Optional[str] = None,
    trusted_jwks: Optional[Dict[str, Any]] = None,
) -> ImportBatch:
    """Stages a clinical or wearable file into an `ImportBatch` without writing to `HealthResource`.

    Steps:
    1. Validates `profile_id` and resolves format (`fhir_r4`, `ccda`, `apple_health`, `iis_pdf`, `smart_health_card`).
    2. Archives raw content in Content-Addressed Storage (CAS) and persists/reuses an
       `Attachment` row with `source="import"`.
    3. Parses and normalizes clinical records with provenance and `"trust": "untrusted"`.
    4. Creates and persists an `ImportBatch` row with `status="staged"`.
    """
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required to stage a clinical import.")

    if content is None or (isinstance(content, (bytes, str)) and len(content) == 0):
        raise ValueError("Import file content cannot be empty.")

    raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    resolved_fmt = detect_import_format(filename, raw_bytes, fmt=fmt)

    default_sources = {
        "fhir_r4": "FHIR Bundle Import",
        "ccda": "C-CDA Clinical Summary",
        "apple_health": "Apple Health Export",
        "iis_pdf": "State IIS Registry PDF",
        "smart_health_card": "SMART Health Card",
    }
    clean_source_name = (source_name or default_sources[resolved_fmt]).strip()

    # 1. Run format-specific parser first (fail closed on malformed/XXE/tampered input before DB commit)
    if resolved_fmt == "fhir_r4":
        parsed = parse_fhir_bundle(raw_bytes, source_name=clean_source_name)
    elif resolved_fmt == "ccda":
        parsed = parse_ccda_xml(raw_bytes, source_name=clean_source_name)
    elif resolved_fmt == "apple_health":
        parsed = parse_apple_health_export(raw_bytes, source_name=clean_source_name)
    elif resolved_fmt == "iis_pdf":
        parsed = parse_iis_immunisation_text(raw_bytes, source_name=clean_source_name)
    elif resolved_fmt == "smart_health_card":
        parsed = verify_and_parse_smart_health_card(
            raw_bytes,
            trusted_jwks=trusted_jwks,
            source_name=clean_source_name,
        )
    else:
        raise ValueError(f"Unsupported format: {resolved_fmt}")

    # 2. Resolve profile owner if user_id not explicitly passed
    effective_user_id = user_id
    if not effective_user_id:
        prof_stmt = select(Profile).where(Profile.id == clean_profile_id)
        prof_res = await session.execute(prof_stmt)
        prof_obj = prof_res.scalar_one_or_none()
        if prof_obj is not None:
            effective_user_id = prof_obj.user_id

    # 3. Store raw payload in CAS and create/reuse Attachment row
    cas_path, cas_sha256, _is_dedup = store_cas_file(
        content=raw_bytes,
        carefold_home=settings.home_dir,
        user_id=effective_user_id,
        profile_id=clean_profile_id,
    )

    existing_att_stmt = select(Attachment).where(
        Attachment.profile_id == clean_profile_id,
        Attachment.sha256_hash == cas_sha256,
        Attachment.source == "import",
    )
    existing_att_res = await session.execute(existing_att_stmt)
    attachment = existing_att_res.scalars().first()

    if attachment is None:
        safe_fname = _sanitize_filename(filename)
        if resolved_fmt in ("fhir_r4", "smart_health_card"):
            content_type = "application/json"
        elif resolved_fmt == "iis_pdf":
            content_type = "application/pdf"
        else:
            content_type = "application/xml"
        attachment = Attachment(
            id=str(uuid.uuid4()),
            user_id=effective_user_id,
            profile_id=clean_profile_id,
            storage_key=str(cas_path),
            filename=safe_fname,
            original_name=filename or safe_fname,
            content_type=content_type,
            size_bytes=len(raw_bytes),
            sha256_hash=cas_sha256,
            source="import",
            source_ref=clean_source_name,
            extraction_status="completed",
        )
        session.add(attachment)
        await session.flush()

    records = parsed.get("records") or []
    summary = parsed.get("summary") or {}
    summary.setdefault("total_records", len(records))
    summary.setdefault("counts_by_type", {})
    summary.setdefault("aggregated_raw_sample_count", summary.get("raw_sample_count", 0))
    summary["format"] = resolved_fmt
    summary["attachment_id"] = attachment.id
    if resolved_fmt == "smart_health_card":
        summary["verification_status"] = parsed.get("verification_status", "unverified_issuer")
        summary["issuer"] = parsed.get("issuer", "unknown-issuer")

    batch = ImportBatch(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        attachment_id=attachment.id,
        format=resolved_fmt,
        source_name=clean_source_name,
        status="staged",
        summary_json=json.dumps(summary),
        staged_records_json=json.dumps(records),
        committed_resource_ids_json="[]",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


async def commit_import_batch(
    session: AsyncSession,
    profile_id: str,
    batch_id: str,
    selected_indices: Optional[List[int]] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Commits staged records from an `ImportBatch` into `HealthResource` rows.

    Enforces:
    - Profile ownership check (`batch.profile_id == profile_id`) and `batch.status == "staged"`.
    - Optional selective commit via `selected_indices`.
    - Idempotent upsert on `(profile_id, source_type="file", source_ref, source_id)` with `content_hash`.
    - Enqueues an `index_doc` background `Job` for search freshness.
    - Persists an `AuditEventRecord` (`tool="commit_clinical_import"`, `risk="write_local"`).
    """
    clean_profile_id = (profile_id or "").strip()
    clean_batch_id = (batch_id or "").strip()
    if not clean_profile_id or not clean_batch_id:
        raise ValueError("profile_id and batch_id are required.")

    stmt = select(ImportBatch).where(
        ImportBatch.id == clean_batch_id,
        ImportBatch.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    batch = res.scalar_one_or_none()
    if batch is None:
        raise ValueError(f"ImportBatch '{clean_batch_id}' not found for profile '{clean_profile_id}'.")

    if batch.status != "staged":
        raise ValueError(
            f"ImportBatch '{clean_batch_id}' cannot be committed because its status is '{batch.status}' (expected 'staged')."
        )

    staged_records: List[Dict[str, Any]] = json.loads(batch.staged_records_json or "[]")
    if selected_indices is not None:
        index_set = set(int(i) for i in selected_indices)
        records_to_commit = [
            rec for idx, rec in enumerate(staged_records) if idx in index_set
        ]
    else:
        records_to_commit = list(staged_records)

    source_ref = batch.attachment_id or batch.id
    now = utc_now()
    committed_ids: List[str] = []
    created_count = 0
    updated_count = 0

    for idx, rec in enumerate(records_to_commit):
        if not isinstance(rec, dict):
            continue
        rtype = str(rec.get("resource_type") or "Observation").strip()
        source_id = str(rec.get("source_id") or f"{rtype}:{idx}").strip()
        fhir_data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
        if "source_display" in rec and "_carefold_provenance" not in fhir_data:
            fhir_data = dict(fhir_data)
            fhir_data["_carefold_provenance"] = {
                "source_name": batch.source_name,
                "source_display": rec["source_display"],
                "trust": rec.get("trust", "untrusted"),
            }

        content_hash = hashlib.sha256(
            json.dumps(fhir_data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        effective_dt = _parse_iso_datetime(rec.get("effective_at"))

        # Check for existing HealthResource for idempotent upsert
        existing_stmt = select(HealthResource).where(
            HealthResource.profile_id == clean_profile_id,
            HealthResource.source_type == "file",
            HealthResource.source_ref == source_ref,
            HealthResource.source_id == source_id,
        )
        existing_res = await session.execute(existing_stmt)
        hr = existing_res.scalar_one_or_none()

        if hr is not None:
            hr.resource_type = rtype
            hr.content_hash = content_hash
            hr.data = fhir_data
            hr.effective_at = effective_dt
            hr.status = "active"
            hr.updated_at = now
            committed_ids.append(hr.id)
            updated_count += 1
        else:
            hr = HealthResource(
                id=str(uuid.uuid4()),
                profile_id=clean_profile_id,
                resource_type=rtype,
                source_type="file",
                source_ref=source_ref,
                source_id=source_id,
                content_hash=content_hash,
                data=fhir_data,
                status="active",
                effective_at=effective_dt,
                recorded_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(hr)
            committed_ids.append(hr.id)
            created_count += 1

    batch.status = "committed"
    batch.committed_at = now
    batch.updated_at = now
    batch.committed_resource_ids_json = json.dumps(committed_ids)

    # Enqueue background index_doc job for search freshness
    index_job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        kind="index_doc",
        payload=json.dumps({
            "batch_id": batch.id,
            "profile_id": clean_profile_id,
            "resource_ids": committed_ids,
            "doc_type": "health_resource_batch",
        }),
        timezone="UTC",
        next_run_at=now,
        idempotency_key=f"index:import_batch:{batch.id}",
        status="pending",
    )
    session.add(index_job)

    # Write AuditEventRecord for provenance & undoability
    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "batch_id": batch.id,
                "profile_id": clean_profile_id,
                "committed_ids": committed_ids,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit_record = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="tool",
        tool="commit_clinical_import",
        risk="write_local",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"import_batch:{batch.id}",
        detail_redacted=json.dumps({
            "batch_id": batch.id,
            "format": batch.format,
            "source_name": batch.source_name,
            "committed_count": len(committed_ids),
            "created_count": created_count,
            "updated_count": updated_count,
        }),
    )
    session.add(audit_record)

    await session.commit()
    await session.refresh(batch)

    return {
        "batch_id": batch.id,
        "profile_id": clean_profile_id,
        "status": batch.status,
        "format": batch.format,
        "source_name": batch.source_name,
        "committed_count": len(committed_ids),
        "created_count": created_count,
        "updated_count": updated_count,
        "committed_resource_ids": committed_ids,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else now.isoformat(),
        "undo_reference": f"import_batch:{batch.id}",
    }


async def discard_import_batch(
    session: AsyncSession,
    profile_id: str,
    batch_id: str,
) -> bool:
    """Marks a staged `ImportBatch` as `'discarded'` without writing any `HealthResource` rows."""
    clean_profile_id = (profile_id or "").strip()
    clean_batch_id = (batch_id or "").strip()
    if not clean_profile_id or not clean_batch_id:
        raise ValueError("profile_id and batch_id are required.")

    stmt = select(ImportBatch).where(
        ImportBatch.id == clean_batch_id,
        ImportBatch.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    batch = res.scalar_one_or_none()
    if batch is None:
        return False

    batch.status = "discarded"
    batch.updated_at = utc_now()
    await session.commit()
    return True


async def list_import_batches(
    session: AsyncSession,
    profile_id: str,
    status: Optional[str] = None,
) -> List[ImportBatch]:
    """Lists `ImportBatch` rows for a profile ordered by creation time descending."""
    stmt = select(ImportBatch).where(ImportBatch.profile_id == profile_id.strip())
    if status and status.strip():
        stmt = stmt.where(ImportBatch.status == status.strip())
    stmt = stmt.order_by(ImportBatch.created_at.desc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_import_batch(
    session: AsyncSession,
    profile_id: str,
    batch_id: str,
) -> Optional[ImportBatch]:
    """Retrieves a single `ImportBatch` scoped to `profile_id`."""
    stmt = select(ImportBatch).where(
        ImportBatch.id == batch_id.strip(),
        ImportBatch.profile_id == profile_id.strip(),
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


__all__ = [
    "SUPPORTED_IMPORT_FORMATS",
    "commit_import_batch",
    "detect_import_format",
    "discard_import_batch",
    "get_import_batch",
    "list_import_batches",
    "stage_import",
]
