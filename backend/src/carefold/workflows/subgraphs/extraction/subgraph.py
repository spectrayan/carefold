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

"""Document Extraction & Attachment Processing Subgraph (Requirement R2).

Coordinates:
- Ingestion of attachments from attachments/
- Direct PII sanitization (SSN, MRN, phone, address)
- Structured schema extraction into typed Pydantic dossiers
- Grounding verification of numerical data against raw text
- AgentState['document_dossiers'] population and verified summary generation
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Callable, Coroutine, Dict, Optional, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from carefold.constants.agents import AGENT_DOCUMENT_EXTRACTOR
from carefold.constants.extraction import (
    DOSSIER_TYPE_CLINICAL,
    DOSSIER_TYPE_GENERIC,
    DOSSIER_TYPE_INSURANCE,
    EXTRACTION_STEP_DONE,
    EXTRACTION_STEP_SANITIZE,
    MSG_EXTRACTION_COMPLETED,
    MSG_EXTRACTION_FALLBACK,
)
from carefold.resources.loader import get_resource_loader
from carefold.workflows.state import AgentState, get_last_user_prompt_text
from carefold.workflows.subgraphs.extraction.tool import extract_document_dossier


logger = logging.getLogger(__name__)


class ExtractionState(AgentState, total=False):
    """Specialized state for document extraction subgraphs extending AgentState."""
    document_text: Optional[str]
    raw_text: Optional[str]
    file_path: Optional[str]
    attachment_path: Optional[str]
    dossier_type: Optional[str]


def create_ingestion_node() -> Callable[[ExtractionState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Builds node resolving attachment path or document text from state."""

    async def ingestion_node(state: ExtractionState) -> Dict[str, Any]:
        doc_text = state.get("document_text") or state.get("raw_text")
        file_path = state.get("attachment_path") or state.get("file_path")

        if not doc_text and not file_path:
            # Check state attachments if present
            attachments = state.get("attachments") or []
            if attachments and isinstance(attachments, list) and isinstance(attachments[0], str):
                file_path = attachments[0]
            else:
                # Dynamically extract attachment filename from prompt
                prompt = get_last_user_prompt_text(state)
                matched_files = re.findall(r"[\w\-.]+\.(?:txt|pdf|md)", prompt)
                if matched_files:
                    file_path = matched_files[0]

        return {
            "document_text": doc_text,
            "file_path": file_path,
            "next_step": EXTRACTION_STEP_SANITIZE,
        }

    return ingestion_node


def create_extraction_node(
    model: Optional[BaseChatModel] = None,
) -> Callable[[ExtractionState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Builds node executing extraction, sanitization, grounding, and state update."""

    async def extraction_node(state: ExtractionState) -> Dict[str, Any]:
        file_path = state.get("file_path")
        doc_text = state.get("document_text")
        dossier_type = state.get("dossier_type")

        # Only auto-infer dossier_type from prompt patterns if not explicitly provided
        if not dossier_type:
            prompt = get_last_user_prompt_text(state).lower()
            matched = None
            try:
                patterns = get_resource_loader().get_routing_patterns().get("dossier_types", {})
                for dtype, pat_list in patterns.items():
                    for pat in pat_list:
                        if re.search(pat, prompt, re.IGNORECASE):
                            matched = dtype
                            break
                    if matched:
                        break
            except Exception:
                matched = None

            if matched == "insurance":
                dossier_type = DOSSIER_TYPE_INSURANCE
            elif matched == "clinical":
                dossier_type = DOSSIER_TYPE_CLINICAL
            else:
                dossier_type = DOSSIER_TYPE_GENERIC


        dossiers = list(state.get("document_dossiers", []))

        # Run extraction tool pipeline if file or text is available
        if file_path or doc_text:
            try:
                res = await extract_document_dossier.ainvoke({
                    "file_path": file_path,
                    "document_text": doc_text,
                    "dossier_type": dossier_type,
                })
                if isinstance(res, dict) and "dossier" in res:
                    payload = {
                        "dossier_type": res.get("dossier_type", dossier_type),
                        "data": res.get("dossier"),
                        "grounding": {
                            "is_grounded": res.get("is_grounded", True),
                            "unmatched_values": res.get("unmatched_values", []),
                        },
                        "source_file": file_path,
                    }
                    dossiers.append(payload)
            except Exception as exc:
                logger.warning("Extraction pipeline execution note: %s", exc)

        if dossiers:
            output_msg = MSG_EXTRACTION_COMPLETED
        else:
            output_msg = MSG_EXTRACTION_FALLBACK

        return {
            "document_dossiers": dossiers,
            "output": output_msg,
            "messages": [AIMessage(content=output_msg)],
            "current_agent": AGENT_DOCUMENT_EXTRACTOR,
            "agent_id": AGENT_DOCUMENT_EXTRACTOR,
            "next_step": EXTRACTION_STEP_DONE,
        }

    return extraction_node


def create_extraction_subgraph(
    model: Optional[BaseChatModel] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    compile: bool = False,
    **kwargs: Any,
) -> Union[StateGraph, CompiledStateGraph]:
    """Assembles and optionally compiles the Document Extraction Subgraph.

    Args:
        model: Optional chat model double or provider.
        checkpointer: Optional state checkpointer.
        compile: If True, returns a CompiledStateGraph; otherwise StateGraph.

    Returns:
        StateGraph or CompiledStateGraph.
    """
    builder = StateGraph(ExtractionState)

    builder.add_node("ingestion_node", create_ingestion_node())
    builder.add_node("extraction_node", create_extraction_node(model=model))

    builder.add_edge(START, "ingestion_node")
    builder.add_edge("ingestion_node", "extraction_node")
    builder.add_edge("extraction_node", END)

    if compile:
        return builder.compile(checkpointer=checkpointer)
    return builder


def build_extraction_subgraph(
    model: Optional[BaseChatModel] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    **kwargs: Any,
) -> CompiledStateGraph:
    """Convenience factory compiling the extraction subgraph directly."""
    return create_extraction_subgraph(
        model=model, checkpointer=checkpointer, compile=True, **kwargs
    )


__all__ = [
    "ExtractionState",
    "build_extraction_subgraph",
    "create_extraction_node",
    "create_extraction_subgraph",
    "create_ingestion_node",
]
