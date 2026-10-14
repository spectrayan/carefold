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

"""Carefold relational database layer with multi-dialect support (SQLite & PostgreSQL)."""

from carefold.db.base import Base
from carefold.db.models import (
    Agent,
    Appointment,
    Approval,
    Attachment,
    AuditEventRecord,
    ChatThread,
    CompanionDevice,
    Connection,
    ConsentGrant,
    Credential,
    EmailDraft,
    HealthResource,
    ImportBatch,
    Job,
    KnowledgeBase,
    McpToolPin,
    Note,
    PasswordReset,
    PreventiveRecord,
    Profile,
    ProfileAccess,
    ProfileConsent,
    ProfileKey,
    Reminder,
    Routine,
    SchoolForm,
    SchoolIcsFeed,
    Session,
    Skill,
    SyncRun,
    SystemSetting,
    User,
    ViewerInvite,
)
from carefold.db.session import (
    close_db,
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    normalize_database_url,
    reset_engine,
    resolve_database_url,
    sanitize_db_url,
)

__all__ = [
    "Base",
    "User",
    "Session",
    "PasswordReset",
    "SystemSetting",
    "Agent",
    "Skill",
    "KnowledgeBase",
    "Note",
    "Attachment",
    "AuditEventRecord",
    "ChatThread",
    "Profile",
    "ProfileAccess",
    "ProfileConsent",
    "ProfileKey",
    "Approval",
    "Job",
    "Connection",
    "Credential",
    "ConsentGrant",
    "SyncRun",
    "Routine",
    "McpToolPin",
    "EmailDraft",
    "SchoolIcsFeed",
    "CompanionDevice",
    "ViewerInvite",
    "HealthResource",
    "Appointment",
    "Reminder",
    "PreventiveRecord",
    "ImportBatch",
    "SchoolForm",
    "create_db_engine",
    "get_engine",
    "get_session_factory",
    "get_db",
    "init_db",
    "close_db",
    "reset_engine",
    "normalize_database_url",
    "sanitize_db_url",
    "resolve_database_url",
]
