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

"""SkillGeneratorNode: Dynamically synthesizes missing domain skills on demand.

When the Orchestrator identifies that a skill is missing (either undeclared,
uninstalled, or required for specialized care navigation), this node is invoked
to generate a complete, structured, safety-compliant skill manifest and reference
documents, which are then passed to the downstream answering agent.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from carefold.config import settings
from carefold.constants.paths import SKILLS_DIR
from carefold.resources.loader import get_resource_loader
from carefold.schemas.manifest import RiskClass, SkillManifest
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import extract_text_content

logger = logging.getLogger(__name__)


# Patterns indicating conversational refusals or disclaimers that must NOT be persisted as reference docs
_REFUSAL_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"\b(?:cannot|can['’]t|unable\s+to|not\s+(?:able|permitted|allowed)\s+to)\s+"
        r"(?:provide|give|offer)\s+(?:medical|clinical)\s+advice\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:as\s+an?\s+ai|as\s+a\s+language\s+model|i\s+am\s+an?\s+ai)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:please\s+)?consult\s+(?:a\s+)?(?:qualified|licensed)\s+"
        r"(?:healthcare\s+professional|physician|doctor|clinician|medical\s+professional)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bif\s+you\s+are\s+experiencing\s+symptoms\b", re.IGNORECASE),
    re.compile(
        r"\bi\s+am\s+not\s+a\s+(?:doctor|physician|clinician|licensed\s+medical\s+professional)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bi\s+cannot\s+(?:diagnose|prescribe)\b", re.IGNORECASE),
]

# Patterns indicating conversational greetings or chat dialogue that must NOT be persisted as reference docs
_GREETING_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:i\s+am|i['’]m)\s+here\s+to\s+assist\s+you\b", re.IGNORECASE),
    re.compile(r"\bhow\s+(?:can|may)\s+i\s+(?:assist|help)\s+you\b", re.IGNORECASE),
    re.compile(r"\bis\s+there\s+anything\s+else\s+i\s+can\s+(?:help|assist)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+can\s+i\s+help\s+you\s+with\b", re.IGNORECASE),
]


class GeneratedSkillSchema(BaseModel):
    """Structured output schema for a generated domain skill."""

    id: str = Field(
        ...,
        description="URL-safe slug identifier for the skill (e.g., 'dental-benefits-explainer', 'pediatric-visit-prep').",
    )
    name: str = Field(
        ...,
        description="Human-readable title of the skill.",
    )
    description: str = Field(
        ...,
        description="Concise description of the skill scope and capabilities.",
    )
    instructions: str = Field(
        ...,
        description="Step-by-step guidance, domain rules, and safety boundaries for the answering agent.",
    )
    tools: List[str] = Field(
        default_factory=lambda: ["skill-docs"],
        description="Tools required by this skill from Phase 0 registry (e.g. ['skill-docs', 'attach-read']).",
    )
    references: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of reference document filenames to markdown content (e.g. {'guide.md': '# Guide...'})",
    )


class SkillGeneratorNode(BaseNode):
    """Executes the skill-generator agent to synthesize missing domain skills."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        skills_dir: Optional[Union[Path, str]] = None,
        name: str = "skill_generator",
    ) -> None:
        super().__init__(name=name)
        self.model = model
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else None

    def _resolve_skills_dir(self, state: Dict[str, Any]) -> Path:
        """Resolves target skills directory from state, injection, or settings."""
        if self.skills_dir:
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            return self.skills_dir
        if state.get("skills_dir"):
            p = Path(state["skills_dir"]).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
        if state.get("workspace_root"):
            return Path(state["workspace_root"]).resolve() / SKILLS_DIR
        return settings.get_skills_dir().resolve()

    def _is_valid_reference_doc_content(self, text: Optional[str]) -> bool:
        """Validates that candidate content is a structured markdown reference document.

        Enforces:
        1. Non-empty string with substantial length (>= 200 bytes and >= 50 words).
        2. Contains Markdown headings (starts with '#' or contains '##').
        3. Does not contain conversational LLM refusals or medical advice disclaimers.
        4. Does not contain conversational greetings or chat dialogue.
        """
        if not text or not isinstance(text, str):
            return False
        stripped = text.strip()

        # 1. Structural Markdown header check
        if not (stripped.startswith("#") or "##" in stripped):
            return False

        # 2. Substantial content threshold (satisfies systematic stress suite)
        if len(stripped.encode("utf-8")) < 200 or len(stripped.split()) < 50:
            return False

        # 3. Reject LLM conversational refusals / disclaimers
        for pattern in _REFUSAL_PATTERNS:
            if pattern.search(stripped):
                return False

        # 4. Reject conversational greetings / chat dialogue
        for pattern in _GREETING_PATTERNS:
            if pattern.search(stripped):
                return False

        return True

    def _build_system_prompt(self) -> str:
        """Assembles prompt enforcing Carefold non-clinical boundaries."""
        return (
            "You are the Carefold Skill Generator, a specialized meta-agent.\n"
            "Your objective is to generate structured, high-quality, safety-compliant healthcare navigation skills.\n"
            "CRITICAL SAFETY CONSTRAINTS:\n"
            "- Generated skills must NEVER diagnose, prescribe, dose, or replace emergency care.\n"
            "- Always include non-clinical boundaries, disclaimers, and verify-with-clinician instructions.\n"
            "- Provide clear step-by-step guidance and at least one reference guide/checklist.\n"
        )

    def _synthesize_fallback_skill(
        self,
        skill_id: str,
        skill_description: str,
        user_query: str,
        target_agent: str,
    ) -> Dict[str, Any]:
        """Synthesizes a rule-based fallback skill when model is unconfigured or offline."""
        clean_id = re.sub(r"[^a-z0-9_-]", "-", skill_id.lower()).strip("-") or "generated-skill"
        title = clean_id.replace("-", " ").title()
        desc = skill_description or f"On-demand guidance for {title} navigating user inquiries."

        ref_doc_name = f"{clean_id}_guide.md"
        ref_doc_content = (
            f"# {title} Reference Guide\n\n"
            f"## Overview\n{desc}\n\n"
            f"## Context & User Inquiry\n{user_query}\n\n"
            f"## Key Checklist & Navigation Steps\n"
            f"1. Clarify patient/member context and specific questions.\n"
            f"2. Gather plan documents, provider instructions, or clinical notes.\n"
            f"3. Direct user to appropriate licensed clinicians or insurance administrators for formal determinations.\n\n"
            f"## Boundary Disclosure\n"
            f"This guide is an informational navigation resource and does not provide clinical diagnoses or legally binding coverage decisions.\n"
        )

        instructions = (
            f"You are operating with the dynamically generated skill '{title}'.\n"
            f"Purpose: {desc}\n\n"
            f"Guidelines:\n"
            f"1. Explain relevant domain concepts clearly without clinical jargon.\n"
            f"2. Reference '{ref_doc_name}' for detailed checklists.\n"
            f"3. Strictly maintain safety boundaries: never diagnose, prescribe, or alter treatments.\n"
        )

        return {
            "id": clean_id,
            "name": title,
            "description": desc,
            "instructions": instructions,
            "tools": ["skill-docs"],
            "references": {
                ref_doc_name: ref_doc_content,
            },
        }

    def _synthesize_reference_doc_content(
        self,
        skill_id: str,
        doc_name: str,
        user_query: str = "",
        target_agent: str = "",
    ) -> str:
        """Synthesizes structured, safety-compliant clinical navigation markdown for a missing document."""
        clean_stem = Path(doc_name).stem.replace("_", " ").replace("-", " ").title()
        skill_title = skill_id.replace("_", " ").replace("-", " ").title()
        doc_lower = doc_name.lower()

        if "template" in doc_lower or "log" in doc_lower or "tracker" in doc_lower:
            body = (
                f"## 1. Purpose & Overview\n"
                f"This template provides a standardized tracking tool for {clean_stem.lower()} to support productive discussions with your healthcare provider.\n\n"
                f"## 2. Tracking Log Matrix\n\n"
                f"| Date & Time | Primary Observation / Entry | Severity / Rating (1-10) | Duration / Frequency | Triggers / Contributing Factors | Actions / Interventions Tried | Impact on Daily Function |\n"
                f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
                f"| *YYYY-MM-DD* | *Detailed description* | *1 - 10* | *e.g., 2 hours* | *Specific triggers noted* | *Rest, lifestyle, or prescribed remedies* | *Impact on work, sleep, or routine* |\n"
                f"| | | | | | | |\n"
                f"| | | | | | | |\n\n"
                f"## 3. Key Discussion Points for Your Clinician\n"
                f"- Describe specific patterns or triggers identified during logging.\n"
                f"- Note which interventions provided relief and which were ineffective.\n"
                f"- Ask what diagnostic tests, lifestyle modifications, or specialist consultations are recommended.\n"
            )
        elif "checklist" in doc_lower or "prep" in doc_lower:
            body = (
                f"## 1. Pre-Visit Logistics & Documents\n"
                f"- [ ] Insurance card, photo ID, and form of payment for copays.\n"
                f"- [ ] Current medication list including exact doses and OTC supplements.\n"
                f"- [ ] Prior records, lab reports, imaging discs, or referring provider notes.\n\n"
                f"## 2. Priority Agendas\n"
                f"- [ ] Top 1–3 questions or health goals prioritized for this consultation.\n"
                f"- [ ] Timeline of relevant changes or concerns over the past 30–90 days.\n\n"
                f"## 3. Next Steps & Follow-Up Verification\n"
                f"- [ ] Clarify required diagnostic orders, referrals, or lab requisitions.\n"
                f"- [ ] Confirm follow-up visit timeline and clinician contact procedures.\n"
            )
        elif "glossary" in doc_lower or "terms" in doc_lower or "code" in doc_lower or "explanation" in doc_lower or "eob" in doc_lower:
            body = (
                f"## 1. Key Terminology & Concepts\n"
                f"- **Core Definition**: Essential understanding of {clean_stem.lower()} within healthcare navigation.\n"
                f"- **Clinical Context**: How healthcare providers and insurers use this terminology.\n"
                f"- **Patient Considerations**: What this means for your care plan, coverage, and out-of-pocket responsibilities.\n\n"
                f"## 2. Questions to Clarify with Provider or Carrier\n"
                f"1. *How does this apply to my specific clinical situation or insurance policy?*\n"
                f"2. *Are there formal pre-authorization, in-network, or documentation requirements?*\n"
            )
        else:
            body = (
                f"## 1. Overview & Context\n"
                f"{clean_stem} provides structured informational guidance for {skill_title.lower()}.\n\n"
                f"## 2. Key Action Items & Guidance\n"
                f"1. Review relevant patient history and document priorities in writing.\n"
                f"2. Formulate clear, concise questions for the treating healthcare provider.\n"
                f"3. Verify insurance coverage, in-network provider tiers, and required authorizations.\n\n"
                f"## 3. Communication Guide\n"
                f"Prepare a concise 2-minute summary of your goals for the clinician to ensure all priorities are addressed.\n"
            )

        context_section = f"\n## Clinical Context & User Inquiry\n{user_query}\n\n" if user_query else "\n"

        return (
            f"# {clean_stem}\n\n"
            f"**Skill Domain**: {skill_title}  \n"
            f"**Reference Document**: `{doc_name}`\n\n"
            f"---{context_section}"
            f"{body}\n"
            f"---\n\n"
            f"## ⚠️ Carefold Boundary & Safety Disclosures\n\n"
            f"> **NON-CLINICAL INFORMATIONAL AID**: This reference document is an educational and organizational resource. "
            f"It does **NOT** provide clinical diagnoses, prescribe or dose medications, or replace the clinical judgment of licensed medical professionals.\n"
            f"> \n"
            f"> **EMERGENCY WARNING**: If experiencing acute, life-threatening symptoms (e.g. acute chest pain, shortness of breath, sudden weakness/speech impairment, severe trauma), **immediately call 911 or visit the nearest emergency department**.\n"
        )

    def synthesize_reference_doc_content(
        self,
        skill_id: str,
        doc_name: str,
        user_query: str = "",
        target_agent: str = "assistant",
    ) -> str:
        """Synchronously synthesizes rule-based reference doc content in-memory."""
        return self._synthesize_reference_doc_content(
            skill_id=skill_id,
            doc_name=doc_name,
            user_query=user_query,
            target_agent=target_agent,
        )

    async def synthesize_reference_doc(
        self,
        skill_id: str,
        doc_name: str,
        user_query: str = "",
        target_agent: str = "assistant",
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synthesizes reference doc content with guaranteed in-memory fallback if disk write is not possible."""
        clean_doc = doc_name.strip()
        if not clean_doc.endswith((".md", ".txt", ".markdown")):
            clean_doc = f"{clean_doc}.md"

        clean_stem = Path(clean_doc).stem.replace("_", " ").replace("-", " ").title()

        # 1. Check if already exists and valid on disk
        doc_path: Optional[Path] = None
        try:
            target_skills_dir = self._resolve_skills_dir(state or {})
            skill_folder = target_skills_dir / skill_id
            if skill_folder.is_dir():
                candidate = skill_folder / "references" / clean_doc
                if candidate.is_file():
                    existing_text = candidate.read_text(encoding="utf-8")
                    if self._is_valid_reference_doc_content(existing_text):
                        return {
                            "title": clean_stem,
                            "content": existing_text,
                            "path": candidate,
                            "skill_id": skill_id,
                        }
            doc_path = skill_folder / "references" / clean_doc
        except Exception as resolve_err:
            logger.debug("Could not resolve disk path for '%s': %s", clean_doc, resolve_err)

        # 2. Synthesize content via LLM or rule-based fallback
        content = None
        if self.model is not None:
            try:
                sys_msg = SystemMessage(content=self._build_system_prompt())
                prompt = (
                    f"Generate a complete, structured reference markdown document named '{clean_doc}' "
                    f"for the healthcare skill '{skill_id}'.\n"
                    f"Target Specialist Agent: {target_agent}\n"
                    f"User Inquiry Context: {user_query}\n\n"
                    f"Include structured tables or checklists, action steps, and strict non-clinical disclaimers."
                )
                resp = await self.model.ainvoke(
                    [sys_msg, HumanMessage(content=prompt)],
                    config={"tags": ["internal", "skill_generator", "no_stream"]},
                )
                text = extract_text_content(resp).strip()
                if self._is_valid_reference_doc_content(text):
                    content = text
                else:
                    logger.warning(
                        "Model output for reference doc '%s' failed validation; falling back to rule-based synthesis",
                        clean_doc,
                    )
            except Exception as exc:
                logger.warning("SkillGenerator reference doc model generation failed: %s; using rule-based synthesis", exc)

        if not content:
            content = self._synthesize_reference_doc_content(
                skill_id=skill_id,
                doc_name=clean_doc,
                user_query=user_query,
                target_agent=target_agent,
            )

        # 3. Best-effort persistence to disk without halting on failure
        written_path: Optional[Path] = None
        if doc_path is not None:
            try:
                doc_path.parent.mkdir(parents=True, exist_ok=True)
                doc_path.write_text(content, encoding="utf-8")
                written_path = doc_path
                logger.info("SkillGenerator proactively provisioned reference doc: %s", doc_path)
            except Exception as write_err:
                logger.warning(
                    "Could not persist provisioned doc '%s' (retaining in-memory content): %s",
                    doc_path,
                    write_err,
                )

        return {
            "title": clean_stem,
            "content": content,
            "path": written_path,
            "skill_id": skill_id,
        }

    async def ensure_reference_doc(
        self,
        skill_id: str,
        doc_name: str,
        user_query: str = "",
        target_agent: str = "assistant",
        state: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """Proactively verifies that a reference doc exists for a skill, generating it beforehand if missing."""
        res = await self.synthesize_reference_doc(
            skill_id=skill_id,
            doc_name=doc_name,
            user_query=user_query,
            target_agent=target_agent,
            state=state,
        )
        return res.get("path")


    async def generate_skill(
        self,
        skill_id: str,
        skill_description: str,
        user_query: str,
        target_agent: str = "assistant",
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates a complete skill dictionary and optionally persists to skills_dir."""
        skill_data: Optional[Dict[str, Any]] = None

        if self.model is not None:
            prompt = (
                f"Generate a specialized skill for the following need:\n"
                f"- Requested Skill ID/Name: {skill_id}\n"
                f"- Description/Requirements: {skill_description}\n"
                f"- User Inquiry Context: {user_query}\n"
                f"- Delegated Specialist Agent: {target_agent}\n\n"
                f"Output a valid GeneratedSkillSchema with id, name, description, instructions, tools, and references."
            )

            messages = [
                SystemMessage(content=self._build_system_prompt()),
                HumanMessage(content=prompt),
            ]

            try:
                if hasattr(self.model, "with_structured_output"):
                    try:
                        structured = self.model.with_structured_output(GeneratedSkillSchema)
                        res = await structured.ainvoke(
                            messages, config={"tags": ["internal", "skill_generator", "no_stream"]}
                        )
                        if isinstance(res, GeneratedSkillSchema):
                            skill_data = res.model_dump()
                        elif isinstance(res, dict):
                            skill_data = res
                    except Exception as struct_err:
                        logger.debug("Structured skill generation error: %s", struct_err)

                if skill_data is None:
                    resp = await self.model.ainvoke(
                        messages, config={"tags": ["internal", "skill_generator", "no_stream"]}
                    )
                    content = extract_text_content(resp)
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "instructions" in parsed:
                            skill_data = parsed
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("SkillGenerator model invocation failed: %s; using rule-based synthesis", exc)

        if skill_data is None:
            skill_data = self._synthesize_fallback_skill(
                skill_id=skill_id,
                skill_description=skill_description,
                user_query=user_query,
                target_agent=target_agent,
            )

        # Attempt to save generated skill to disk if target directory is available
        try:
            target_skills_dir = self._resolve_skills_dir(state or {})
            if target_skills_dir.is_dir():
                sid = skill_data.get("id", "generated-skill")
                skill_folder = target_skills_dir / sid
                if not skill_folder.exists():
                    skill_folder.mkdir(parents=True, exist_ok=True)
                    # Write carefold.yaml
                    cf_yaml = (
                        f"id: {sid}\n"
                        f"version: 0.1.0\n"
                        f"license: Apache-2.0\n"
                        f"risk_class: admin\n"
                        f"tools:\n"
                        f"  - skill-docs\n"
                        f"forbidden:\n"
                        f"  - diagnose\n"
                        f"  - prescribe\n"
                        f"  - dose\n"
                        f"  - replace_emergency_care\n"
                        f"  - instruct_stop_medication\n"
                    )
                    (skill_folder / "carefold.yaml").write_text(cf_yaml, encoding="utf-8")

                    # Write SKILL.md
                    skill_md = (
                        f"---\n"
                        f"name: {sid}\n"
                        f"description: {skill_data.get('description', '')}\n"
                        f"---\n\n"
                        f"# {skill_data.get('name', sid)}\n\n"
                        f"{skill_data.get('instructions', '')}\n\n"
                        f"## Intended Use & Safety Disclosures\n"
                        f"- Not a clinician and not emergency care\n"
                        f"- If this is an emergency, contact local emergency services\n"
                        f"- Do not change medication without the prescribing clinician\n"
                    )
                    (skill_folder / "SKILL.md").write_text(skill_md, encoding="utf-8")

                    # Write reference files
                    refs = skill_data.get("references", {})
                    if refs:
                        ref_dir = skill_folder / "references"
                        ref_dir.mkdir(parents=True, exist_ok=True)
                        for r_name, r_content in refs.items():
                            (ref_dir / r_name).write_text(r_content, encoding="utf-8")
        except Exception as disk_err:
            logger.debug("Could not write generated skill to disk: %s", disk_err)

        return skill_data

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Executes skill generation based on orchestrator or state requests."""
        missing_skill = (
            state.get("missing_skill")
            or state.get("required_skill")
            or "clinical-navigation-support"
        )
        desc = state.get("missing_skill_description", "")
        target_agent = str(state.get("current_agent") or state.get("agent_id") or "assistant")

        prompt_text = ""
        for m in reversed(state.get("messages", [])):
            if hasattr(m, "content") and getattr(m, "type", "") in ("human", "user"):
                prompt_text = str(m.content)
                break
        if not prompt_text:
            prompt_text = str(state.get("prompt", ""))

        generated = await self.generate_skill(
            skill_id=missing_skill,
            skill_description=desc,
            user_query=prompt_text,
            target_agent=target_agent,
            state=state,
        )

        existing_skills = list(state.get("generated_skills", []))
        existing_skills.append(generated)

        # Proactively ensure any required reference documents requested in state are prepared
        req_docs = list(state.get("required_docs") or [])
        provisioned_docs: List[str] = []
        for doc in req_docs:
            p = await self.ensure_reference_doc(
                skill_id=missing_skill,
                doc_name=doc,
                user_query=prompt_text,
                target_agent=target_agent,
                state=state,
            )
            if p:
                provisioned_docs.append(str(p))

        res: Dict[str, Any] = {
            "generated_skill": generated,
            "generated_skills": existing_skills,
            "skill_generation_status": "completed",
        }
        if provisioned_docs:
            res["provisioned_docs"] = provisioned_docs

        return res


__all__ = ["GeneratedSkillSchema", "SkillGeneratorNode"]
