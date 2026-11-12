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
    from carefold.scope.adapter import DualWriteAdapter

    DualWriteAdapter.register_listeners()
except Exception:
    try:
        from yarvelle_core.scope.adapter import DualWriteAdapter

        DualWriteAdapter.register_listeners()
    except Exception:
        pass


def __getattr__(name: str) -> Any:
    if _health_models is not None and hasattr(_health_models, name):
        return getattr(_health_models, name)
    return getattr(_core_models, name)


def __dir__() -> list[str]:
    attrs = set(globals().keys()) | set(dir(_core_models))
    if _health_models is not None:
        attrs |= set(dir(_health_models))
    return sorted(attrs)
