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

"""Preventive Care & Immunisation Engine (AU-36 / E6).

Implements:
- Cited YAML rule loading and citation metadata validation (source, citation_url, reviewed_by, reviewed_at).
- Adult USPSTF Grade A/B screening evaluation ("Discuss with your clinician").
- Pediatric well-child & immunisation schedule evaluation ("Possibly due, confirm with your pediatrician").
- AAP Bright Futures 2026 ("aap_2026", default) vs CDC ACIP ("cdc") schedule variant switching.
- Automatic matching against FHIR HealthResource (Immunization / Observation) codes and PreventiveRecord overrides.
- 1-click conversion of due items into visit preparation questions or reminders with audit logging.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Union
import uuid
import yaml

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.audit.logger import record_audit
from carefold.config import settings
from carefold.db.models import (
    Appointment,
    AuditEventRecord,
    HealthResource,
    Job,
    Note,
    PreventiveRecord,
    Profile,
    Reminder,
    SystemSetting,
    User,
)

logger = logging.getLogger("carefold.clinical.preventive")


async def _resolve_actor_user_id(
    session: AsyncSession,
    profile_id: str,
    actor_user_id: Optional[str],
) -> Optional[str]:
    """Resolves a valid User.id for FK columns (AuditEventRecord.actor_user_id, Note.user_id)."""
    if actor_user_id and str(actor_user_id).strip():
        candidate = str(actor_user_id).strip()
        user_res = await session.execute(select(User.id).where(User.id == candidate))
        if user_res.scalar_one_or_none() is not None:
            return candidate
    prof_res = await session.execute(select(Profile.user_id).where(Profile.id == profile_id))
    return prof_res.scalar_one_or_none()


ScheduleSourceLiteral = Literal["aap_2026", "cdc"]
PreventiveStatusLiteral = Literal["due", "completed", "not_applicable", "declined"]
PreventiveActionLiteral = Literal["reminder", "prep_question"]

VALID_SCHEDULE_SOURCES: Set[str] = {"aap_2026", "cdc"}
VALID_PREVENTIVE_STATUSES: Set[str] = {"due", "completed", "not_applicable", "declined"}
VALID_RULE_CATEGORIES: Set[str] = {"screening", "immunisation", "well_visit"}
VALID_SEX_FILTERS: Set[str] = {"any", "female", "male"}
VALID_SCHEDULE_VARIANTS: Set[str] = {"all", "aap_2026", "cdc"}

REQUIRED_CITATION_FIELDS: Sequence[str] = (
    "source",
    "citation_url",
    "reviewed_by",
    "reviewed_at",
)

REQUIRED_RULE_FIELDS: Sequence[str] = (
    "id",
    "title",
    "category",
    "target_age_min_months",
    "target_age_max_months",
    "sex",
    "schedule_variant",
    "codes",
    "clinical_summary",
    "source",
    "citation_url",
    "reviewed_by",
    "reviewed_at",
)

DEFAULT_ADULT_AGE_MONTHS: int = 420  # 35 years (default when date_of_birth is None)
PEDIATRIC_CUTOFF_MONTHS: int = 216   # 18 years (216 months)

ADULT_FRAMING: str = "Discuss with your clinician"
PEDIATRIC_FRAMING: str = "Possibly due, confirm with your pediatrician"

# In-memory fallback map for schedule_source preference per profile
_profile_schedule_sources: Dict[str, str] = {}


def _resolve_default_yaml_paths(skills_dir: Optional[Union[Path, str]] = None) -> List[Path]:
    """Resolves the canonical YAML reference rule files in skills/preventive-care/references/."""
    candidates: List[Path] = []
    if skills_dir is not None:
        candidates.append(Path(skills_dir))
    try:
        candidates.append(Path(settings.get_skills_dir()))
    except Exception:
        pass
    # Walk up from backend/src/carefold/clinical/preventive.py -> repo root / skills
    repo_root = Path(__file__).resolve().parents[4]
    candidates.append(repo_root / "skills")
    candidates.append(Path.cwd() / "skills")

    for base in candidates:
        ref_dir = base / "preventive-care" / "references"
        if ref_dir.is_dir():
            yaml_files = sorted(ref_dir.glob("*.yaml"))
            if yaml_files:
                return yaml_files

    raise FileNotFoundError(
        "Preventive care YAML reference files not found in skills/preventive-care/references/."
    )


def validate_preventive_rule(rule: Dict[str, Any], source_file: str = "unknown") -> Dict[str, Any]:
    """Validates a single preventive rule dictionary, enforcing mandatory citation metadata (E6.4).

    Raises:
        ValueError: If any mandatory field or citation field (source, citation_url,
            reviewed_by, reviewed_at) is missing or empty.
    """
    if not isinstance(rule, dict):
        raise ValueError(f"Invalid rule entry in {source_file}: expected mapping, got {type(rule).__name__}.")

    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
        raise ValueError(f"Preventive rule in {source_file} is missing non-empty 'id'.")

    # 1. Enforce citation metadata invariant (E6.4)
    for c_field in REQUIRED_CITATION_FIELDS:
        val = rule.get(c_field)
        if val is None or not str(val).strip():
            raise ValueError(
                f"Preventive rule '{rule_id}' in {source_file} is missing mandatory citation field '{c_field}'."
            )

    citation_url = str(rule["citation_url"]).strip()
    if not (citation_url.startswith("https://") or citation_url.startswith("http://")):
        raise ValueError(
            f"Preventive rule '{rule_id}' in {source_file} has invalid citation_url '{citation_url}': must be an HTTP(S) URL."
        )

    # 2. Enforce structural fields
    for field_name in REQUIRED_RULE_FIELDS:
        if field_name not in rule or rule[field_name] is None:
            raise ValueError(
                f"Preventive rule '{rule_id}' in {source_file} is missing required field '{field_name}'."
            )

    title = str(rule.get("title") or "").strip()
    if not title:
        raise ValueError(f"Preventive rule '{rule_id}' in {source_file} has empty 'title'.")

    category = str(rule.get("category") or "").strip().lower()
    if category not in VALID_RULE_CATEGORIES:
        raise ValueError(
            f"Preventive rule '{rule_id}' has invalid category '{category}'. Allowed: {sorted(VALID_RULE_CATEGORIES)}."
        )

    sex = str(rule.get("sex") or "").strip().lower()
    if sex not in VALID_SEX_FILTERS:
        raise ValueError(
            f"Preventive rule '{rule_id}' has invalid sex '{sex}'. Allowed: {sorted(VALID_SEX_FILTERS)}."
        )

    schedule_variant = str(rule.get("schedule_variant") or "").strip().lower()
    if schedule_variant not in VALID_SCHEDULE_VARIANTS:
        raise ValueError(
            f"Preventive rule '{rule_id}' has invalid schedule_variant '{schedule_variant}'. Allowed: {sorted(VALID_SCHEDULE_VARIANTS)}."
        )

    try:
        min_age = int(rule["target_age_min_months"])
        max_age = int(rule["target_age_max_months"])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Preventive rule '{rule_id}' age bounds must be integers.") from exc

    if min_age < 0 or max_age < min_age:
        raise ValueError(
            f"Preventive rule '{rule_id}' has invalid age range: {min_age}..{max_age} months."
        )

    interval_raw = rule.get("interval_months")
    interval_months: Optional[int] = int(interval_raw) if interval_raw is not None else None

    codes_raw = rule.get("codes")
    if not isinstance(codes_raw, list) or not codes_raw:
        raise ValueError(f"Preventive rule '{rule_id}' must declare a non-empty list of clinical 'codes'.")
    codes = [str(c).strip() for c in codes_raw if str(c).strip()]

    clinical_summary = str(rule.get("clinical_summary") or "").strip()
    if not clinical_summary:
        raise ValueError(f"Preventive rule '{rule_id}' has empty 'clinical_summary'.")

    return {
        "id": rule_id,
        "title": title,
        "category": category,
        "target_age_min_months": min_age,
        "target_age_max_months": max_age,
        "sex": sex,
        "schedule_variant": schedule_variant,
        "interval_months": interval_months,
        "codes": codes,
        "clinical_summary": clinical_summary,
        "source": str(rule["source"]).strip(),
        "citation_url": citation_url,
        "reviewed_by": str(rule["reviewed_by"]).strip(),
        "reviewed_at": str(rule["reviewed_at"]).strip(),
    }


def load_preventive_rules(
    skills_dir: Optional[Union[Path, str]] = None,
    yaml_paths: Optional[Sequence[Union[Path, str]]] = None,
) -> List[Dict[str, Any]]:
    """Loads and validates all preventive care rules from YAML rule packs.

    Args:
        skills_dir: Optional root directory containing `preventive-care/references/*.yaml`.
        yaml_paths: Optional explicit sequence of YAML file paths to load and validate.

    Returns:
        List of validated rule dictionaries.

    Raises:
        ValueError: If any rule lacks mandatory citation or structural fields, or if duplicate IDs exist.
    """
    paths = [Path(p) for p in yaml_paths] if yaml_paths is not None else _resolve_default_yaml_paths(skills_dir)

    validated_rules: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for path in paths:
        raw_text = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
        if parsed is None:
            raise ValueError(f"Empty YAML rule pack in {path.name}.")

        if isinstance(parsed, dict):
            raw_rules = parsed.get("rules")
        elif isinstance(parsed, list):
            raw_rules = parsed
        else:
            raise ValueError(f"Invalid YAML root structure in {path.name}.")

        if not isinstance(raw_rules, list) or not raw_rules:
            raise ValueError(f"No rules list found in {path.name}.")

        for raw_rule in raw_rules:
            clean_rule = validate_preventive_rule(raw_rule, source_file=path.name)
            if clean_rule["id"] in seen_ids:
                raise ValueError(f"Duplicate preventive rule ID '{clean_rule['id']}' in {path.name}.")
            seen_ids.add(clean_rule["id"])
            validated_rules.append(clean_rule)

    return validated_rules


def calculate_age_months(
    date_of_birth: Optional[str],
    reference_date: Optional[Union[datetime, date]] = None,
) -> int:
    """Calculates age in months from YYYY-MM-DD date_of_birth.

    Defaults to 420 months (35 years) when date_of_birth is None or empty.
    """
    if not date_of_birth or not isinstance(date_of_birth, str) or not date_of_birth.strip():
        return DEFAULT_ADULT_AGE_MONTHS

    clean_dob = date_of_birth.strip()
    try:
        if "T" in clean_dob:
            dob_date = datetime.fromisoformat(clean_dob).date()
        else:
            dob_date = datetime.strptime(clean_dob[:10], "%Y-%m-%d").date()
    except Exception:
        return DEFAULT_ADULT_AGE_MONTHS

    if reference_date is None:
        ref_date = datetime.now(timezone.utc).date()
    elif isinstance(reference_date, datetime):
        ref_date = reference_date.date()
    else:
        ref_date = reference_date

    months = (ref_date.year - dob_date.year) * 12 + (ref_date.month - dob_date.month)
    if ref_date.day < dob_date.day:
        months -= 1
    return max(0, months)


def _extract_resource_codes(data: Any) -> Set[str]:
    """Extracts LOINC, CVX, and CPT clinical codes from a HealthResource JSON payload."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return set()
    if not isinstance(data, dict):
        return set()

    codes: Set[str] = set()

    # Direct convenience keys
    for key in ("code_value", "cvx_code", "loinc_code", "cpt_code"):
        val = data.get(key)
        if val is not None and str(val).strip():
            codes.add(str(val).strip())

    if isinstance(data.get("codes"), list):
        for c in data["codes"]:
            if c is not None and str(c).strip():
                codes.add(str(c).strip())

    # FHIR CodeableConcept structures: code.coding, vaccineCode.coding
    for concept_key in ("code", "vaccineCode", "medicationCodeableConcept"):
        concept = data.get(concept_key)
        if isinstance(concept, dict):
            if concept.get("code") is not None:
                codes.add(str(concept["code"]).strip())
            coding_list = concept.get("coding")
            if isinstance(coding_list, list):
                for item in coding_list:
                    if isinstance(item, dict) and item.get("code") is not None:
                        codes.add(str(item["code"]).strip())
        elif isinstance(concept, str) and concept.strip():
            codes.add(concept.strip())

    # FHIR Observation components
    components = data.get("component")
    if isinstance(components, list):
        for comp in components:
            if isinstance(comp, dict):
                comp_code = comp.get("code")
                if isinstance(comp_code, dict):
                    for item in comp_code.get("coding") or []:
                        if isinstance(item, dict) and item.get("code") is not None:
                            codes.add(str(item["code"]).strip())

    return codes


