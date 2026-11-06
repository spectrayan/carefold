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

"""Carefold workflows subgraphs package.

Houses encapsulated LangGraph subgraphs for:
- Document Extraction & Attachment Ingestion Subgraph (Phase4 / R2)

The legacy regex supervisor subgraph was retired; routing runs through
yarvelle_core's orchestrated GraphBuilder (see carefold.engine.runtime).
"""

from __future__ import annotations

__all__: list[str] = []
