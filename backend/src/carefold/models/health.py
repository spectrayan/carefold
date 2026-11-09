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

"""Health Pack ORM models (Requirement R3 & Step C3b).

Defines the 7 clinical and health navigation entities:
1. HealthResource (FHIR R4 Observations, metrics)
2. Appointment (clinical encounter booking and status)
3. PreventiveRecord (USPSTF screening & immunization schedules)
4. ImportBatch (staged and committed medical file imports)
5. SchoolForm (pediatric exam and school prefill forms)
6. SchoolIcsFeed (read-only school calendar subscription feeds)
7. CompanionDevice (paired mobile health companion devices)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from yarvelle_core.db.base import Base
from yarvelle_core.scope.mixin import ScopedMixin


def utc_now() -> datetime:
    """Returns the current UTC datetime."""
    return datetime.now(timezone.utc)


class HealthResource(Base, ScopedMixin):
    """Clinical health resource entity representing FHIR R4 Observations, vitals, and metrics."""

    __tablename__ = "health_resources"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "source_type", "source_ref", "source_id",
            name="uq_health_resources_source",
        ),
        Index("ix_health_resources_profile_type_effective", "profile_id", "resource_type", "effective_at"),
        Index("ix_health_resources_effective_at", "effective_at"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique health resource identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="FHIR resource category (e.g. observation)",
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Origin source type: manual, device, note_extracted",
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Source document reference identifier or external URI",
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External identifier in source system for idempotency",
    )
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 digest of clinical content",
    )
    data: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        doc="Complete FHIR R4 JSON representation of the resource",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="Status: active, amended, tombstone",
    )
    locale: Mapped[str] = mapped_column(
        String(16),
        default="en-US",
        server_default="en-US",
        nullable=False,
        doc="IETF BCP 47 locale tag of resource display narrative while codes stay language-neutral",
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Clinically relevant observation timestamp (UTC)",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="System ingestion or entry timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "recorded_at" not in kwargs:
            kwargs["recorded_at"] = utc_now()
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<HealthResource id={self.id!r} profile_id={self.profile_id!r} type={self.resource_type!r} status={self.status!r}>"


class Appointment(Base, ScopedMixin):
    """Clinical appointment and scheduling navigation entity."""

    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_start_time", "start_time"),
        Index("ix_appointments_status", "status"),
        Index("ix_appointments_profile_start", "profile_id", "start_time"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique appointment identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Appointment title or encounter description",
    )
    provider_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Healthcare provider or clinic name",
    )
    specialty: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        doc="Medical specialty (e.g. Cardiology, Endocrinology)",
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Physical clinic address, department, or telehealth URL",
    )
    clinic_phone: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Clinic or scheduler contact phone number",
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled appointment start timestamp (UTC)",
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled appointment end timestamp (UTC)",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
        doc="Local appointment IANA timezone identifier",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="scheduled",
        nullable=False,
        doc="Appointment status: requested, scheduled, confirmed, completed, cancelled",
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Chief complaint or purpose of appointment",
    )
    preparation_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Pre-visit preparation checklist or instructions",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")
    notes: Mapped[List[Any]] = relationship(
        "Note",
        primaryjoin="Appointment.id == foreign(Note.linked_appointment_id)",
        back_populates="appointment",
        passive_deletes=True,
    )



    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "timezone" not in kwargs:
            kwargs["timezone"] = "UTC"
        if "status" not in kwargs:
            kwargs["status"] = "scheduled"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Appointment id={self.id!r} profile_id={self.profile_id!r} title={self.title!r} status={self.status!r}>"


class PreventiveRecord(Base, ScopedMixin):
    """Per-profile preventive screening and immunisation tracking entity (AU-36)."""

    __tablename__ = "preventive_records"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "rule_id",
            name="uq_preventive_records_profile_rule",
        ),
        Index("ix_preventive_records_profile_status", "profile_id", "status"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique preventive record identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    rule_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Preventive rule identifier from YAML rule pack (e.g. uspstf-colorectal-screening)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="due",
        nullable=False,
        index=True,
        doc="Status: due, completed, not_applicable, declined",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when screening or immunisation was completed (UTC)",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional user or provider notes for this preventive item",
    )
    schedule_source: Mapped[str] = mapped_column(
        String(32),
        default="aap_2026",
        nullable=False,
        doc="Immunisation schedule source setting: aap_2026 or cdc",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "due"
        if "schedule_source" not in kwargs:
            kwargs["schedule_source"] = "aap_2026"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<PreventiveRecord id={self.id!r} profile_id={self.profile_id!r} "
            f"rule_id={self.rule_id!r} status={self.status!r}>"
        )


class ImportBatch(Base, ScopedMixin):
    """Clinical and wearable file import staging and provenance batch entity (AU-38)."""

    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_profile_status", "profile_id", "status"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique import batch identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    attachment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Source CAS attachment identifier (E13)",
    )
    format: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Import file format: fhir_r4, ccda, apple_health",
    )
    source_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable provenance origin (e.g. 'Apple Health Export', 'Epic C-CDA')",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="staged",
        nullable=False,
        index=True,
        doc="Lifecycle status: staged, committed, discarded",
    )
    summary_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized JSON summary of parsed counts, categories, and date ranges",
    )
    staged_records_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of normalized FHIR records staged for review-before-save",
    )
    committed_resource_ids_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
        doc="Serialized JSON array of health_resources IDs created on commit (for undo)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Staging creation timestamp (UTC)",
    )
    committed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Commit timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "staged"
        if "summary_json" not in kwargs:
            kwargs["summary_json"] = "{}"
        if "staged_records_json" not in kwargs:
            kwargs["staged_records_json"] = "[]"
        if "committed_resource_ids_json" not in kwargs:
            kwargs["committed_resource_ids_json"] = "[]"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<ImportBatch id={self.id!r} profile_id={self.profile_id!r} "
            f"format={self.format!r} status={self.status!r}>"
        )


class SchoolForm(Base, ScopedMixin):
    """Pediatric and school health form tracking and draft prefill entity (AU-39)."""

    __tablename__ = "school_forms"
    __table_args__ = (
        Index("ix_school_forms_profile_status", "profile_id", "status"),
        Index("ix_school_forms_expires_at", "expires_at"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique school form identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    attachment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional linked CAS attachment ID for the uploaded PDF/image form",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Form display title (e.g. 'Annual School Physical & Immunization Form')",
    )
    school_or_camp_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="School, daycare, or camp institution name",
    )
    form_type: Mapped[str] = mapped_column(
        String(64),
        default="general",
        nullable=False,
        doc="Form classification: physical, immunization, medication_authorization, sports_clearance, general",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Form expiration or renewal due date (UTC)",
    )
    reminder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("reminders.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated renewal reminder ID (AU-28)",
    )
    prefill_draft_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Serialized JSON of compiled draft prefill fields from profile records",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional notes or instructions for the school health form",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        nullable=False,
        index=True,
        doc="Lifecycle status: draft, active, expired, archived",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "institution_name" in kwargs and "school_or_camp_name" not in kwargs:
            kwargs["school_or_camp_name"] = kwargs.pop("institution_name")
        else:
            kwargs.pop("institution_name", None)
        kwargs.pop("issued_at", None)
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "form_type" not in kwargs:
            kwargs["form_type"] = "general"
        if "prefill_draft_json" not in kwargs:
            kwargs["prefill_draft_json"] = "{}"
        if "status" not in kwargs:
            kwargs["status"] = "draft"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def institution_name(self) -> Optional[str]:
        return self.school_or_camp_name

    @institution_name.setter
    def institution_name(self, value: Optional[str]) -> None:
        self.school_or_camp_name = value

    def __repr__(self) -> str:
        return (
            f"<SchoolForm id={self.id!r} profile_id={self.profile_id!r} "
            f"title={self.title!r} status={self.status!r}>"
        )


class SchoolIcsFeed(Base, ScopedMixin):
    """Per-child read-only school calendar ICS subscription feed (AU-61 / E4.4)."""

    __tablename__ = "school_ics_feeds"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique school ICS feed identifier (UUID v4 string)",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced child/student Profile identifier",
    )
    label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="School or calendar feed display name (e.g. 'Oakridge Elementary Calendar')",
    )
    feed_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        doc="Public HTTPS/webcal .ics subscription URL",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        index=True,
        doc="Feed sync status: active, paused, error",
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last successful feed synchronization timestamp (UTC)",
    )
    events_synced: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Count of calendar events synchronized from this feed",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Redacted error message if last sync failed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "status" not in kwargs:
            kwargs["status"] = "active"
        if "events_synced" not in kwargs:
            kwargs["events_synced"] = 0
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<SchoolIcsFeed id={self.id!r} profile_id={self.profile_id!r} "
            f"label={self.label!r} status={self.status!r}>"
        )


class CompanionDevice(Base):
    """Paired iOS companion device with pinned TLS certificate fingerprint and scoped profile permissions (AU-62)."""

    __tablename__ = "companion_devices"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique companion device identifier (UUID v4 string)",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner User identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Scoped Profile identifier",
    )
    device_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable device label (e.g. 'Priya iPhone 16 Pro')",
    )
    platform: Mapped[str] = mapped_column(
        String(32),
        default="ios",
        nullable=False,
        doc="Companion platform ('ios' in v1)",
    )
    pairing_code_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 digest of one-time pairing code (cleared once paired)",
    )
    token_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="SHA-256 digest of issued companion device bearer token",
    )
    cert_fingerprint_sha256: Mapped[str] = mapped_column(
        String(95),
        nullable=False,
        doc="Pinned TLS server certificate SHA-256 fingerprint",
    )
    allowed_categories_json: Mapped[str] = mapped_column(
        Text,
        default='["vitals", "clinical_records", "reminders"]',
        nullable=False,
        doc="Serialized JSON array of consented companion sync categories",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_pair",
        nullable=False,
        index=True,
        doc="Device status: pending_pair, active, revoked",
    )
    paired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when QR pairing completed (UTC)",
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last companion sync or notification poll timestamp (UTC)",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Pairing code or device token expiration timestamp (UTC)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="Creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="Last modification timestamp (UTC)",
    )

    profile: Mapped[Any] = relationship("Profile")

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "allowed_categories" in kwargs and "allowed_categories_json" not in kwargs:
            kwargs["allowed_categories_json"] = json.dumps(list(kwargs.pop("allowed_categories")))
        elif "allowed_categories" in kwargs:
            kwargs.pop("allowed_categories")
        if "allowed_categories_json" not in kwargs:
            kwargs["allowed_categories_json"] = '["vitals", "clinical_records", "reminders"]'
        if "status" not in kwargs:
            kwargs["status"] = "pending_pair"
        if "platform" not in kwargs:
            kwargs["platform"] = "ios"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    @property
    def allowed_categories(self) -> List[str]:
        try:
            return json.loads(self.allowed_categories_json or "[]")
        except Exception:
            return []

    @allowed_categories.setter
    def allowed_categories(self, value: List[str]) -> None:
        self.allowed_categories_json = json.dumps(list(value))

    def __repr__(self) -> str:
        return (
            f"<CompanionDevice id={self.id!r} profile_id={self.profile_id!r} "
            f"device_name={self.device_name!r} status={self.status!r}>"
        )


class HealthResourceVersion(Base, ScopedMixin):
    """Immutable FHIR R4 version snapshot for a HealthResource (#282)."""

    __tablename__ = "health_resource_versions"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "version_id",
            name="uq_health_resource_versions_resource_version",
        ),
        Index(
            "ix_health_resource_versions_profile_scope_type",
            "profile_id",
            "scope",
            "resource_type",
        ),
        Index(
            "ix_health_resource_versions_resource_version",
            "resource_id",
            "version_id",
        ),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique version snapshot identifier (UUID v4 string)",
    )
    resource_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("health_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced current HealthResource identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="FHIR R4 resourceType for this snapshot",
    )
    version_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Monotonically increasing integer version number (1, 2, ...)",
    )
    operation: Mapped[str] = mapped_column(
        String(16),
        default="create",
        server_default="create",
        nullable=False,
        doc="Lifecycle operation: create, update, or delete",
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Deterministic SHA-256 hex digest of canonical clinical JSON content",
    )
    fhir_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        doc="Immutable versioned FHIR R4 JSON payload with meta.versionId and meta.lastUpdated",
    )
    source_batch_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional ImportBatch identifier that produced this version",
    )
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        doc="Optional user ID of the actor that committed this version",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="UTC timestamp when this version snapshot was recorded",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="UTC timestamp of last record metadata update",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "operation" not in kwargs:
            kwargs["operation"] = "create"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<HealthResourceVersion id={self.id!r} resource_id={self.resource_id!r} "
            f"version_id={self.version_id!r} operation={self.operation!r}>"
        )


