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

"""Clinical Visit Prep Pack compiler and deterministic ExecutionPlan generator (AU-33, AU-34).

Delivers:
- Deterministic ExecutionPlan compilation for template card intents (visit_prep, log_vitals, remind_me)
- Clinical visit preparation dossier compilation blending vitals, medications, and questions
- Doctor question synthesis prioritizing clinical specialty guidelines and vitals status
- End-to-end prep pack generation with database persistence as a visit Note and search indexing
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.vitals import calculate_diurnal_bp_trends
from carefold.db.models import Appointment, HealthResource, Job, Note
from carefold.schemas.plan import AgentTask, ExecutionMode, ExecutionPlan

logger = logging.getLogger("carefold.clinical.prep_pack")

NON_CLINICAL_DISCLAIMER: str = (
    "*Disclaimer: Prepared with Carefold for patient empowerment. "
    "Extracted from your notes, not formal medical advice. "
    "Review with your healthcare provider.*"
)


def compile_execution_plan(intent: str, parameters: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
    """Deterministically compiles an ExecutionPlan for template plan cards (AU-33).

    Supported intents:
    - visit_prep: 4-step consultation preparation pipeline
    - log_vitals: 3-step vital sign observation logging pipeline
    - remind_me: 2-step temporal reminder scheduling pipeline

    Raises:
        ValueError: If an unknown intent is passed.
    """
    params = parameters or {}
    plan_id = str(uuid.uuid4())

    if intent == "visit_prep":
        steps = [
            {"step": 1, "tool": "search_records", "description": "Retrieve past clinical notes and diagnoses"},
            {"step": 2, "tool": "calculate_trends", "description": "Synthesize 30-day and 90-day vitals trends"},
            {"step": 3, "tool": "draft_questions", "description": "Prioritize 3-5 clinical questions for clinician"},
            {"step": 4, "tool": "generate_prep_pack", "description": "Compile formatted consultation prep dossier"},
        ]
        target_agent = "visit-steward"
        specialty = str(params.get("specialty", "")).strip().lower()
        if "cardio" in specialty:
            target_agent = "cardiology-guide"
        elif "pulmon" in specialty:
            target_agent = "pulmonology-guide"
        elif "endo" in specialty:
            target_agent = "endocrinology-guide"

        tasks = [
            AgentTask(
                agent_id=target_agent,
                task_description="Retrieve past clinical notes and diagnoses",
                instructions="tool: search_records",
                priority=1,
            ),
            AgentTask(
                agent_id=target_agent,
                task_description="Synthesize 30-day and 90-day vitals trends",
                instructions="tool: calculate_trends",
                priority=2,
                depends_on=["task_1"],
            ),
            AgentTask(
                agent_id=target_agent,
                task_description="Prioritize 3-5 clinical questions for clinician",
                instructions="tool: draft_questions",
                priority=3,
                depends_on=["task_2"],
            ),
            AgentTask(
                agent_id=target_agent,
                task_description="Compile formatted consultation prep dossier",
                instructions="tool: generate_prep_pack",
                priority=4,
                depends_on=["task_3"],
            ),
        ]
        target_agents = [target_agent]

    elif intent == "log_vitals":
        steps = [
            {"step": 1, "tool": "parse_observation", "description": "Normalize LOINC observation and units"},
            {"step": 2, "tool": "check_red_flags", "description": "Evaluate non-clinical boundary safety rules"},
            {"step": 3, "tool": "record_vitals", "description": "Persist Observation to health_resources store"},
        ]
        tasks = [
            AgentTask(
                agent_id="visit-steward",
                task_description="Normalize LOINC observation and units",
                instructions="tool: parse_observation",
                priority=1,
            ),
            AgentTask(
                agent_id="visit-steward",
                task_description="Evaluate non-clinical boundary safety rules",
                instructions="tool: check_red_flags",
                priority=2,
                depends_on=["task_1"],
            ),
            AgentTask(
                agent_id="visit-steward",
                task_description="Persist Observation to health_resources store",
                instructions="tool: record_vitals",
                priority=3,
                depends_on=["task_2"],
            ),
        ]
        target_agents = ["visit-steward"]

    elif intent == "remind_me":
        steps = [
            {"step": 1, "tool": "parse_rrule", "description": "Parse RFC 5545 recurrence and timezone"},
            {"step": 2, "tool": "create_reminder", "description": "Schedule recurring wall-clock reminder job"},
        ]
        tasks = [
            AgentTask(
                agent_id="records-coordinator",
                task_description="Parse RFC 5545 recurrence and timezone",
                instructions="tool: parse_rrule",
                priority=1,
            ),
            AgentTask(
                agent_id="records-coordinator",
                task_description="Schedule recurring wall-clock reminder job",
                instructions="tool: create_reminder",
                priority=2,
                depends_on=["task_1"],
            ),
        ]
        target_agents = ["records-coordinator"]

    else:
        raise ValueError(f"Unknown ExecutionPlan intent: '{intent}'")

    return ExecutionPlan(
        id=plan_id,
        intent=intent,
        parameters=params,
        steps=steps,
        status="compiled",
        mode=ExecutionMode.PIPELINE,
        target_agents=target_agents,
        tasks=tasks,
        reasoning=f"Deterministic template execution plan compiled for intent '{intent}'.",
    )


def synthesize_doctor_questions(
    specialty: Optional[str] = None,
    vitals_trends: Optional[Dict[str, Any]] = None,
    custom_questions: Optional[List[str]] = None,
) -> List[str]:
    """Synthesizes 3 to 5 high-yield clinical questions for the healthcare provider."""
    questions: List[str] = []
    seen: set[str] = set()

    # 1. Custom user questions prioritized first
    for q in custom_questions or []:
        cleaned = str(q).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            questions.append(cleaned)
            if len(questions) >= 5:
                return questions

    spec_clean = str(specialty or "").strip().lower()

    # 2. Vitals-driven questions
    if vitals_trends:
        t30 = vitals_trends.get("30_day", {})
        am_cls = t30.get("am", {}).get("classification")
        pm_cls = t30.get("pm", {}).get("classification")
        elevated_tiers = {"Elevated", "Stage 1", "Stage 2", "Hypertensive Crisis"}
        if am_cls in elevated_tiers or pm_cls in elevated_tiers:
            bp_q = "My home blood pressure readings have been elevated in recent logs. Do you recommend adjusting my medication dosage or timing?"
            if bp_q not in seen:
                seen.add(bp_q)
                questions.append(bp_q)
                if len(questions) >= 5:
                    return questions

    # 3. Specialty-driven questions
    specialty_bank: Dict[str, List[str]] = {
        "cardio": [
            "What is my target blood pressure range for home monitoring?",
            "Are there any warning signs or symptoms that should prompt immediate medical evaluation?",
            "Is it safe to continue my current physical activity and exercise routine?",
        ],
        "pulmon": [
            "How often should I be using my rescue inhaler versus daily controller medication?",
            "What peak flow reading or symptom changes indicate a flare-up?",
            "Are there environmental or seasonal triggers I should take precautions against?",
        ],
        "endo": [
            "What are my target fasting and post-meal blood glucose goals?",
            "How frequently should we monitor my A1c and renal function labs?",
            "What protocol should I follow if I experience hypoglycemia symptoms?",
        ],
        "gastro": [
            "Should I maintain a food and symptom journal to identify specific triggers?",
            "Are there dietary modifications or probiotics you recommend?",
            "What follow-up diagnostic tests or imaging might be indicated?",
        ],
        "general": [
            "What is the recommended treatment plan and expected recovery timeline?",
            "Are there potential side effects or drug interactions with my medications?",
            "When should I schedule my next follow-up appointment or lab test?",
        ],
    }

    matched_key = "general"
    for k in specialty_bank:
        if k in spec_clean:
            matched_key = k
            break

    for candidate in specialty_bank[matched_key]:
        if candidate not in seen:
            seen.add(candidate)
            questions.append(candidate)
            if len(questions) >= 5:
                break

    # If still fewer than 3, pull from general
    if len(questions) < 3 and matched_key != "general":
        for candidate in specialty_bank["general"]:
            if candidate not in seen:
                seen.add(candidate)
                questions.append(candidate)
                if len(questions) >= 3:
                    break

    return questions[:5]


def compile_clinical_prep_pack(
    reason_for_visit: str,
    symptoms: List[str],
    vitals_trends: Dict[str, Any],
    medications: List[str],
    allergies: List[str],
    doctor_questions: List[str],
    search_excerpts: List[str],
    specialty: Optional[str] = None,
    provider_name: Optional[str] = None,
    appointment_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Compiles a complete clinical consultation prep pack with Markdown & printable layout (AU-34)."""
    md_lines: List[str] = [
        "# Clinical Visit Preparation Dossier",
        f"**Chief Reason for Visit**: {reason_for_visit}",
    ]

    if provider_name:
        spec_text = f" ({specialty})" if specialty else ""
        md_lines.append(f"**Provider**: {provider_name}{spec_text}")
    elif specialty:
        md_lines.append(f"**Specialty**: {specialty}")

    if appointment_date:
        md_lines.append(f"**Scheduled Date**: {appointment_date}")

    # Section 1: Recent Symptoms Timeline
    md_lines.append("\n## 1. Recent Symptoms Timeline")
    clean_symptoms = [s.strip() for s in symptoms if s and s.strip()]
    if clean_symptoms:
        for s in clean_symptoms:
            md_lines.append(f"- {s}")
    else:
        md_lines.append("- No recent acute symptoms reported.")

    # Section 2: Vitals Trends Summary
    md_lines.append("\n## 2. Vitals Trends Summary")
    has_vitals = False
    if vitals_trends:
        t30 = vitals_trends.get("30_day", {})
        t30_am = t30.get("am", {})
        t30_pm = t30.get("pm", {})
        if t30_am.get("systolic") is not None and t30_am.get("diastolic") is not None:
            has_vitals = True
            md_lines.append(
                f"- **30-Day AM Average**: {t30_am['systolic']}/{t30_am['diastolic']} mmHg ({t30_am.get('classification', 'N/A')})"
            )
        if t30_pm.get("systolic") is not None and t30_pm.get("diastolic") is not None:
            has_vitals = True
            md_lines.append(
                f"- **30-Day PM Average**: {t30_pm['systolic']}/{t30_pm['diastolic']} mmHg ({t30_pm.get('classification', 'N/A')})"
            )

        t90 = vitals_trends.get("90_day", {})
        t90_am = t90.get("am", {})
        t90_pm = t90.get("pm", {})
        if t90_am.get("systolic") is not None and t90_am.get("diastolic") is not None:
            has_vitals = True
            md_lines.append(
                f"- **90-Day AM Average**: {t90_am['systolic']}/{t90_am['diastolic']} mmHg ({t90_am.get('classification', 'N/A')})"
            )
        if t90_pm.get("systolic") is not None and t90_pm.get("diastolic") is not None:
            has_vitals = True
            md_lines.append(
                f"- **90-Day PM Average**: {t90_pm['systolic']}/{t90_pm['diastolic']} mmHg ({t90_pm.get('classification', 'N/A')})"
            )

    if not has_vitals:
        md_lines.append("- No recent vitals recorded.")

    # Section 3: Active Medications & Allergies
    md_lines.append("\n## 3. Active Medications & Allergies")
    clean_meds = [m.strip() for m in medications if m and m.strip()]
    clean_allergies = [a.strip() for a in allergies if a and a.strip()]
    meds_text = ", ".join(clean_meds) if clean_meds else "None reported"
    allergies_text = ", ".join(clean_allergies) if clean_allergies else "No known drug allergies"
    md_lines.append(f"- **Medications**: {meds_text}")
    md_lines.append(f"- **Allergies**: {allergies_text}")

    # Section 4: Prioritized Doctor Questions
    md_lines.append("\n## 4. Prioritized Doctor Questions")
    clamped_questions = doctor_questions[:5]
    if clamped_questions:
        for idx, q in enumerate(clamped_questions, 1):
            md_lines.append(f"{idx}. {q}")
    else:
        md_lines.append("1. What are my primary treatment goals and next steps?")

    # Section 5: Relevant History from Prior Records (included if excerpts provided)
    clean_excerpts = [e.strip() for e in search_excerpts if e and e.strip()]
    if clean_excerpts:
        md_lines.append("\n## 5. Relevant History from Prior Records")
        for exc in clean_excerpts:
            md_lines.append(f"> {exc}")

    # Disclaimer
    md_lines.append(f"\n---\n{NON_CLINICAL_DISCLAIMER}")

    markdown_doc = "\n".join(md_lines)

    return {
        "title": f"Prep Pack: {reason_for_visit}",
        "markdown": markdown_doc,
        "questions_count": len(clamped_questions),
        "has_vitals_summary": has_vitals,
        "printable_html_ready": True,
        "metadata": {
            "reason_for_visit": reason_for_visit,
            "specialty": specialty,
            "provider_name": provider_name,
            "appointment_date": appointment_date,
            "questions_count": len(clamped_questions),
        },
    }