async def get_profile_schedule_source(
    session: Optional[AsyncSession],
    profile_id: str,
) -> str:
    """Resolves the active pediatric immunisation schedule source ('aap_2026' or 'cdc') for a profile."""
    clean_id = (profile_id or "").strip()
    if not clean_id:
        return "aap_2026"

    if session is not None:
        setting_key = f"profile.{clean_id}.preventive_schedule_source"
        stmt = select(SystemSetting).where(SystemSetting.key == setting_key)
        res = await session.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting is not None:
            try:
                val = setting.get_value()
                if isinstance(val, str) and val in VALID_SCHEDULE_SOURCES:
                    _profile_schedule_sources[clean_id] = val
                    return val
            except Exception:
                pass

    if clean_id in _profile_schedule_sources:
        return _profile_schedule_sources[clean_id]

    if session is not None:
        rec_stmt = (
            select(PreventiveRecord.schedule_source)
            .where(PreventiveRecord.profile_id == clean_id)
            .order_by(PreventiveRecord.updated_at.desc())
            .limit(1)
        )
        rec_res = await session.execute(rec_stmt)
        rec_source = rec_res.scalar_one_or_none()
        if isinstance(rec_source, str) and rec_source in VALID_SCHEDULE_SOURCES:
            return rec_source

    return "aap_2026"