class HealthResourceCoding(Base, ScopedMixin):
    """Multi-coding terminology index entry for a HealthResource (#282).

    Indexes structured `(element_path, system, code, display)` tuples (LOINC, SNOMED CT,
    RxNorm, ICD-10-CM, CVX, CPT, HL7 CodeSystems) without exposing free-text narratives.
    """

    __tablename__ = "health_resource_codings"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "element_path",
            "system",
            "code",
            name="uq_health_resource_codings_res_path_sys_code",
        ),
        Index(
            "ix_health_resource_codings_profile_sys_code",
            "profile_id",
            "system",
            "code",
        ),
        Index(
            "ix_health_resource_codings_profile_scope_code",
            "profile_id",
            "scope",
            "code",
        ),
        Index(
            "ix_health_resource_codings_profile_type_code",
            "profile_id",
            "resource_type",
            "code",
        ),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique coding index row identifier (UUID v4 string)",
    )
    resource_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("health_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced HealthResource identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    resource_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="FHIR R4 resourceType of the owning resource",
    )
    element_path: Mapped[str] = mapped_column(
        String(128),
        default="code",
        server_default="code",
        nullable=False,
        doc="FHIR element path of the CodeableConcept/Coding (e.g. code, component.code, category)",
    )
    system: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Terminology system URI (e.g. http://loinc.org, http://snomed.info/sct)",
    )
    code: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Terminology code string",
    )
    display: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Standardized coding display label (never free-text narrative)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="UTC timestamp when coding index row was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="UTC timestamp when coding index row was last updated",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "element_path" not in kwargs:
            kwargs["element_path"] = "code"
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<HealthResourceCoding id={self.id!r} resource_id={self.resource_id!r} "
            f"path={self.element_path!r} system={self.system!r} code={self.code!r}>"
        )


