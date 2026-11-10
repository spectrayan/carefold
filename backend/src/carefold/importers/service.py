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

from yarvelle_core.config import settings
from carefold.fhir.dedup import evaluate_staged_records_dedup_preview
from carefold.fhir.repository import (
    compute_canonical_fhir_content_hash,
    delete_fhir_resource_with_history,
    ensure_canonical_patient_resource,
    get_inbound_references,
    get_outbound_references,
    get_resource_version_history,
    link_intra_batch_references,
    reverse_dedup_merge,
    search_resources_by_coding,
    upsert_fhir_resource_with_history,
)
from carefold.models import (
    HealthResource,
    HealthResourceCoding,
    HealthResourceReference,
    HealthResourceVersion,
    ImportBatch,
)
from yarvelle_core.db.models import (
    Attachment,
    AuditEventRecord,
    Job,
    Profile,
    utc_now,
)
from carefold.importers.apple_health import parse_apple_health_export
from carefold.importers.ccda import parse_ccda_xml
from carefold.importers.fhir_bundle import parse_fhir_bundle
from carefold.importers.fhir_converter import parse_hl7v2_to_fhir
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
    "hl7v2",
})


def detect_import_format(filename: str, content: Union[bytes, str], fmt: Optional[str] = None) -> str:
    """Auto-detects or validates the clinical import format ('fhir_r4', 'ccda', 'apple_health', 'iis_pdf', 'smart_health_card', 'hl7v2')."""
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
            "hl7": "hl7v2",
            "hl7v2": "hl7v2",
            "hl7_v2": "hl7v2",
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
    if fname_lower.endswith((".hl7", ".hl7v2", ".er7")):
        return "hl7v2"
    if raw_bytes[:4] == b"PK\x03\x04" or fname_lower.endswith(".zip"):
        return "apple_health"
    if raw_bytes[:4] == b"%PDF" or fname_lower.endswith(".pdf"):
        return "iis_pdf"

    head = raw_bytes[:4096].decode("utf-8", errors="ignore").lstrip()
    if head.startswith("MSH|") or head.startswith("FHS|") or head.startswith("BHS|"):
        return "hl7v2"
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
    *,
    expected_patient_id: Optional[str] = None,
    verified_source_patient_ids: Optional[Sequence[str]] = None,
    strict_patient_matching: bool = True,
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
        "hl7v2": "HL7v2 Clinical Message",
    }
    clean_source_name = (source_name or default_sources[resolved_fmt]).strip()

    # 1. Run format-specific parser first (fail closed on malformed/XXE/tampered input before DB commit)
    if resolved_fmt == "fhir_r4":
        parsed = parse_fhir_bundle(
            raw_bytes,
            source_name=clean_source_name,
            profile_id=clean_profile_id,
            expected_patient_id=expected_patient_id,
            verified_source_patient_ids=verified_source_patient_ids,
            strict_patient_matching=strict_patient_matching,
        )
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
    elif resolved_fmt == "hl7v2":
        parsed = parse_hl7v2_to_fhir(
            raw_bytes.decode("utf-8", errors="replace"),
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
        elif resolved_fmt == "hl7v2":
            content_type = "x-application/hl7-v2+er7"
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
    dedup_preview = await evaluate_staged_records_dedup_preview(
        session,
        profile_id=clean_profile_id,
        staged_records=records,
    )
    summary = parsed.get("summary") or {}
    summary.setdefault("total_records", len(records))
    summary.setdefault("counts_by_type", {})
    summary.setdefault("aggregated_raw_sample_count", summary.get("raw_sample_count", 0))
    summary["format"] = resolved_fmt
    summary["attachment_id"] = attachment.id
    summary["dedup_preview"] = dedup_preview
    if "quarantined_records" in parsed:
        summary["quarantined_records"] = parsed["quarantined_records"]
    if "diagnostics" in parsed:
        summary["diagnostics"] = parsed["diagnostics"]
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
    *,
    expected_patient_id: Optional[str] = None,
    verified_source_patient_ids: Optional[Sequence[str]] = None,
    strict_patient_matching: bool = True,
) -> Dict[str, Any]:
    """Commits staged records from an `ImportBatch` into `HealthResource` and relational repository tables (#282).

    Enforces:
    - Profile ownership check (`batch.profile_id == profile_id`) and `batch.status == "staged"`.
    - Patient identity verification (rejecting ambiguous multi-patient or wrong-patient imports).
    - Optional selective commit via `selected_indices`.
    - Atomic upsert of `HealthResource` (`meta.versionId`, `meta.lastUpdated`, canonical `content_hash`),
      immutable `HealthResourceVersion` snapshot, `HealthResourceCoding` index rows, and
      `HealthResourceReference` graph edges.
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

    batch_summary: Dict[str, Any] = json.loads(batch.summary_json or "{}")
    patient_ctx = batch_summary.get("patient_context") or {}
    if (
        strict_patient_matching
        and patient_ctx.get("ambiguous_multi_patient")
        and not (expected_patient_id or verified_source_patient_ids)
    ):
        raise ValueError(
            f"ImportBatch '{clean_batch_id}' contains ambiguous multiple patient identities and cannot be "
            f"committed without explicit patient disambiguation."
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
    committed_version_ids: List[str] = []
    created_count = 0
    updated_count = 0
    merged_count = 0
    near_duplicate_count = 0

    for idx, rec in enumerate(records_to_commit):
        if not isinstance(rec, dict):
            continue
        rtype = str(rec.get("resource_type") or "Observation").strip()
        source_id = str(rec.get("source_id") or f"{rtype}:{idx}").strip()
        fhir_data = dict(rec.get("data")) if isinstance(rec.get("data"), dict) else {"resourceType": rtype}
        if "source_display" in rec and "_carefold_provenance" not in fhir_data:
            fhir_data["_carefold_provenance"] = {
                "source_name": batch.source_name,
                "source_display": rec["source_display"],
                "trust": rec.get("trust", "untrusted"),
            }

        effective_dt = _parse_iso_datetime(rec.get("effective_at"))
        rec_scope = rec.get("scope")
        rec_codings = rec.get("codings") if isinstance(rec.get("codings"), list) else None
        rec_refs = rec.get("references") if isinstance(rec.get("references"), list) else None

        hr, version_row, is_created = await upsert_fhir_resource_with_history(
            session,
            profile_id=clean_profile_id,
            resource_type=rtype,
            fhir_data=fhir_data,
            source_type="file",
            source_ref=source_ref,
            source_id=source_id,
            effective_at=effective_dt,
            scope=rec_scope,
            codings=rec_codings,
            references=rec_refs,
            source_batch_id=batch.id,
            actor_user_id=actor_user_id,
            expected_patient_id=expected_patient_id,
            verified_source_patient_ids=verified_source_patient_ids,
            strict_patient_matching=strict_patient_matching,
            strict_fhir_validation=(batch.format == "fhir_r4"),
        )
        committed_ids.append(hr.id)
        committed_version_ids.append(version_row.id)
        if is_created:
            created_count += 1
        else:
            updated_count += 1
        if version_row.operation == "merge":
            merged_count += 1
        persisted_payload = hr.data if isinstance(hr.data, dict) else {}
        if isinstance(persisted_payload.get("_carefold_provenance"), dict):
            prov_obj = persisted_payload["_carefold_provenance"]
            dedup_meta = prov_obj.get("dedup") if isinstance(prov_obj.get("dedup"), dict) else {}
            if prov_obj.get("review_required") is True or dedup_meta.get("review_required") is True:
                near_duplicate_count += 1

    # Link intra-batch target_resource_id references now that all resources in the batch exist
    await link_intra_batch_references(
        session,
        profile_id=clean_profile_id,
        resource_ids=committed_ids,
    )

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
            "merged_count": merged_count,
            "near_duplicate_count": near_duplicate_count,
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
        "merged_count": merged_count,
        "near_duplicate_count": near_duplicate_count,
        "committed_resource_ids": committed_ids,
        "version_ids": committed_version_ids,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else now.isoformat(),
        "undo_reference": f"import_batch:{batch.id}",
    }


confirm_batch = commit_import_batch


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
    "compute_canonical_fhir_content_hash",
    "confirm_batch",
    "delete_fhir_resource_with_history",
    "detect_import_format",
    "discard_import_batch",
    "ensure_canonical_patient_resource",
    "evaluate_staged_records_dedup_preview",
    "get_inbound_references",
    "get_import_batch",
    "get_outbound_references",
    "get_resource_version_history",
    "list_import_batches",
    "reverse_dedup_merge",
    "search_resources_by_coding",
    "stage_import",
    "upsert_fhir_resource_with_history",
]
