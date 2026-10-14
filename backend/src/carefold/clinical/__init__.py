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

"""Clinical domain logic, vitals normalization, BMI calculation, and trend analysis."""

from carefold.clinical.appointments import (
    AppointmentStatus,
    InvalidStatusTransitionError,
    VALID_STATUS_TRANSITIONS,
    evaluate_post_visit_transitions,
    generate_how_to_book_drafts,
    sweep_post_visit_transitions,
    validate_status_transition,
)
from carefold.clinical.bmi import (
    calculate_adult_bmi,
    calculate_adult_bmi_imperial,
    calculate_pediatric_bmi_percentile,
)
from carefold.clinical.notes import (
    AfterVisitSummary,
    ExtractedClinicalItem,
    NON_CLINICAL_DISCLAIMER,
    NoteType,
    VALID_NOTE_TYPES,
    extract_after_visit_summary,
    validate_note_type,
)
from carefold.clinical.prep_pack import (
    compile_clinical_prep_pack,
    compile_execution_plan,
    generate_and_persist_prep_pack,
    synthesize_doctor_questions,
)
from carefold.clinical.reminders import (
    SNOOZE_DELTAS,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar,
    handle_reminder_job,
)
from carefold.clinical.activity import (
    compute_is_undoable,
    format_audit_event_as_activity_item,
    get_profile_activity_timeline,
    synthesize_activity_summary,
)
from carefold.clinical.undo import (
    ActionNotUndoableError,
    AlreadyUndoneError,
    EntityNotFoundError,
    InvalidExternalRefError,
    UndoError,
    UndoWindowExpiredError,
    execute_single_click_undo,
    execute_single_click_undo_async,
)
from carefold.clinical.vitals import (
    LOINC_CODES,
    classify_blood_pressure,
    calculate_diurnal_bp_trends,
    normalize_fhir_vitals,
    parse_all_vitals_observations,
)

__all__ = [
    "ActionNotUndoableError",
    "AfterVisitSummary",
    "AlreadyUndoneError",
    "AppointmentStatus",
    "EntityNotFoundError",
    "ExtractedClinicalItem",
    "InvalidExternalRefError",
    "InvalidStatusTransitionError",
    "LOINC_CODES",
    "NON_CLINICAL_DISCLAIMER",
    "NoteType",
    "SNOOZE_DELTAS",
    "UndoError",
    "UndoWindowExpiredError",
    "VALID_NOTE_TYPES",
    "VALID_STATUS_TRANSITIONS",
    "advance_rrule_occurrence",
    "apply_reminder_snooze",
    "calculate_adult_bmi",
    "calculate_adult_bmi_imperial",
    "calculate_diurnal_bp_trends",
    "calculate_pediatric_bmi_percentile",
    "classify_blood_pressure",
    "coalesce_overdue_reminders",
    "compile_clinical_prep_pack",
    "compile_execution_plan",
    "compute_is_undoable",
    "evaluate_post_visit_transitions",
    "execute_single_click_undo",
    "execute_single_click_undo_async",
    "extract_after_visit_summary",
    "format_audit_event_as_activity_item",
    "generate_and_persist_prep_pack",
    "generate_how_to_book_drafts",
    "generate_ics_calendar",
    "get_profile_activity_timeline",
    "handle_reminder_job",
    "normalize_fhir_vitals",
    "parse_all_vitals_observations",
    "sweep_post_visit_transitions",
    "synthesize_activity_summary",
    "synthesize_doctor_questions",
    "validate_note_type",
    "validate_status_transition",
]


