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

"""Dual-invocation document extraction tool for specialist agents (Feature F-38 & Milestone 6).

Invocable directly as a LangChain tool by specialist agents or as an automated
ingestion step upon attachment upload. Reads sandboxed attachments, sanitizes PII,
extracts typed Pydantic dossiers, runs GroundingValidator, and populates AgentState.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Type, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from carefold.config import settings
from carefold.constants.agents import TOOL_EXTRACT_DOCUMENT_DOSSIER
from carefold.constants.extraction import (
    DEFAULT_DOSSIER_TYPE,
    DOSSIER_TYPE_CLINICAL,
    DOSSIER_TYPE_GENERIC,
    DOSSIER_TYPE_INSURANCE,
)
from carefold.constants.paths import ATTACHMENTS_DIR
from carefold.tools.attach_read import (
    execute_attach_read,
    extract_text_from_pdf_bytes,
)
from carefold.tools.sandbox import SandboxSecurityError
from carefold.workflows.state import AgentState
from carefold.workflows.subgraphs.extraction.dossiers import (
    BaseDossier,
    ClinicalVisitDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from carefold.workflows.subgraphs.extraction.grounding import GroundingValidator
from carefold.workflows.subgraphs.extraction.sanitizer import sanitize_pii

logger = logging.getLogger(__name__)


class DocumentSandboxError(SandboxSecurityError, PermissionError):
    """Raised when an attachment path traversal or sandbox escape is attempted."""


class ExtractDocumentDossierInput(BaseModel):
    """Input argument schema for the extract_document_dossier tool."""

    file_path: Optional[str] = Field(
        default=None,
        description="Relative path to file located inside the attachments/ directory.",
    )
    document_text: Optional[str] = Field(
        default=None,
        description="Raw document text if already loaded or provided directly.",
    )
    dossier_type: str = Field(
        default=DEFAULT_DOSSIER_TYPE,
        description="Target dossier schema: 'insurance', 'clinical', or 'generic'.",
    )
    state: Optional[Any] = Field(
        default=None,
        description="Optional state dictionary or AgentState to populate directly.",
    )
    workspace_root: Optional[Union[str, Path]] = Field(
        default=None,
        description="Optional workspace directory path.",
    )


def _heuristic_dossier_extractor(text: str, dossier_type: str) -> BaseDossier:
    """Deterministic extractor fallback supporting offline and test environments."""
    norm_type = dossier_type.lower().strip()

    if norm_type in ("insurance", "insurance_benefits") or "deductible" in text.lower():
        # Deductible
        m_ded = re.search(
            r"deductible\s*(?:is|:)?\s*(\$?\d+(?:,\d{3})*)", text, re.I
        )
        deductible = m_ded.group(1) if m_ded else ""
        if deductible and not deductible.startswith("$") and deductible.isdigit():
            deductible = f"${deductible}"

        # Copays
        copays: Dict[str, str] = {}
        m_pc = re.search(
            r"primary\s*care\s*(?:visit)?(?:\s*copay)?(?:\s*[:is]+)?\s*(\$?\d+)", text, re.I
        )
        if m_pc:
            copays["primary_care"] = (
                m_pc.group(1) if m_pc.group(1).startswith("$") else f"${m_pc.group(1)}"
            )
        m_sp = re.search(
            r"specialist\s*(?:visit)?(?:\s*copay)?(?:\s*[:is]+)?\s*(\$?\d+)", text, re.I
        )
        if m_sp:
            copays["specialist"] = (
                m_sp.group(1) if m_sp.group(1).startswith("$") else f"${m_sp.group(1)}"
            )
        if not copays:
            m_gen_copay = re.search(r"copay\s*(?:is|:)?\s*(\$?\d+)", text, re.I)
            if m_gen_copay:
                val = m_gen_copay.group(1)
                copays["office_visit"] = val if val.startswith("$") else f"${val}"

        # Coinsurance
        m_coin = re.search(
            r"coinsurance\s*(?:is|:)?\s*(\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*percent)",
            text,
            re.I,
        )
        coinsurance = m_coin.group(1) if m_coin else ""

        # OOP Max
        m_oop = re.search(
            r"out[- ]of[- ]pocket\s*max(?:imum)?\s*(?:is|:)?\s*(\$?\d+(?:,\d{3})*)",
            text,
            re.I,
        )
        oop = m_oop.group(1) if m_oop else ""

        # Rules & Prior Auth
        m_rules = re.search(r"([^\n]*in-network[^\n]*)", text, re.I)
        rules = m_rules.group(1).strip() if m_rules else ""

        prior_auth: List[str] = []
        if re.search(r"\bMRI\b", text):
            prior_auth.append("MRI")
        if re.search(r"\bCT\b", text):
            prior_auth.append("CT")
        if re.search(r"\bPET\b", text):
            prior_auth.append("PET")
        if re.search(r"\bphysical\s*therapy\b", text, re.I):
            prior_auth.append("physical therapy")

        return InsuranceBenefitsDossier(
            deductible=deductible,
            copays=copays,
            coinsurance=coinsurance,
            out_of_pocket_maximum=oop,
            in_out_network_rules=rules,
            prior_authorization_flags=prior_auth,
        )

    elif norm_type in ("clinical", "clinical_visit") or "physician" in text.lower():
        m_reason = re.search(r"reason\s*for\s*visit\s*:\s*([^\n\.]+)", text, re.I)
        reason = m_reason.group(1).strip() if m_reason else ""

        m_time = re.search(
            r"follow[- ]up\s*(?:is|:)?\s*(?:return\s*in\s*)?(\d+\s*(?:weeks?|days?|months?))",
            text,
            re.I,
        )
        timeline = m_time.group(1) if m_time else ""

        instructions: List[str] = []
        m_inst = re.search(r"physician\s*instructions\s*:\s*([^\n]+)", text, re.I)
        if m_inst:
            raw_inst = [
                s.strip()
                for s in m_inst.group(1).split(",")
                if s.strip()
            ]
            if raw_inst:
                instructions = raw_inst

        questions: List[str] = []
        m_q = re.search(r"questions?\s*(?:to\s*ask)?\s*:\s*([^\n]+)", text, re.I)
        if m_q:
            raw_q = [
                s.strip()
                for s in m_q.group(1).split(",")
                if s.strip()
            ]
            if raw_q:
                questions = raw_q

        return ClinicalVisitDossier(
            reason_for_visit=reason,
            physician_instructions=instructions,
            follow_up_timeline=timeline,
            questions_to_ask=questions,
        )

    else:
        m_sum = re.search(r"summary\s*:\s*([^\n]+)", text, re.I)
        summary = (
            m_sum.group(1).strip()
            if m_sum
            else text.splitlines()[0]
            if text.splitlines()
            else ""
        )

        nums: Dict[str, str] = {}
        m_stay = re.search(r"length\s*of\s*stay\s*:\s*([^\n,\.]+)", text, re.I)
        if m_stay:
            nums["length_of_stay"] = m_stay.group(1).strip()

        m_iv = re.search(r"iv\s*hydration\s*:\s*([^\n,\.]+)", text, re.I)
        if m_iv:
            nums["iv_hydration"] = m_iv.group(1).strip()

        sections: List[str] = []
        m_sec = re.search(r"sections?\s*:\s*([^\n]+)", text, re.I)
        if m_sec:
            raw_secs = [
                s.strip()
                for s in m_sec.group(1).split(",")
                if s.strip()
            ]
            if raw_secs:
                sections = raw_secs

        return GenericDocumentDossier(
            summary=summary,
            key_numerical_values=nums,
            sections=sections,
        )


class ExtractDocumentDossierTool(BaseTool):
    """LangChain-compatible tool for structured document extraction with PII and grounding.

    Composes SanitizePIITool, ExtractStructuredDataTool, and ValidateGroundingTool
    while retaining 100% backward compatibility with all existing tests.
    """

    name: str = TOOL_EXTRACT_DOCUMENT_DOSSIER
    description: str = (
        "Extract structured, grounded Pydantic dossiers from medical documents or "
        "insurance summaries. Automatically sanitizes PII and verifies numerical figures."
    )
    args_schema: Type[BaseModel] = ExtractDocumentDossierInput
    model: Optional[BaseChatModel] = None

    def __init__(self, model: Optional[BaseChatModel] = None, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)

    def _read_document_content(
        self,
        file_path: Optional[str],
        document_text: Optional[str],
        workspace_root: Optional[Union[str, Path]] = None,
    ) -> str:
        """Resolve document content from raw text or sandboxed attachment file."""
        if document_text and str(document_text).strip():
            return str(document_text)

        if not file_path:
            raise ValueError("Either file_path or document_text must be provided.")

        ws_root = Path(workspace_root) if workspace_root else Path(settings.workspace_root)
        uploads_dir = settings.get_uploads_dir().resolve()
        ws_uploads_dir = (ws_root / "uploads").resolve()
        legacy_att_dir = (ws_root / "attachments").resolve()

        allowed_sandboxes = [uploads_dir, ws_uploads_dir, legacy_att_dir]

        # Reject null bytes or URI schemes
        clean_path = str(file_path).strip()
        if any(c in clean_path for c in ("\0", "file://", "http://", "https://")):
            raise DocumentSandboxError(f"Path traversal forbidden: Invalid path characters in '{file_path}'")

        # 1. Attempt sandboxed execution via attach_read
        ctx = type("ExtractionExecutionContext", (), {"workspace_root": ws_root})()

        res = None
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    res = executor.submit(
                        lambda: asyncio.run(
                            execute_attach_read({"path": file_path}, ctx)
                        )
                    ).result()
            else:
                res = asyncio.run(execute_attach_read({"path": file_path}, ctx))
        except SandboxSecurityError as sec_err:
            raise DocumentSandboxError(str(sec_err)) from sec_err
        except Exception as exc:
            logger.debug("execute_attach_read failed: %s", exc)

        if res is not None:
            if res.success and res.output and res.output.get("content"):
                return str(res.output.get("content", ""))

            if not res.success and res.error:
                err_lower = res.error.lower()
                if any(
                    kw in err_lower
                    for kw in (
                        "traversal",
                        "escape",
                        "escapes",
                        "forbidden",
                        "null byte",
                        "uri scheme",
                        "security",
                    )
                ):
                    raise DocumentSandboxError(res.error)

        # 2. Direct path resolution fallbacks across allowed sandboxes
        candidate_paths = [
            uploads_dir / file_path,
            ws_uploads_dir / file_path,
            legacy_att_dir / file_path,
        ]
        if str(file_path).startswith("attachments/") or str(file_path).startswith("uploads/"):
            candidate_paths.append(ws_root / file_path)

        for p in candidate_paths:
            try:
                resolved = p.resolve()
                if not any(resolved.is_relative_to(sandbox) for sandbox in allowed_sandboxes):
                    raise DocumentSandboxError(
                        f"Path traversal forbidden: Path '{file_path}' escapes allowed directory"
                    )
                if resolved.is_file():
                    if resolved.suffix.lower() == ".pdf":
                        return extract_text_from_pdf_bytes(resolved.read_bytes())
                    return resolved.read_text(encoding="utf-8", errors="replace")
            except DocumentSandboxError:
                raise
            except Exception:
                continue

        raise FileNotFoundError(
            f"Failed to find or read sandboxed attachment '{file_path}'"
        )

    def _run(
        self,
        file_path: Optional[str] = None,
        document_text: Optional[str] = None,
        dossier_type: str = DEFAULT_DOSSIER_TYPE,
        state: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute document extraction, sanitization, grounding, and state update."""
        raw_text = self._read_document_content(
            file_path, document_text, workspace_root=workspace_root
        )

        from carefold.tools.extraction_tools import (
            ExtractStructuredDataTool,
            SanitizePIITool,
            ValidateGroundingTool,
        )

        # 1. PII Sanitization via SanitizePIITool
        sanitizer_tool = SanitizePIITool()
        sanitized_text = sanitizer_tool._run(raw_text)

        # 2. Schema Extraction via ExtractStructuredDataTool
        extraction_tool = ExtractStructuredDataTool(model=self.model)
        serialized_dossier = extraction_tool._run(sanitized_text, schema_type=dossier_type)

        # 3. Grounding Verification against raw source text
        grounding_tool = ValidateGroundingTool()
        grounding_dict = grounding_tool._run(serialized_dossier, raw_text)

        # 4. Resolve normalized dossier type
        dossier_cls = get_dossier_cls(dossier_type)
        try:
            resolved_type = dossier_cls().dossier_type
        except Exception:
            resolved_type = dossier_type

        # 5. State Population
        payload = {
            "dossier_type": resolved_type,
            "data": serialized_dossier,
            "grounding": grounding_dict,
            "source_file": file_path,
        }

        if state is not None and isinstance(state, dict):
            state.setdefault("document_dossiers", []).append(payload)

        return {
            "status": "success",
            "dossier_type": resolved_type,
            "dossier": serialized_dossier,
            "is_grounded": grounding_dict.get("is_grounded", True),
            "unmatched_values": grounding_dict.get("unmatched_values", []),
        }

    async def _arun(
        self,
        file_path: Optional[str] = None,
        document_text: Optional[str] = None,
        dossier_type: str = DEFAULT_DOSSIER_TYPE,
        state: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Async execution handler delegating to _run."""
        return self._run(
            file_path=file_path,
            document_text=document_text,
            dossier_type=dossier_type,
            state=state,
            workspace_root=workspace_root,
            **kwargs,
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Enables direct invocation as a callable Python function."""
        if args and isinstance(args[0], dict) and not kwargs:
            return self.invoke(args[0])
        keys = ["file_path", "document_text", "dossier_type"]
        for i, a in enumerate(args):
            if i < len(keys) and keys[i] not in kwargs:
                kwargs[keys[i]] = a
        return self.invoke(kwargs)


# Canonical singleton tool instance
extract_document_dossier = ExtractDocumentDossierTool()

__all__ = [
    "DocumentSandboxError",
    "ExtractDocumentDossierInput",
    "ExtractDocumentDossierTool",
    "extract_document_dossier",
]