def _slugify(text: str) -> str:
    """Generates a URL-safe alphanumeric slug."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\s]", "", text.strip())
    slug = re.sub(r"\s+", "-", clean).lower()
    return slug[:64] or "consultation"


async def generate_and_persist_prep_pack(
    session: AsyncSession,
    profile_id: str,
    appointment_id: Optional[str] = None,
    specialty: Optional[str] = None,
    visit_reason: Optional[str] = None,
    doctor_questions: Optional[List[str]] = None,
    search_index: Optional[Any] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates a complete prep pack, persists it as a visit Note, and enqueues indexing."""
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string for fail-closed prep pack generation.")
    clean_profile_id = profile_id.strip()

    resolved_appointment: Optional[Appointment] = None
    if appointment_id:
        clean_appt_id = str(appointment_id).strip()
        appt_stmt = select(Appointment).where(
            Appointment.id == clean_appt_id,
            Appointment.profile_id == clean_profile_id,
        )
        res = await session.execute(appt_stmt)
        resolved_appointment = res.scalar_one_or_none()
        if resolved_appointment is None:
            raise ValueError(
                f"Appointment '{clean_appt_id}' not found for profile '{clean_profile_id}'."
            )

    # 1. Resolve reason, specialty, provider, date
    final_reason = (
        visit_reason
        or (resolved_appointment.reason if resolved_appointment and resolved_appointment.reason else None)
        or (resolved_appointment.title if resolved_appointment else None)
        or "General Consultation"
    ).strip()

    final_specialty = (
        specialty
        or (resolved_appointment.specialty if resolved_appointment else None)
    )

    provider_name = resolved_appointment.provider_name if resolved_appointment else None
    appointment_date = (
        resolved_appointment.start_time.isoformat()
        if resolved_appointment and resolved_appointment.start_time
        else None
    )

    # 2. Retrieve 90-day vitals observations & calculate trends
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    vitals_stmt = select(HealthResource).where(
        HealthResource.profile_id == clean_profile_id,
        HealthResource.resource_type == "observation",
        HealthResource.status != "tombstone",
        HealthResource.effective_at >= cutoff,
    ).order_by(HealthResource.effective_at.desc())

    vitals_res = await session.execute(vitals_stmt)
    hr_rows = vitals_res.scalars().all()
    readings: List[Dict[str, Any]] = []
    for hr in hr_rows:
        eff_iso = hr.effective_at.isoformat() if hasattr(hr.effective_at, "isoformat") else str(hr.effective_at)
        readings.append({"effective_at": eff_iso, "data": hr.data})

    vitals_trends: Dict[str, Any] = {}
    if readings:
        try:
            vitals_trends = calculate_diurnal_bp_trends(readings)
        except Exception as trend_err:
            logger.debug("calculate_diurnal_bp_trends error: %s", trend_err)

    # 3. Retrieve recent notes for symptoms, medications, allergies
    notes_stmt = select(Note).where(
        Note.profile_id == clean_profile_id,
    ).order_by(Note.updated_at.desc()).limit(15)
    notes_res = await session.execute(notes_stmt)
    recent_notes = notes_res.scalars().all()

    symptoms_list: List[str] = []
    medications_list: List[str] = []
    allergies_list: List[str] = []

    for n in recent_notes:
        if n.type == "symptom" and n.title:
            symptoms_list.append(n.title)
        content_lower = (n.content or "").lower()
        # Parse simple allergy or med mentions if tagged
        tags = n.get_tags()
        if "medication" in tags or "prescription" in tags:
            medications_list.append(n.title)
        if "allergy" in tags or "allergies" in tags:
            allergies_list.append(n.title)

    # 4. Search cognitive excerpts
    search_excerpts: List[str] = []
    try:
        idx = search_index
        if idx is None:
            from carefold.search.factory import get_search_index
            idx = get_search_index()
        if idx is not None:
            query_str = f"{final_reason} {final_specialty or ''}".strip()
            search_results = await asyncio.to_thread(
                idx.search,
                query=query_str,
                profile_id=clean_profile_id,
                limit=3,
            ) if not inspect.iscoroutinefunction(getattr(idx, "search", None)) else await idx.search(
                query=query_str,
                profile_id=clean_profile_id,
                limit=3,
            )
            for sr in search_results:
                text_snippet = getattr(sr, "snippet", None) or getattr(sr, "text", None) or str(sr)
                if text_snippet:
                    # Clean snippet
                    first_line = text_snippet.strip().splitlines()[0][:140]
                    search_excerpts.append(first_line)
    except Exception as search_err:
        logger.debug("Cognitive search lookup skipped during prep pack compilation: %s", search_err)

    # 5. Synthesize questions
    final_questions = synthesize_doctor_questions(
        specialty=final_specialty,
        vitals_trends=vitals_trends,
        custom_questions=doctor_questions,
    )

    # 6. Compile Markdown dossier
    compiled = compile_clinical_prep_pack(
        reason_for_visit=final_reason,
        symptoms=symptoms_list,
        vitals_trends=vitals_trends,
        medications=medications_list,
        allergies=allergies_list,
        doctor_questions=final_questions,
        search_excerpts=search_excerpts,
        specialty=final_specialty,
        provider_name=provider_name,
        appointment_date=appointment_date,
    )

    # 7. Persist Note
    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    base_slug = f"prep-pack-{_slugify(final_reason)}"
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    note = Note(
        id=note_id,
        type="visit",
        user_id=user_id,
        profile_id=clean_profile_id,
        slug=unique_slug,
        title=f"Prep Pack: {final_reason}",
        content=compiled["markdown"],
        tags_json=json.dumps(["prep_pack", (final_specialty or "general").lower(), "consultation"]),
        linked_appointment_id=appointment_id,
        created_at=now,
        updated_at=now,
    )
    session.add(note)

    # 8. Update Appointment preparation_notes if linked
    if resolved_appointment is not None:
        resolved_appointment.preparation_notes = f"Prep pack compiled: Note {note.id}"

    # 9. Enqueue index_doc Job
    content_hash = hashlib.sha256((note.content or "").encode("utf-8")).hexdigest()[:12]
    index_job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        kind="index_doc",
        payload=json.dumps({
            "document_id": note.id,
            "profile_id": clean_profile_id,
            "doc_type": "note",
        }),
        timezone="UTC",
        next_run_at=now,
        idempotency_key=f"index:note:{note.id}:{content_hash}",
        status="pending",
    )
    session.add(index_job)

    await session.commit()

    # 10. Record Audit Event for Undoability
    try:
        from carefold.audit.logger import record_audit
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "create",
                "tool": "generate_prep_pack",
                "risk": "write_local",
                "external_ref": f"note:{note.id}",
                "details": {
                    "note_id": note.id,
                    "title": note.title,
                    "appointment_id": appointment_id,
                },
            },
            actor_user_id=user_id or "user",
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed during prep pack persistence: %s", audit_err)

    return {
        "note_id": note.id,
        "appointment_id": appointment_id,
        "profile_id": clean_profile_id,
        "title": note.title,
        "markdown": compiled["markdown"],
        "questions_count": compiled["questions_count"],
        "has_vitals_summary": compiled["has_vitals_summary"],
        "printable_html_ready": True,
        "undo_reference": f"note:{note.id}",
    }


__all__ = [
    "NON_CLINICAL_DISCLAIMER",
    "compile_clinical_prep_pack",
    "compile_execution_plan",
    "generate_and_persist_prep_pack",
    "synthesize_doctor_questions",
]