async def set_profile_schedule_source(
    session: Optional[AsyncSession],
    profile_id: str,
    schedule_source: str,
    actor_user_id: Optional[str] = None,
) -> str:
    """Updates and persists the profile's immunisation schedule source ('aap_2026' or 'cdc')."""
    clean_source = (schedule_source or "").strip().lower()
    if clean_source not in VALID_SCHEDULE_SOURCES:
        raise ValueError(
            f"Invalid schedule_source '{schedule_source}'. Permitted values: 'aap_2026', 'cdc'."
        )

    clean_id = (profile_id or "").strip()
    if not clean_id:
        raise ValueError("profile_id is required.")

    _profile_schedule_sources[clean_id] = clean_source

    if session is not None:
        now_utc = datetime.now(timezone.utc)
        setting_key = f"profile.{clean_id}.preventive_schedule_source"
        stmt = select(SystemSetting).where(SystemSetting.key == setting_key)
        res = await session.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting is None:
            setting = SystemSetting(
                key=setting_key,
                value_json=json.dumps(clean_source),
                is_secret=False,
                updated_at=now_utc,
                updated_by=actor_user_id,
            )
            session.add(setting)
        else:
            setting.set_value(clean_source)
            setting.updated_at = now_utc
            setting.updated_by = actor_user_id

        # Synchronize existing PreventiveRecord rows for this profile
        rec_stmt = select(PreventiveRecord).where(PreventiveRecord.profile_id == clean_id)
        rec_res = await session.execute(rec_stmt)
        for rec in rec_res.scalars().all():
            rec.schedule_source = clean_source
            rec.updated_at = now_utc

        await session.commit()

        resolved_actor_id = await _resolve_actor_user_id(session, clean_id, actor_user_id)
        try:
            await record_audit(
                {
                    "profile_id": clean_id,
                    "action": "update_schedule_source",
                    "tool": "update_preventive_settings",
                    "risk": "write_local",
                    "external_ref": f"profile:{clean_id}:preventive_settings",
                    "details": {"schedule_source": clean_source},
                },
                actor_user_id=resolved_actor_id,
                risk="write_local",
                db=session,
            )
        except Exception as err:
            logger.debug("Audit logging failed for schedule_source update: %s", err)

    return clean_source


