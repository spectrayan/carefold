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

"""Local-only orchestration evals for the Carefold health pack.

Built on ``yarvelle_core.testing.orch_eval``: scenarios, the eval pack loader,
the driver and the checks come from core. Carefold adds the health eval pack,
health scenarios and rubrics, an LLM judge and a local Ollama backend.

Nothing here runs on CI. Entry points refuse on CI and need ``YARVELLE_EVAL=1``.
"""
