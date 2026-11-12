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

"""Declarative SQLAlchemy models for Carefold (slim composition and re-exports).

Re-exports core models from `yarvelle_core.db.models` and health domain models
from `carefold.models.health`, dynamically attaching health relationships to
`Profile` for 100% backwards compatibility with tests and application code.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import foreign, relationship, synonym


# 1. Re-export all core models and primitives from yarvelle_core.db.models
from yarvelle_core.db.base import Base  # noqa: F401
from yarvelle_core.scope.context import DEFAULT_SCOPE  # noqa: F401
from yarvelle_core.scope.mixin import ScopedMixin  # noqa: F401
from yarvelle_core.db.models import *  # noqa: F401, F403
import yarvelle_core.db.models as _core_models

# 2. Re-export all 7 health pack models from carefold.models.health
try:
    from carefold.models.health import (
        HealthResource,
        HealthResourceVersion,
        HealthResourceCoding,
        HealthResourceReference,
        Appointment,
        PreventiveRecord,
        ImportBatch,
        SchoolForm,
        SchoolIcsFeed,
        CompanionDevice,
    )
    import carefold.models.health as _health_models
except ImportError:
    _health_models = None

if _health_models is not None:
    from sqlalchemy.orm import foreign, synonym

    # 3. Attach 7 health relationships onto Profile dynamically for Carefold runtime compatibility
    _HEALTH_RELATIONSHIPS = [
        ("health_resources", HealthResource),
        ("appointments", Appointment),
        ("preventive_records", PreventiveRecord),
        ("import_batches", ImportBatch),
        ("school_forms", SchoolForm),
        ("school_ics_feeds", SchoolIcsFeed),
        ("companion_devices", CompanionDevice),
    ]

    for rel_name, target in _HEALTH_RELATIONSHIPS:
        if not hasattr(Profile, rel_name):
            setattr(
                Profile,
                rel_name,
                relationship(
                    target,
                    overlaps="profile",
                    cascade="all, delete-orphan",
                    passive_deletes=True,
                ),
            )
    if not hasattr(Note, "appointment"):
        Note.appointment = relationship(
            Appointment,
            primaryjoin=foreign(Note.linked_appointment_id) == Appointment.id,
            back_populates="notes",
        )
        Note.linked_appointment = synonym("appointment")


# 4. Register dual-write listeners after all models are loaded
try:
    from yarvelle_core.scope.adapter import DualWriteAdapter

    DualWriteAdapter.register_listeners()
except Exception:
    pass


def _register_pack_scope_grant_bridge() -> None:
    """Ensures ProfileAccess and ProfileConsent synchronize ScopeGrant rows before flush."""
    import uuid
    from sqlalchemy import delete, event, select
    from sqlalchemy.orm import Session

    if getattr(Session, "_carefold_scope_bridge_registered", False):
        return

    _NS = "health"

    @event.listens_for(Session, "before_flush")
    def _on_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
        if session.info.get("skip_dual_write", False):
            return
        session.info["skip_dual_write"] = True
        session.info["carefold_bridge_skip_dw"] = True

        for obj in list(session.deleted):
            if isinstance(obj, ProfileAccess) and obj.profile_id and obj.user_id:
                session.execute(
                    delete(ScopeGrant).where(
                        ScopeGrant.profile_id == obj.profile_id,
                        ScopeGrant.user_id == obj.user_id,
                    )
                )

        for obj in list(session.new) + list(session.dirty):
            if isinstance(obj, ProfileConsent) and obj.profile_id:
                if obj in session.dirty and not session.is_modified(obj, include_collections=False):
                    continue
                rec_scope = f"{_NS}.records"
                session.execute(
                    delete(ScopeGrant).where(
                        ScopeGrant.profile_id == obj.profile_id,
                        ScopeGrant.user_id.is_(None),
                        ScopeGrant.scope == rec_scope,
                    )
                )
                for g in list(session.new):
                    if isinstance(g, ScopeGrant) and g.profile_id == obj.profile_id and g.user_id is None and g.scope == rec_scope:
                        session.expunge(g)
                if obj.allow_assist:
                    session.add(
                        ScopeGrant(
                            id=str(uuid.uuid4()),
                            profile_id=obj.profile_id,
                            user_id=None,
                            scope=rec_scope,
                            access_level="read",
                            granted_at=obj.updated_at or obj.created_at,
                        )
                    )
                continue

            if not isinstance(obj, ProfileAccess) or not obj.profile_id or not obj.user_id:
                continue
            if obj in session.dirty and not session.is_modified(obj, include_collections=False):
                continue

            session.execute(
                delete(ScopeGrant).where(
                    ScopeGrant.profile_id == obj.profile_id,
                    ScopeGrant.user_id == obj.user_id,
                )
            )
            for g in list(session.new):
                if isinstance(g, ScopeGrant) and g.profile_id == obj.profile_id and g.user_id == obj.user_id:
                    session.expunge(g)

            lvl = getattr(obj, "access_level", None)
            if lvl == "manage":
                targets = [(f"{_NS}.*", "write"), (f"{_NS}.*", "approve")]
            elif lvl == "view_records":
                targets = [
                    (f"{_NS}.clinical", "read"),
                    (f"{_NS}.records", "read"),
                    (f"{_NS}.paperwork", "read"),
                ]
            elif lvl == "view_paperwork":
                targets = [(f"{_NS}.paperwork", "read")]
            else:
                targets = [(f"{_NS}.*", "read")]

            for sc, access_lvl in targets:
                session.add(
                    ScopeGrant(
                        id=str(uuid.uuid4()),
                        profile_id=obj.profile_id,
                        user_id=obj.user_id,
                        scope=sc,
                        access_level=access_lvl,
                        granted_at=obj.granted_at,
                        granted_by=obj.granted_by,
                    )
                )

    def _restore_dw(session: Session, *_args: Any) -> None:
        if session.info.pop("carefold_bridge_skip_dw", False):
            session.info.pop("skip_dual_write", None)

    event.listen(Session, "after_flush", _restore_dw)
    event.listen(Session, "after_rollback", _restore_dw)
    setattr(Session, "_carefold_scope_bridge_registered", True)


_register_pack_scope_grant_bridge()


def __getattr__(name: str) -> Any:
    if _health_models is not None and hasattr(_health_models, name):
        return getattr(_health_models, name)
    return getattr(_core_models, name)


def __dir__() -> list[str]:
    attrs = set(globals().keys()) | set(dir(_core_models))
    if _health_models is not None:
        attrs |= set(dir(_health_models))
    return sorted(attrs)
