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

"""SQL pushdown predicates and coding-index helpers for FHIR R4 & Vitals queries (#341).

Pushes resource_type, logical-ID, LOINC/terminology coding filters, category/clinical-status
predicates, date bounds, COUNT(*), and LIMIT/OFFSET pagination into SQLite/PostgreSQL so
endpoints and MCP tools never scan or JSON-decode full-chart HealthResource tables in Python.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from sqlalchemy import ColumnElement, and_, exists, func, literal, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.fhir.registry import extract_codings, resolve_resource_scope
from carefold.fhir.terminology import normalize_code_system_uri
from carefold.models.health import HealthResource, HealthResourceCoding


def get_session_dialect_name(session: AsyncSession) -> str:
    """Resolves the active SQLAlchemy dialect name ('sqlite', 'postgresql', etc.)."""
    bind = getattr(session, "bind", None)
    if bind is None:
        try:
            bind = session.get_bind()
        except Exception:
            bind = None
    dialect = getattr(bind, "dialect", None)
    return str(getattr(dialect, "name", "sqlite") or "sqlite").lower()


def build_observation_coding_rows(
    *,
    resource_id: str,
    profile_id: str,
    fhir_data: Dict[str, Any],
    resource_type: str = "Observation",
    scope: Optional[str] = None,
) -> List[HealthResourceCoding]:
    """Builds deduplicated HealthResourceCoding index rows (including component LOINCs)."""
    canonical_rtype = "Observation" if resource_type.lower() == "observation" else resource_type
    resolved_scope = scope or resolve_resource_scope(canonical_rtype, fhir_data)
    extracted = extract_codings(fhir_data, rtype=canonical_rtype)

    rows: List[HealthResourceCoding] = []
    seen: set[Tuple[str, str, str]] = set()
    for item in extracted:
        raw_code = str(item.get("code") or "").strip()
        if not raw_code:
            continue
        raw_sys = str(item.get("system") or "").strip()
        canonical_sys = (
            normalize_code_system_uri(raw_sys, code=raw_code, resource_type=canonical_rtype).canonical_system
            if raw_sys
            else ""
        )
        elem_path = str(item.get("element_path") or "code").strip() or "code"
        dedup_key = (elem_path, canonical_sys, raw_code)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        display_val = str(item.get("display") or "").strip() or None
        rows.append(
            HealthResourceCoding(
                id=str(uuid.uuid4()),
                resource_id=resource_id,
                profile_id=profile_id,
                resource_type=canonical_rtype,
                element_path=elem_path,
                system=canonical_sys or None,
                code=raw_code,
                display=display_val[:255] if display_val else None,
                scope=resolved_scope,
            )
        )
    return rows


def json_string_expr(column: Any, json_key: str, *, dialect_name: str = "sqlite") -> Any:
    """Extracts a top-level string field from a JSON column in SQL."""
    if dialect_name.startswith("postgres"):
        return column.op("->>")(json_key)
    return func.json_extract(column, f"$.{json_key}")


def build_logical_id_sql_filter(
    resource_type: str,
    logical_id: str,
    *,
    dialect_name: str = "sqlite",
) -> ColumnElement[bool]:
    """Builds a SQL predicate matching a HealthResource by canonical resource_type and logical FHIR id."""
    clean_id = logical_id.strip()
    id_in_json = json_string_expr(HealthResource.data, "id", dialect_name=dialect_name)
    return and_(
        func.lower(HealthResource.resource_type) == resource_type.lower(),
        or_(
            HealthResource.id == clean_id,
            HealthResource.source_id == clean_id,
            HealthResource.source_id == f"{resource_type}:{clean_id}",
            HealthResource.source_id == f"{resource_type.lower()}:{clean_id}",
            HealthResource.source_id.endswith(f":{clean_id}"),
            id_in_json == clean_id,
        ),
    )


def build_code_sql_filter(
    code: Optional[str],
    *,
    system: Optional[str] = None,
    scope: Optional[str] = None,
    match_display: bool = False,
    component_only_or_top: bool = False,
    dialect_name: str = "sqlite",
) -> ColumnElement[bool]:
    """Builds a SQL predicate matching terminology codes via HealthResourceCoding with unindexed JSON fallback.

    Uses an indexed EXISTS subquery on ``health_resource_codings`` for indexed rows, plus an
    in-SQL JSON fallback gated by ``NOT EXISTS (SELECT 1 FROM health_resource_codings ...)``
    so rows inserted directly in tests/legacy paths without coding index rows still match
    accurately inside SQL without loading full tables into Python.
    """
    clean_code = (code or "").strip()
    clean_code_low = clean_code.lower()
    clean_sys = (system or "").strip()

    coding_conds: List[ColumnElement[Any]] = [
        HealthResourceCoding.profile_id == HealthResource.profile_id,
        HealthResourceCoding.resource_id == HealthResource.id,
    ]
    if scope:
        coding_conds.append(HealthResourceCoding.scope == scope)
    if component_only_or_top:
        coding_conds.append(HealthResourceCoding.element_path.in_(("code", "code.coding", "component.code", "component.code.coding")))
    if clean_sys:
        coding_conds.append(HealthResourceCoding.system == clean_sys)
    if clean_code_low:
        if match_display:
            coding_conds.append(
                or_(
                    func.lower(HealthResourceCoding.code) == clean_code_low,
                    func.lower(func.coalesce(HealthResourceCoding.display, "")).contains(clean_code_low),
                )
            )
        else:
            coding_conds.append(func.lower(HealthResourceCoding.code) == clean_code_low)

    indexed_exists = exists(select(literal(1)).where(*coding_conds))

    any_indexed_for_row = exists(
        select(literal(1)).where(
            HealthResourceCoding.profile_id == HealthResource.profile_id,
            HealthResourceCoding.resource_id == HealthResource.id,
        )
    )

    if dialect_name == "sqlite":
        uid = uuid.uuid4().hex[:8]
        if component_only_or_top and clean_code and not clean_sys and not match_display:
            p_exact = f"_cf_code_exact_{uid}"
            unindexed_json_match = text(
                "("
                "EXISTS ("
                "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
                "    THEN json_extract(health_resources.data, '$.code.coding') END) jc "
                f"  WHERE json_extract(jc.value, '$.code') = :{p_exact}"
                ") OR EXISTS ("
                "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
                "    THEN json_extract(health_resources.data, '$.component') END) comp, "
                "  json_each(json_extract(comp.value, '$.code.coding')) cc "
                f"  WHERE json_extract(cc.value, '$.code') = :{p_exact}"
                ")"
                ")"
            ).bindparams(**{p_exact: clean_code})
        else:
            p_low = f"_cf_code_low_{uid}"
            p_sys = f"_cf_sys_{uid}"
            sys_clause_jc = (
                f" AND (:{p_sys} = '' OR LOWER(COALESCE(json_extract(jc.value, '$.system'), '')) = LOWER(:{p_sys}))"
            )
            sys_clause_cc = (
                f" AND (:{p_sys} = '' OR LOWER(COALESCE(json_extract(cc.value, '$.system'), '')) = LOWER(:{p_sys}))"
            )
            code_clause_jc = (
                f"(:{p_low} = '' OR LOWER(COALESCE(json_extract(jc.value, '$.code'), '')) = :{p_low}"
                + (
                    f" OR LOWER(COALESCE(json_extract(jc.value, '$.display'), '')) LIKE '%' || :{p_low} || '%'"
                    if match_display
                    else ""
                )
                + ")"
            )
            code_clause_cc = (
                f"(:{p_low} = '' OR LOWER(COALESCE(json_extract(cc.value, '$.code'), '')) = :{p_low}"
                + (
                    f" OR LOWER(COALESCE(json_extract(cc.value, '$.display'), '')) LIKE '%' || :{p_low} || '%'"
                    if match_display
                    else ""
                )
                + ")"
            )
            text_fallback = (
                f" OR LOWER(COALESCE(CASE WHEN json_valid(health_resources.data) THEN json_extract(health_resources.data, '$.code.text') END, '')) LIKE '%' || :{p_low} || '%'"
                if (match_display and clean_code_low and not clean_sys)
                else ""
            )
            unindexed_json_match = text(
                "("
                "EXISTS ("
                "  SELECT 1 FROM ("
                "    SELECT value FROM json_each(CASE WHEN json_valid(health_resources.data) THEN json_extract(health_resources.data, '$.code.coding') END) "
                "    UNION ALL "
                "    SELECT value FROM json_each(CASE WHEN json_valid(health_resources.data) THEN json_extract(health_resources.data, '$.medicationCodeableConcept.coding') END) "
                "    UNION ALL "
                "    SELECT value FROM json_each(CASE WHEN json_valid(health_resources.data) THEN json_extract(health_resources.data, '$.vaccineCode.coding') END)"
                "  ) jc WHERE "
                + code_clause_jc
                + sys_clause_jc
                + ") OR EXISTS ("
                "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
                "    THEN json_extract(health_resources.data, '$.component') END) comp, "
                "  json_each(json_extract(comp.value, '$.code.coding')) cc "
                "  WHERE "
                + code_clause_cc
                + sys_clause_cc
                + ")"
                + text_fallback
                + ")"
            ).bindparams(**{p_low: clean_code_low, p_sys: clean_sys})
    else:
        needle = clean_code_low or clean_sys.lower()
        unindexed_json_match = func.lower(func.cast(HealthResource.data, HealthResource.status.type)).contains(needle)

    return or_(indexed_exists, and_(not_(any_indexed_for_row), unindexed_json_match))


def build_category_sql_filter(
    category_filter: str,
    *,
    dialect_name: str = "sqlite",
) -> ColumnElement[bool]:
    """Builds a SQL predicate matching FHIR ``category`` strings or CodeableConcept codings."""
    target = category_filter.strip().lower()
    if "|" in target:
        _, target = target.split("|", 1)
    if not target:
        return literal(True)

    cat_indexed = exists(
        select(literal(1)).where(
            HealthResourceCoding.profile_id == HealthResource.profile_id,
            HealthResourceCoding.resource_id == HealthResource.id,
            HealthResourceCoding.element_path.in_(("category", "category.coding")),
            or_(
                func.lower(HealthResourceCoding.code) == target,
                func.lower(func.coalesce(HealthResourceCoding.display, "")) == target,
            ),
        )
    )

    if dialect_name == "sqlite":
        p_cat = f"_cf_cat_{uuid.uuid4().hex[:8]}"
        json_cat = text(
            "("
            "LOWER(COALESCE(CASE WHEN json_valid(health_resources.data) "
            f"  THEN json_extract(health_resources.data, '$.category.text') END, '')) = :{p_cat} "
            "OR EXISTS ("
            "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
            "    AND json_type(health_resources.data, '$.category') = 'array' "
            "    THEN json_extract(health_resources.data, '$.category') END) cat_el "
            f"  WHERE (json_type(cat_el.value) = 'text' AND LOWER(cat_el.value) = :{p_cat}) "
            f"     OR LOWER(COALESCE(json_extract(cat_el.value, '$.text'), '')) = :{p_cat} "
            "     OR EXISTS ("
            "       SELECT 1 FROM json_each(CASE WHEN json_type(cat_el.value) = 'object' "
            "         THEN json_extract(cat_el.value, '$.coding') END) c_el "
            f"       WHERE LOWER(COALESCE(json_extract(c_el.value, '$.code'), '')) = :{p_cat} "
            f"          OR LOWER(COALESCE(json_extract(c_el.value, '$.display'), '')) = :{p_cat}"
            "     )"
            ") "
            "OR EXISTS ("
            "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
            "    AND json_type(health_resources.data, '$.category') = 'object' "
            "    THEN json_extract(health_resources.data, '$.category.coding') END) c_single "
            f"  WHERE LOWER(COALESCE(json_extract(c_single.value, '$.code'), '')) = :{p_cat} "
            f"     OR LOWER(COALESCE(json_extract(c_single.value, '$.display'), '')) = :{p_cat}"
            ")"
            ")"
        ).bindparams(**{p_cat: target})
        return or_(cat_indexed, json_cat)

    return or_(
        cat_indexed,
        func.lower(func.cast(HealthResource.data, HealthResource.status.type)).contains(target),
    )


def build_clinical_status_sql_filter(
    clinical_status_filter: str,
    *,
    dialect_name: str = "sqlite",
) -> ColumnElement[bool]:
    """Builds a SQL predicate matching FHIR ``clinicalStatus`` string or CodeableConcept."""
    target = clinical_status_filter.strip().lower()
    if not target:
        return literal(True)

    cs_indexed = exists(
        select(literal(1)).where(
            HealthResourceCoding.profile_id == HealthResource.profile_id,
            HealthResourceCoding.resource_id == HealthResource.id,
            HealthResourceCoding.element_path.in_(("clinicalStatus", "clinicalStatus.coding")),
            func.lower(HealthResourceCoding.code) == target,
        )
    )

    if dialect_name == "sqlite":
        p_cs = f"_cf_cs_{uuid.uuid4().hex[:8]}"
        json_cs = text(
            "("
            "LOWER(COALESCE(CASE WHEN json_valid(health_resources.data) "
            "  AND json_type(health_resources.data, '$.clinicalStatus') = 'text' "
            f"  THEN json_extract(health_resources.data, '$.clinicalStatus') END, '')) = :{p_cs} "
            "OR LOWER(COALESCE(CASE WHEN json_valid(health_resources.data) "
            f"  THEN json_extract(health_resources.data, '$.clinicalStatus.text') END, '')) = :{p_cs} "
            "OR EXISTS ("
            "  SELECT 1 FROM json_each(CASE WHEN json_valid(health_resources.data) "
            "    THEN json_extract(health_resources.data, '$.clinicalStatus.coding') END) cs_el "
            f"  WHERE LOWER(COALESCE(json_extract(cs_el.value, '$.code'), '')) = :{p_cs}"
            ")"
            ")"
        ).bindparams(**{p_cs: target})
        return or_(cs_indexed, json_cs)

    return or_(
        cs_indexed,
        func.lower(func.cast(HealthResource.data, HealthResource.status.type)).contains(target),
    )


def build_fhir_status_sql_filter(
    status_filter: str,
    *,
    dialect_name: str = "sqlite",
) -> ColumnElement[bool]:
    """Builds a SQL predicate matching FHIR resource payload ``status`` (falling back to row status)."""
    target = status_filter.strip().lower()
    if not target:
        return literal(True)
    payload_status = json_string_expr(HealthResource.data, "status", dialect_name=dialect_name)
    return func.lower(func.coalesce(payload_status, HealthResource.status)) == target


def build_fhir_date_sql_filters(
    column: Any,
    raw_filters: Sequence[str],
    parse_token_fn: Any,
) -> List[ColumnElement[bool]]:
    """Translates FHIR date search tokens (ge/le/gt/lt/eq/sa/eb) into SQL column predicates."""
    clauses: List[ColumnElement[bool]] = [column.is_not(None)] if raw_filters else []
    for idx, raw_tok in enumerate(raw_filters):
        if not raw_tok or not str(raw_tok).strip():
            continue
        clean_raw = str(raw_tok).strip()
        op, bound_dt = parse_token_fn(clean_raw)
        if op == "ge":
            clauses.append(column >= bound_dt)
        elif op == "gt":
            clauses.append(column > bound_dt)
        elif op == "le":
            clauses.append(column <= bound_dt)
        elif op == "lt":
            clauses.append(column < bound_dt)
        elif op == "eq":
            clean_val = clean_raw[2:].strip() if clean_raw.lower().startswith("eq") else clean_raw
            if len(clean_val) == 10 and clean_val[4] == "-" and clean_val[7] == "-":
                start_dt = datetime.fromisoformat(f"{clean_val}T00:00:00+00:00").astimezone(timezone.utc)
                end_dt = datetime.fromisoformat(f"{clean_val}T23:59:59.999999+00:00").astimezone(timezone.utc)
                clauses.append(and_(column >= start_dt, column <= end_dt))
            else:
                clauses.append(column == bound_dt)
        else:
            _ = idx
    return clauses