# Alias for convenience
update_schedule_source = set_profile_schedule_source


async def evaluate_preventive_care(
    session: AsyncSession,
    profile: Union[Profile, str],
    *,
    schedule_source: Optional[str] = None,
    sex: Optional[str] = None,
    category: Optional[str] = None,
    skills_dir: Optional[Union[Path, str]] = None,
    reference_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluates preventive care screenings and immunisations for a Profile.

    Combines cited YAML rules, age in months (defaulting to 35y / 420m if DOB is None),
    schedule variant ('aap_2026' or 'cdc'), matching HealthResource records, and
    persisted PreventiveRecord status overrides.
    """
    if isinstance(profile, str):
        stmt = select(Profile).where(Profile.id == profile.strip())
        res = await session.execute(stmt)
        profile_obj = res.scalar_one_or_none()
        if profile_obj is None:
            raise ValueError(f"Profile '{profile}' not found.")
    else:
        profile_obj = profile

    now_utc = reference_date or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    # 1. Resolve schedule_source
    if schedule_source is not None and str(schedule_source).strip():
        active_source = str(schedule_source).strip().lower()
        if active_source not in VALID_SCHEDULE_SOURCES:
            raise ValueError(
                f"Invalid schedule_source '{schedule_source}'. Permitted: 'aap_2026', 'cdc'."
            )
    else:
        active_source = await get_profile_schedule_source(session, profile_obj.id)

    # 2. Compute age in months
    age_months = calculate_age_months(profile_obj.date_of_birth, reference_date=now_utc)
    is_pediatric = age_months < PEDIATRIC_CUTOFF_MONTHS

    # 3. Resolve optional sex filter
    raw_sex = sex or getattr(profile_obj, "sex", None) or getattr(profile_obj, "gender", None)
    clean_sex: Optional[str] = None
    if raw_sex and isinstance(raw_sex, str):
        s_norm = raw_sex.strip().lower()
        if s_norm in ("female", "f", "woman", "girl"):
            clean_sex = "female"
        elif s_norm in ("male", "m", "man", "boy"):
            clean_sex = "male"

    clean_category = category.strip().lower() if category and category.strip() else None

    # 4. Load validated YAML rules
    rules = load_preventive_rules(skills_dir=skills_dir)

    # 5. Fetch active HealthResources for code matching
    hr_stmt = (
        select(HealthResource)
        .where(
            HealthResource.profile_id == profile_obj.id,
            HealthResource.status == "active",
        )
        .order_by(HealthResource.effective_at.desc())
    )
    hr_res = await session.execute(hr_stmt)
    health_resources = list(hr_res.scalars().all())

    # Map code -> most recent HealthResource
    code_to_resource: Dict[str, HealthResource] = {}
    for hr in health_resources:
        rtype = (hr.resource_type or "").strip().lower()
        if rtype not in ("immunization", "observation", "procedure", "diagnostic_report", "diagnosticreport"):
            continue
        for code in _extract_resource_codes(hr.data):
            if code not in code_to_resource:
                code_to_resource[code] = hr

    # 6. Fetch persisted PreventiveRecord overrides
    pr_stmt = select(PreventiveRecord).where(PreventiveRecord.profile_id == profile_obj.id)
    pr_res = await session.execute(pr_stmt)
    records_by_rule: Dict[str, PreventiveRecord] = {
        rec.rule_id: rec for rec in pr_res.scalars().all()
    }

    # 7. Evaluate rules
    items: List[Dict[str, Any]] = []
    for rule in rules:
        # Age range check
        if not (rule["target_age_min_months"] <= age_months <= rule["target_age_max_months"]):
            continue

        # Schedule variant check
        if rule["schedule_variant"] not in ("all", active_source):
            continue

        # Sex check
        if clean_sex is not None and rule["sex"] not in ("any", clean_sex):
            continue

        # Category check
        if clean_category is not None and rule["category"] != clean_category:
            continue

        rule_id = rule["id"]
        override_rec = records_by_rule.get(rule_id)

        # Check HealthResource match
        matched_hr: Optional[HealthResource] = None
        for code in rule["codes"]:
            if code in code_to_resource:
                candidate_hr = code_to_resource[code]
                eff_at = candidate_hr.effective_at
                if eff_at is not None and eff_at.tzinfo is None:
                    eff_at = eff_at.replace(tzinfo=timezone.utc)
                interval_m = rule["interval_months"]
                if interval_m is None or eff_at is None:
                    matched_hr = candidate_hr
                    break
                cutoff_dt = now_utc - timedelta(days=interval_m * 30)
                if eff_at >= cutoff_dt:
                    matched_hr = candidate_hr
                    break

        if override_rec is not None:
            resolved_status = override_rec.status
            completed_dt = override_rec.completed_at or (matched_hr.effective_at if matched_hr else None)
            notes_val = override_rec.notes
            rec_id = override_rec.id
        elif matched_hr is not None:
            resolved_status = "completed"
            completed_dt = matched_hr.effective_at
            notes_val = None
            rec_id = None
        else:
            resolved_status = "due"
            completed_dt = None
            notes_val = None
            rec_id = None

        framing = PEDIATRIC_FRAMING if is_pediatric or rule["category"] in ("immunisation", "well_visit") else ADULT_FRAMING

        items.append({
            "id": rule_id,
            "rule_id": rule_id,
            "record_id": rec_id,
            "title": rule["title"],
            "category": rule["category"],
            "status": resolved_status,
            "framing": framing,
            "clinical_summary": rule["clinical_summary"],
            "target_age_min_months": rule["target_age_min_months"],
            "target_age_max_months": rule["target_age_max_months"],
            "sex": rule["sex"],
            "schedule_variant": rule["schedule_variant"],
            "schedule_source": active_source,
            "interval_months": rule["interval_months"],
            "codes": rule["codes"],
            "source": rule["source"],
            "citation_url": rule["citation_url"],
            "reviewed_by": rule["reviewed_by"],
            "reviewed_at": rule["reviewed_at"],
            "completed_at": completed_dt.isoformat() if completed_dt else None,
            "notes": notes_val,
            "matched_resource_id": matched_hr.id if matched_hr else None,
        })

    return {
        "profile_id": profile_obj.id,
        "age_months": age_months,
        "is_pediatric": is_pediatric,
        "schedule_source": active_source,
        "items": items,
        "total": len(items),
        "due_count": sum(1 for i in items if i["status"] == "due"),
        "completed_count": sum(1 for i in items if i["status"] == "completed"),
        "disclaimer": (
            f"{PEDIATRIC_FRAMING}."
            if is_pediatric
            else f"Informational preventive screening summary only. {ADULT_FRAMING}."
        ),
    }


async def update_preventive_record(
    session: AsyncSession,
    profile_id: str,
    rule_id: str,
    status: str,
    *,
    notes: Optional[str] = None,
    completed_at: Optional[Union[datetime, str]] = None,
    schedule_source: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> PreventiveRecord:
    """Creates or updates a PreventiveRecord status override for a profile and records an audit event."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    clean_rule_id = (rule_id or "").strip()
    if not clean_rule_id:
        raise ValueError("rule_id is required.")

    clean_status = (status or "").strip().lower()
    if clean_status not in VALID_PREVENTIVE_STATUSES:
        raise ValueError(
            f"Invalid preventive status '{status}'. Permitted: {sorted(VALID_PREVENTIVE_STATUSES)}."
        )

    if schedule_source is not None and str(schedule_source).strip():
        clean_sched = str(schedule_source).strip().lower()
        if clean_sched not in VALID_SCHEDULE_SOURCES:
            raise ValueError(
                f"Invalid schedule_source '{schedule_source}'. Permitted: 'aap_2026', 'cdc'."
            )
    else:
        clean_sched = await get_profile_schedule_source(session, clean_profile_id)

    now_utc = datetime.now(timezone.utc)
    comp_dt: Optional[datetime] = None
    if completed_at is not None:
        if isinstance(completed_at, datetime):
            comp_dt = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
        elif isinstance(completed_at, str) and completed_at.strip():
            parsed_dt = datetime.fromisoformat(completed_at.strip())
            comp_dt = parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)
    elif clean_status == "completed":
        comp_dt = now_utc

    stmt = select(PreventiveRecord).where(
        PreventiveRecord.profile_id == clean_profile_id,
        PreventiveRecord.rule_id == clean_rule_id,
    )
    res = await session.execute(stmt)
    record = res.scalar_one_or_none()

    if record is None:
        record = PreventiveRecord(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            rule_id=clean_rule_id,
            status=clean_status,
            completed_at=comp_dt,
            notes=notes,
            schedule_source=clean_sched,
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(record)
    else:
        record.status = clean_status
        if completed_at is not None or clean_status == "completed":
            record.completed_at = comp_dt
        elif clean_status in ("due", "not_applicable", "declined") and completed_at is None:
            record.completed_at = None
        if notes is not None:
            record.notes = notes
        if schedule_source is not None:
            record.schedule_source = clean_sched
        record.updated_at = now_utc

    resolved_actor_id = await _resolve_actor_user_id(session, clean_profile_id, actor_user_id)
    audit_rec = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=resolved_actor_id,
        principal="user",
        event="tool",
        tool="update_preventive_status",
        risk="write_local",
        decision="allow",
        external_ref=f"preventive_record:{record.id}",
        detail_redacted=json.dumps({
            "rule_id": clean_rule_id,
            "status": clean_status,
            "schedule_source": record.schedule_source,
        }),
    )
    session.add(audit_rec)
    await session.commit()
    await session.refresh(record)

    return record


