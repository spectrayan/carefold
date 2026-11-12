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

"""Dual-version compatibility tests for Carefold pack registration against yarvelle-core."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError
import pytest

import carefold


def test_pack_spec_passes_error_prefix_and_errors_file_when_supported() -> None:
    """Against current yarvelle-core, Carefold registers error_prefix='CFD' and errors_file."""
    spec = carefold.get_pack()
    assert spec.error_prefix == "CFD"
    assert spec.provides is not None
    assert spec.provides.errors_file == "resources/errors.yaml"


def test_pack_spec_omits_error_prefix_on_legacy_024_schema_without_swallowing_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Against PyPI yarvelle-core 0.2.4 (extra='forbid', no error_prefix), PackSpec boots cleanly."""

    class LegacyPackProvidesSpec(BaseModel):
        model_config = ConfigDict(extra="forbid")

        prompts_dir: Optional[str] = "resources/prompts/"
        locales_dir: Optional[str] = "resources/locales/"
        connectors_dir: Optional[str] = "connectors/"
        resources_dir: Optional[str] = "resources/"
        workflows_dir: Optional[str] = "workflows/"

    class LegacyPackSpec(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

        pack_api: int = 1
        id: str
        name: str
        version: str
        domain: str
        requires_core: str
        routing_hints: Any = None
        manifest_path: Optional[str] = None
        provides: Optional[LegacyPackProvidesSpec] = None

    monkeypatch.setattr(carefold, "PackProvidesSpec", LegacyPackProvidesSpec)
    monkeypatch.setattr(carefold, "PackSpec", LegacyPackSpec)

    provides = carefold._build_pack_provides_spec(
        prompts_dir="resources/prompts/",
        errors_file="resources/errors.yaml",
    )
    assert isinstance(provides, LegacyPackProvidesSpec)
    assert not hasattr(provides, "errors_file")

    spec = carefold._build_pack_spec(
        pack_api=1,
        id="health",
        name="Carefold Health Pack",
        version=carefold.__version__,
        domain="health",
        requires_core=">=0.2.4,<0.3.0",
        provides=provides,
        error_prefix="CFD",
    )
    assert isinstance(spec, LegacyPackSpec)
    assert not hasattr(spec, "error_prefix")

    # Other validation errors must NEVER be swallowed
    with pytest.raises(ValidationError):
        carefold._build_pack_spec(
            pack_api=1,
            id="health",
            name="Carefold Health Pack",
            version=carefold.__version__,
            domain="health",
            requires_core=">=0.2.4,<0.3.0",
            error_prefix="CFD",
            unexpected_invalid_field=True,
        )