class HealthResourceReference(Base, ScopedMixin):
    """Directed FHIR R4 resource reference graph edge (#282).

    Captures outbound references (`subject`, `patient`, `encounter`, `performer`, `result`,
    `reasonReference`, etc.) between resources within a profile's clinical/paperwork graph.
    """

    __tablename__ = "health_resource_references"
    __table_args__ = (
        UniqueConstraint(
            "source_resource_id",
            "reference_field",
            "target_type",
            "target_id",
            "raw_reference",
            name="uq_health_resource_references_edge",
        ),
        Index(
            "ix_health_resource_refs_profile_target",
            "profile_id",
            "target_type",
            "target_id",
        ),
        Index(
            "ix_health_resource_refs_profile_scope_source",
            "profile_id",
            "scope",
            "source_resource_id",
        ),
        Index(
            "ix_health_resource_refs_target_resource_id",
            "target_resource_id",
        ),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique reference edge identifier (UUID v4 string)",
    )
    source_resource_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("health_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Source HealthResource identifier",
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Referenced Profile identifier (strictly scoped, non-nullable)",
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="FHIR R4 resourceType of the source resource",
    )
    reference_field: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="FHIR element path holding the reference (e.g. subject, encounter, result, performer)",
    )
    target_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Target FHIR R4 resourceType (e.g. Patient, Encounter, Observation, Practitioner)",
    )
    target_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Target logical FHIR ID or canonical profile ID",
    )
    target_resource_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("health_resources.id", ondelete="SET NULL"),
        nullable=True,
        doc="Resolved local HealthResource.id when the target resource exists in the same profile",
    )
    raw_reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Normalized or raw FHIR reference string (never free-text display)",
    )
    is_external: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="True when referencing an unresolved external URI or logical identifier",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        doc="UTC timestamp when reference edge was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        doc="UTC timestamp when reference edge was last updated",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "id" not in kwargs:
            kwargs["id"] = str(uuid.uuid4())
        if "is_external" not in kwargs:
            kwargs["is_external"] = False
        if "created_at" not in kwargs:
            kwargs["created_at"] = utc_now()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = utc_now()
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<HealthResourceReference id={self.id!r} source_resource_id={self.source_resource_id!r} "
            f"field={self.reference_field!r} target='{self.target_type}/{self.target_id}'>"
        )


from yarvelle_core.db.models import Note
from sqlalchemy.orm import synonym

if not hasattr(Note, "appointment"):
    Note.appointment = relationship(
        "Appointment",
        primaryjoin="foreign(Note.linked_appointment_id) == Appointment.id",
        back_populates="notes",
    )
    Note.linked_appointment = synonym("appointment")


__all__ = [
    "HealthResource",
    "HealthResourceVersion",
    "HealthResourceCoding",
    "HealthResourceReference",
    "Appointment",
    "PreventiveRecord",
    "ImportBatch",
    "SchoolForm",
    "SchoolIcsFeed",
    "CompanionDevice",
]