async def create_preventive_action(
    session: AsyncSession,
    profile_id: str,
    rule_id: str,
    action_type: Literal["reminder", "prep_question"],
    *,
    due_at: Optional[Union[datetime, str]] = None,
    appointment_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    skills_dir: Optional[Union[Path, str]] = None,
) -> Dict[str, Any]:
    """Converts a preventive care item into a Reminder or Appointment prep question (E6.3)."""
    clean_profile_id = (profile_id or "").strip()
    if not clean_profile_id:
        raise ValueError("profile_id is required.")

    clean_rule_id = (rule_id or "").strip()
    if not clean_rule_id:
        raise ValueError("rule_id is required.")

    clean_action = (action_type or "").strip().lower()
    if clean_action not in ("reminder", "prep_question"):
        raise ValueError(
            f"Invalid action_type '{action_type}'. Permitted: 'reminder', 'prep_question'."
        )

    # Lookup rule metadata if available
    rules_map = {r["id"]: r for r in load_preventive_rules(skills_dir=skills_dir)}
    rule = rules_map.get(clean_rule_id)
    rule_title = rule["title"] if rule else f"Preventive Screening ({clean_rule_id})"
    rule_summary = (
        rule["clinical_summary"]
        if rule
        else f"Preventive item {clean_rule_id}. Discuss with your clinician."
    )
    rule_source = rule["source"] if rule else "Clinical Guideline"

    now_utc = datetime.now(timezone.utc)
    resolved_actor_id = await _resolve_actor_user_id(session, clean_profile_id, actor_user_id)

    if clean_action == "reminder":
        if due_at is not None:
            if isinstance(due_at, datetime):
                due_dt = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
            else:
                parsed = datetime.fromisoformat(str(due_at).strip())
                due_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        else:
            due_dt = now_utc + timedelta(days=7)

        rem_id = str(uuid.uuid4())
        reminder = Reminder(
            id=rem_id,
            profile_id=clean_profile_id,
            title=f"Preventive care: {rule_title}",
            description=f"{rule_summary} (Source: {rule_source})",
            category="prep",
            timezone="UTC",
            next_due_at=due_dt.astimezone(timezone.utc),
            status="pending",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(reminder)

        job = Job(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            kind="reminder",
            payload=json.dumps({"reminder_id": rem_id, "rule_id": clean_rule_id}),
            timezone="UTC",
            next_run_at=due_dt.astimezone(timezone.utc),
            status="pending",
            idempotency_key=f"reminder:{rem_id}",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(job)

        ext_ref = f"reminder:{rem_id}"
        audit_rec = AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now_utc,
            profile_id=clean_profile_id,
            actor_user_id=resolved_actor_id,
            principal="user",
            event="tool",
            tool="create_preventive_action",
            risk="write_local",
            decision="allow",
            external_ref=ext_ref,
            detail_redacted=json.dumps({
                "action_type": "reminder",
                "rule_id": clean_rule_id,
                "reminder_id": rem_id,
            }),
        )
        session.add(audit_rec)
        await session.commit()

        return {
            "action_type": "reminder",
            "rule_id": clean_rule_id,
            "title": reminder.title,
            "reminder_id": rem_id,
            "next_due_at": reminder.next_due_at.isoformat(),
            "category": reminder.category,
            "external_ref": ext_ref,
        }

    # action_type == "prep_question"
    question_line = f"- Ask clinician about {rule_title} ({rule_source}): {rule_summary}"

    target_appt: Optional[Appointment] = None
    if appointment_id and appointment_id.strip():
        appt_stmt = select(Appointment).where(
            Appointment.id == appointment_id.strip(),
            Appointment.profile_id == clean_profile_id,
        )
        appt_res = await session.execute(appt_stmt)
        target_appt = appt_res.scalar_one_or_none()
        if target_appt is None:
            raise ValueError(
                f"Appointment '{appointment_id}' not found for profile '{clean_profile_id}'."
            )
    else:
        upcoming_stmt = (
            select(Appointment)
            .where(
                Appointment.profile_id == clean_profile_id,
                Appointment.status.in_(["requested", "scheduled", "confirmed"]),
            )
            .order_by(Appointment.start_time.asc())
            .limit(1)
        )
        upcoming_res = await session.execute(upcoming_stmt)
        target_appt = upcoming_res.scalar_one_or_none()

    if target_appt is not None:
        existing_notes = (target_appt.preparation_notes or "").strip()
        if existing_notes:
            target_appt.preparation_notes = f"{existing_notes}\n{question_line}"
        else:
            target_appt.preparation_notes = question_line
        target_appt.updated_at = now_utc

        ext_ref = f"appointment:{target_appt.id}"
        audit_rec = AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now_utc,
            profile_id=clean_profile_id,
            actor_user_id=resolved_actor_id,
            principal="user",
            event="tool",
            tool="create_preventive_action",
            risk="write_local",
            decision="allow",
            external_ref=ext_ref,
            detail_redacted=json.dumps({
                "action_type": "prep_question",
                "rule_id": clean_rule_id,
                "appointment_id": target_appt.id,
            }),
        )
        session.add(audit_rec)
        await session.commit()

        return {
            "action_type": "prep_question",
            "rule_id": clean_rule_id,
            "appointment_id": target_appt.id,
            "note_id": None,
            "question": question_line,
            "preparation_notes": target_appt.preparation_notes,
            "external_ref": ext_ref,
        }

    # No upcoming appointment: create a question Note
    note_id = str(uuid.uuid4())
    note = Note(
        id=note_id,
        type="question",
        user_id=resolved_actor_id,
        profile_id=clean_profile_id,
        slug=f"preventive-question-{clean_rule_id}",
        title=f"Visit Question: {rule_title}",
        content=question_line,
        tags_json=json.dumps(["preventive", clean_rule_id]),
        created_at=now_utc,
        updated_at=now_utc,
    )
    session.add(note)

    ext_ref = f"note:{note_id}"
    audit_rec = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=resolved_actor_id,
        principal="user",
        event="tool",
        tool="create_preventive_action",
        risk="write_local",
        decision="allow",
        external_ref=ext_ref,
        detail_redacted=json.dumps({
            "action_type": "prep_question",
            "rule_id": clean_rule_id,
            "note_id": note_id,
        }),
    )
    session.add(audit_rec)
    await session.commit()

    return {
        "action_type": "prep_question",
        "rule_id": clean_rule_id,
        "appointment_id": None,
        "note_id": note_id,
        "question": question_line,
        "preparation_notes": question_line,
        "external_ref": ext_ref,
    }


__all__ = [
    "ADULT_FRAMING",
    "DEFAULT_ADULT_AGE_MONTHS",
    "PEDIATRIC_CUTOFF_MONTHS",
    "PEDIATRIC_FRAMING",
    "REQUIRED_CITATION_FIELDS",
    "REQUIRED_RULE_FIELDS",
    "VALID_PREVENTIVE_STATUSES",
    "VALID_SCHEDULE_SOURCES",
    "calculate_age_months",
    "create_preventive_action",
    "evaluate_preventive_care",
    "get_profile_schedule_source",
    "load_preventive_rules",
    "set_profile_schedule_source",
    "update_preventive_record",
    "update_schedule_source",
    "validate_preventive_rule",
]
