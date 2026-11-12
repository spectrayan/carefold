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

"""Backward-compatibility re-export shim for yarvelle_core.schemas.profiles."""

from __future__ import annotations

import sys
from typing import Any, Literal
from pydantic import Field, model_validator

from yarvelle_core.schemas.profiles import *  # noqa: F401, F403
import yarvelle_core.schemas.profiles as _target_module

if (
    hasattr(_target_module, "ProfileConsentResponse")
    and "allow_assist" not in _target_module.ProfileConsentResponse.model_fields
):
    _CompatAccessLevel = Literal["manage", "view_records", "view_clinical", "view_paperwork"]
    _target_module.AccessLevel = _CompatAccessLevel  # type: ignore[attr-defined]

    class _CompatProfileConsentResponse(_target_module.ProfileConsentResponse):  # type: ignore[misc]
        allow_clinical: bool = False
        allow_assist: bool = False

        @model_validator(mode="before")
        @classmethod
        def _sync_consent_fields(cls, values: Any) -> Any:
            if isinstance(values, dict):
                data = dict(values)
                if "allow_assist" in data and "allow_clinical" not in data:
                    data["allow_clinical"] = data["allow_assist"]
                elif "allow_clinical" in data and "allow_assist" not in data:
                    data["allow_assist"] = data["allow_clinical"]
                return data
            return values

    class _CompatProfileConsentUpdate(_target_module.ProfileConsentUpdate):  # type: ignore[misc]
        allow_clinical: bool = False
        allow_assist: bool = False

        @model_validator(mode="before")
        @classmethod
        def _sync_update_fields(cls, values: Any) -> Any:
            if isinstance(values, dict):
                data = dict(values)
                if "allow_assist" in data and "allow_clinical" not in data:
                    data["allow_clinical"] = data["allow_assist"]
                elif "allow_clinical" in data and "allow_assist" not in data:
                    data["allow_assist"] = data["allow_clinical"]
                return data
            return values

    class _CompatProfileAccessResponse(_target_module.ProfileAccessResponse):  # type: ignore[misc]
        access_level: _CompatAccessLevel  # type: ignore[assignment]

    class _CompatProfileAccessGrant(_target_module.ProfileAccessGrant):  # type: ignore[misc]
        access_level: _CompatAccessLevel = Field(default="view_records")  # type: ignore[assignment]

    class _CompatProfileSummaryResponse(_target_module.ProfileSummaryResponse):  # type: ignore[misc]
        access_level: _CompatAccessLevel  # type: ignore[assignment]

    class _CompatProfileDetailResponse(_target_module.ProfileDetailResponse):  # type: ignore[misc]
        access_level: _CompatAccessLevel  # type: ignore[assignment]
        consent: _CompatProfileConsentResponse | None = None
        access_grants: list[_CompatProfileAccessResponse] = Field(default_factory=list)  # type: ignore[assignment]

    class _CompatViewerInviteCreate(_target_module.ViewerInviteCreate):  # type: ignore[misc]
        view_clinical: bool = True
        view_records: bool = True

        @model_validator(mode="before")
        @classmethod
        def _sync_invite_create(cls, values: Any) -> Any:
            if isinstance(values, dict):
                data = dict(values)
                if "view_records" in data and "view_clinical" not in data:
                    data["view_clinical"] = data["view_records"]
                elif "view_clinical" in data and "view_records" not in data:
                    data["view_records"] = data["view_clinical"]
                return data
            return values

    class _CompatViewerInviteResponse(_target_module.ViewerInviteResponse):  # type: ignore[misc]
        view_clinical: bool = True
        view_records: bool = True

        @model_validator(mode="before")
        @classmethod
        def _sync_invite_resp(cls, values: Any) -> Any:
            if isinstance(values, dict):
                data = dict(values)
                if "view_records" in data and "view_clinical" not in data:
                    data["view_clinical"] = data["view_records"]
                elif "view_clinical" in data and "view_records" not in data:
                    data["view_records"] = data["view_clinical"]
                return data
            return values

    _target_module.ProfileConsentResponse = _CompatProfileConsentResponse  # type: ignore[misc]
    _target_module.ProfileConsentUpdate = _CompatProfileConsentUpdate  # type: ignore[misc]
    _target_module.ProfileAccessResponse = _CompatProfileAccessResponse  # type: ignore[misc]
    _target_module.ProfileAccessGrant = _CompatProfileAccessGrant  # type: ignore[misc]
    _target_module.ProfileSummaryResponse = _CompatProfileSummaryResponse  # type: ignore[misc]
    _target_module.ProfileDetailResponse = _CompatProfileDetailResponse  # type: ignore[misc]
    _target_module.ProfileResponse = _CompatProfileDetailResponse  # type: ignore[misc]
    _target_module.ViewerInviteCreate = _CompatViewerInviteCreate  # type: ignore[misc]
    _target_module.ViewerInviteResponse = _CompatViewerInviteResponse  # type: ignore[misc]

sys.modules[__name__] = _target_module


def __getattr__(name: str) -> Any:
    return getattr(_target_module, name)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(dir(_target_module)))
