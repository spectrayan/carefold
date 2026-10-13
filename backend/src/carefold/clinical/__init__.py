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


