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

"""Dynamic LLM-driven OrchestratorNode for multi-agent routing (F-47).

Replaces static regex-based SupervisorNode with dynamic LLM structured output.
Discovers available specialist agents dynamically from AgentRegistry, formats
their descriptions and tools into the prompt, and reliably routes inquiries.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from carefold.agents.registry import AgentRegistry, _extract_first_line
from carefold.config import settings
from carefold.constants.agents import AGENT_ORCHESTRATOR, DEFAULT_ROUTING_FALLBACK_AGENT
from carefold.constants.paths import AGENTS_DIR, SKILLS_DIR
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.resources.loader import get_resource_loader
from carefold.schemas.manifest import AgentManifest
from carefold.schemas.plan import AgentTask, ExecutionMode, ExecutionPlan
from carefold.templates.engine import render_template
from carefold.workflows.nodes.base import BaseNode
from carefold.workflows.state import AgentState, extract_text_content

logger = logging.getLogger(__name__)


class DomainClassification(BaseModel):
    """Structured classification output for Tier-1 domain routing."""

    domain: str = Field(
        ...,
        description="One of 'clinical', 'therapy', 'wellness', 'navigation', 'education'.",
    )
    category: str = Field(
        default="",
        description="Dot-notated subcategory path (e.g. 'navigation.insurance', 'wellness.habits').",
    )
    reasoning: str = Field(
        default="",
        description="Brief classification rationale.",
    )


TIER1_DOMAIN_CLASSIFIER_PROMPT = (
    "You are the Carefold Tier-1 Intent and Domain Classifier.\n"
    "Your objective is to analyze the user inquiry and conversation context, then classify it into "
    "exactly one primary healthcare domain and an appropriate dot-notated subcategory.\n\n"
    "## Healthcare Domains:\n"
    "1. 'clinical': Medical evaluation, symptom assessment, diagnostic triage, treatments, prescriptions, lab results, and physician guidance.\n"
    "   Example categories: clinical.triage, clinical.cardiology, clinical.pulmonology, clinical.neurology, clinical.gastroenterology, clinical.nephrology, clinical.endocrinology, clinical.oncology, clinical.orthopedics, clinical.dermatology\n\n"
    "2. 'therapy': Mental health support, counseling, emotional well-being, distress tolerance, stress management, and psychological coping.\n"
    "   Example categories: therapy.cbt, therapy.anxiety, therapy.depression, therapy.mindfulness\n\n"
    "3. 'wellness': Preventative lifestyle guidance, daily healthy habits, hydration, sleep improvement, fitness, and nutrition coaching.\n"
    "   Example categories: wellness.habits, wellness.nutrition, wellness.sleep, wellness.fitness\n\n"
    "4. 'navigation': Healthcare logistics, insurance benefits, claims, deductible/copay, prior auth, appointments, and medical paperwork.\n"
    "   Example categories: navigation.insurance, navigation.prior_auth, navigation.claims, navigation.appointments, navigation.records, navigation.formulary\n\n"
    "5. 'education': Medical literacy, physiological explanations, disease definitions, procedure overviews, and health education.\n"
    "   Example categories: education.conditions, education.procedures, education.anatomy\n\n"
    "## Output Instructions:\n"
    "- Set 'domain' to one of: 'clinical', 'therapy', 'wellness', 'navigation', 'education'.\n"
    "- Set 'category' to a dot-notated category matching the user's inquiry (e.g., 'navigation.insurance', 'wellness.habits').\n"
    "- Set 'reasoning' to a concise rationale explaining why the query belongs in this domain and category.\n"
    "Never attempt to answer clinical questions directly; classify strictly for downstream specialist routing."
)


class OrchestratorDecision(BaseModel):
    """Structured output schema for the dynamic orchestrator routing decision."""

    agent_id: str = Field(
        ...,
        description="ID of the chosen specialist agent to delegate to (e.g., 'visit-steward', 'benefits-guide', 'habit-companion', 'document-extractor').",
    )
    reasoning: str = Field(
        ...,
        description="Clear, concise rationale explaining why this specialist was selected to address the user request.",
    )
    instructions: str = Field(
        default="",
        description="Specific instructions, extracted parameters, or focus areas for the delegated specialist agent.",
    )
    missing_skill: Optional[str] = Field(
        default=None,
        description="ID or name of any missing skill that should be generated for this request, or null if all required skills are present.",
    )
    missing_skill_description: Optional[str] = Field(
        default=None,
        description="Specific domain description, guidelines, and reference materials needed for the missing skill to be generated.",
    )
    required_docs: List[str] = Field(
        default_factory=list,
        description="Specific reference doc filenames (e.g. ['symptom_log_template.md', 'checklist.md']) needed by the specialist to address the user request.",
    )


class OrchestratorNode(BaseNode):
    """Dynamic LLM-driven orchestrator node for multi-agent planning and routing."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        registry: Optional[AgentRegistry] = None,
        catalog: Optional[CatalogPort] = None,
        skill_generator: Optional[Any] = None,
        name: str = "orchestrator",
    ) -> None:
        super().__init__(name=name)
        self.model = model
        self._registry = registry
        self.catalog = catalog
        self._skill_generator = skill_generator

    @property
    def skill_generator(self) -> Any:
        """Lazily resolves SkillGeneratorNode instance."""
        if self._skill_generator is None:
            from carefold.workflows.nodes.skill_generator_node import SkillGeneratorNode
            self._skill_generator = SkillGeneratorNode(
                model=self.model,
                skills_dir=self.registry._skills_dir,
            )
        return self._skill_generator

    @property
    def registry(self) -> AgentRegistry:
        """Lazily resolves AgentRegistry from workspace root if not explicitly injected."""
        if self._registry is None:
            agents_dir = settings.get_agents_dir()
            skills_dir = settings.get_skills_dir()
            self._registry = AgentRegistry(
                agents_dir=agents_dir,
                skills_dir=skills_dir if skills_dir.is_dir() else None,
            )
        return self._registry

    def _format_candidate_agents(self, candidates: List[AgentManifest]) -> str:
        """Formats retrieved candidate agents for Tier-2 prompt."""
        blocks: List[str] = []
        for agent in candidates:
            domain_val = agent.domain.value if hasattr(agent.domain, "value") else str(agent.domain)
            cat_val = agent.category or ""
            tools_val = ", ".join(agent.tools) if agent.tools else "none"
            desc = agent.description or _extract_first_line(agent.persona)
            blocks.append(
                f"- **{agent.id}** ({agent.title}) [Domain: {domain_val}, Category: {cat_val}]\n"
                f"  Description: {desc}\n"
                f"  Tools: [{tools_val}]"
            )
        return "\n".join(blocks)

    def _build_tier2_system_prompt(self, candidates: List[AgentManifest]) -> str:
        """Assembles Tier-2 system prompt targeting candidate agents from catalog via Handlebars."""
        candidate_catalog = self._format_candidate_agents(candidates)
        prompts = get_resource_loader().get_prompts()
        base_prompt = (
            prompts.get("orchestrator", {}).get("system_prompt")
            or prompts.get("supervisor", {}).get("system_prompt")
            or (
                "You are the Carefold Orchestrator, an intelligent routing and planning coordinator.\n"
                "Analyze the conversation, user intent, and available candidate specialist agents to determine the best specialist to handle the request.\n"
                "Delegate to the single most appropriate specialist. Never answer domain-specific questions yourself."
            )
        )
        context = {
            "base_prompt": base_prompt.strip(),
            "heading": "Candidate Specialist Agents",
            "catalog": candidate_catalog,
            "target_list_name": "candidate list",
        }
        return render_template("orchestrator_routing_prompt", context)

    def _build_system_prompt(self, state: Dict[str, Any]) -> str:
        """Assembles orchestrator system prompt incorporating dynamic agent catalog from registry via Handlebars."""
        catalog = self.registry.format_agent_catalog(exclude=AGENT_ORCHESTRATOR)
        prompts = get_resource_loader().get_prompts()
        base_prompt = (
            prompts.get("orchestrator", {}).get("system_prompt")
            or prompts.get("supervisor", {}).get("system_prompt")
            or (
                "You are the Carefold Orchestrator, an intelligent routing and planning coordinator.\n"
                "Analyze the conversation, user intent, and available specialist agents to determine the best specialist to handle the request.\n"
                "Delegate to the single most appropriate specialist. Never answer domain-specific questions yourself."
            )
        )
        context = {
            "base_prompt": base_prompt.strip(),
            "heading": "Available Specialist Agents",
            "catalog": catalog,
            "target_list_name": "catalog",
        }
        return render_template("orchestrator_routing_prompt", context)

    def _resolve_pattern_fallback(self, state: Dict[str, Any], prompt_text: str) -> str:
        """Resolves target agent using attachments and externalized YAML routing patterns."""
        has_attachment = bool(
            state.get("attachments")
            or state.get("document_dossiers")
            or state.get("document_text")
            or state.get("raw_text")
        )
        if has_attachment:
            return "document-extractor"

        try:
            routing_patterns = get_resource_loader().get_routing_patterns()
            prompt_lower = prompt_text.lower()
            for agent_key, patterns in routing_patterns.items():
                if agent_key == "dossier_types" or not isinstance(patterns, list):
                    continue
                for pat in patterns:
                    import re
                    if re.search(pat, prompt_lower, re.IGNORECASE):
                        return agent_key
        except Exception as err:
            logger.debug("Failed loading external routing patterns: %s", err)

        return DEFAULT_ROUTING_FALLBACK_AGENT

    async def _execute_single_hop(
        self,
        state: Dict[str, Any],
        prompt_text: str,
        raw_messages: List[Any],
    ) -> OrchestratorDecision:
        """Executes legacy single-hop dynamic catalog prompt and structured decision."""
        system_prompt = self._build_system_prompt(state)
        lc_messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]

        for m in raw_messages:
            if isinstance(m, BaseMessage):
                lc_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    lc_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    lc_messages.append(AIMessage(content=content))
                elif role == "system":
                    lc_messages.append(SystemMessage(content=content))

        decision = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(OrchestratorDecision)
                    res = await structured_model.ainvoke(
                        lc_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, OrchestratorDecision):
                        decision = res
                    elif isinstance(res, dict):
                        decision = OrchestratorDecision(**res)
                except Exception as structured_err:
                    logger.debug("with_structured_output failed: %s", structured_err)
                    decision = None

            if decision is None:
                resp = await self.model.ainvoke(
                    lc_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        decision = OrchestratorDecision(**data)
                except Exception:
                    pass

                if decision is None:
                    target = self._resolve_pattern_fallback(state, prompt_text)
                    decision = OrchestratorDecision(
                        agent_id=target,
                        reasoning=f"Parsed unstructured model response or fallback to {target}: {content[:100]}",
                        instructions="",
                    )
        except Exception as exc:
            logger.warning("Orchestrator structured model call failed (%s); triggering fallback", exc)
            target = self._resolve_pattern_fallback(state, prompt_text)
            decision = OrchestratorDecision(
                agent_id=target,
                reasoning=f"Routing model error fallback to {target}: {exc}",
                instructions="",
            )

        if decision is None:
            target = self._resolve_pattern_fallback(state, prompt_text)
            decision = OrchestratorDecision(
                agent_id=target,
                reasoning="Default decision fallback",
                instructions="",
            )

        return decision

    async def _execute_two_hop(
        self,
        state: Dict[str, Any],
        prompt_text: str,
        raw_messages: List[Any],
    ) -> Tuple[OrchestratorDecision, List[AgentManifest]]:
        """Executes Tier-1 Domain Classification followed by Tier-2 Specialist Picking via CatalogPort."""
        # 1. Tier-1 Domain Classifier invokes model.with_structured_output(DomainClassification)
        tier1_messages: List[BaseMessage] = [SystemMessage(content=TIER1_DOMAIN_CLASSIFIER_PROMPT)]
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                tier1_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    tier1_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    tier1_messages.append(AIMessage(content=content))
                elif role == "system":
                    tier1_messages.append(SystemMessage(content=content))
        if not any(
            isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") in ("user", "human"))
            for m in raw_messages
        ):
            if prompt_text:
                tier1_messages.append(HumanMessage(content=prompt_text))

        classified: Optional[DomainClassification] = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(DomainClassification)
                    res = await structured_model.ainvoke(
                        tier1_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, DomainClassification):
                        classified = res
                    elif isinstance(res, dict):
                        classified = DomainClassification(**res)
                except Exception as tier1_err:
                    logger.debug("Tier-1 with_structured_output failed: %s", tier1_err)
                    classified = None

            if classified is None:
                resp = await self.model.ainvoke(
                    tier1_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        classified = DomainClassification(**data)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Tier-1 domain classification model call failed: %s", exc)
            classified = None

        # 2. Fallback chain on CatalogPort
        candidates: List[AgentManifest] = []
        if self.catalog is not None and classified is not None:
            domain_val = classified.domain.strip() if classified.domain else ""
            cat_val = classified.category.strip() if classified.category else ""
            # Step 1: Search by domain and category
            if domain_val:
                search_cat = cat_val
                if search_cat and "." not in search_cat:
                    search_cat = f"{domain_val}.{search_cat}"
                candidates = await self.catalog.search_agents(
                    domain=domain_val,
                    category=search_cat,
                    limit=8,
                )
                if not candidates and search_cat != cat_val:
                    candidates = await self.catalog.search_agents(
                        domain=domain_val,
                        category=cat_val,
                        limit=8,
                    )
                # Step 2: If 0 candidates, search by domain only
                if not candidates:
                    candidates = await self.catalog.search_agents(
                        domain=domain_val,
                        limit=8,
                    )

        # Step 3: If 0 candidates, search by FTS query on tags/prompt
        if not candidates and self.catalog is not None:
            candidates = await self.catalog.search_agents(
                query=prompt_text,
                limit=8,
            )

        # Step 4: If 0 candidates, fall back to pattern fallback
        if not candidates:
            target = self._resolve_pattern_fallback(state, prompt_text)
            return (
                OrchestratorDecision(
                    agent_id=target,
                    reasoning=f"Catalog fallback chain returned 0 candidates; pattern fallback to {target}",
                    instructions="",
                ),
                [],
            )

        # 3. Tier-2 Specialist Picker targeting candidate set
        tier2_prompt = self._build_tier2_system_prompt(candidates)
        tier2_messages: List[BaseMessage] = [SystemMessage(content=tier2_prompt)]
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                tier2_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    tier2_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    tier2_messages.append(AIMessage(content=content))
                elif role == "system":
                    tier2_messages.append(SystemMessage(content=content))
        if not any(
            isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") in ("user", "human"))
            for m in raw_messages
        ):
            if prompt_text:
                tier2_messages.append(HumanMessage(content=prompt_text))

        decision: Optional[OrchestratorDecision] = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(OrchestratorDecision)
                    res = await structured_model.ainvoke(
                        tier2_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, OrchestratorDecision):
                        decision = res
                    elif isinstance(res, dict):
                        decision = OrchestratorDecision(**res)
                except Exception as tier2_err:
                    logger.debug("Tier-2 with_structured_output failed: %s", tier2_err)
                    decision = None

            if decision is None:
                resp = await self.model.ainvoke(
                    tier2_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        decision = OrchestratorDecision(**data)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Tier-2 specialist picker model call failed (%s); using candidate fallback", exc)
            decision = None

        if decision is None:
            fallback_id = candidates[0].id if candidates else self._resolve_pattern_fallback(state, prompt_text)
            decision = OrchestratorDecision(
                agent_id=fallback_id,
                reasoning=f"Tier-2 structured invocation fallback to candidate: {fallback_id}",
                instructions="",
            )

        return decision, candidates

    def _route(
        self,
        target_agent: str,
        prompt_text: str,
        state: Dict[str, Any],
        decision: Optional[OrchestratorDecision] = None,
        candidates: Optional[List[AgentManifest]] = None,
        is_explicit: bool = False,
    ) -> ExecutionPlan:
        """Constructs a typed ExecutionPlan evaluating topological mode (single, parallel, pipeline)."""
        if not is_explicit and state.get("explicit_agent"):
            is_explicit = True

        # 1. Respect pre-existing ExecutionPlan if present in state
        existing_plan = state.get("execution_plan")
        if isinstance(existing_plan, dict) and existing_plan.get("mode"):
            try:
                return ExecutionPlan.model_validate(existing_plan)
            except Exception:
                pass
        elif isinstance(existing_plan, ExecutionPlan):
            return existing_plan

        prompt_lower = prompt_text.lower()

        # 2. Check for cross-functional pipeline mode: specialty -> administrative (prior auth / formulary / claims)
        auth_keywords = (
            "prior auth",
            "prior-auth",
            "pre-authorization",
            "preauthorization",
            "authorization",
            "pre-approval",
            "approval",
            "formulary",
            "tier exception",
            "coverage",
            "copay",
            "claim",
            "appeal",
            "denial",
        )
        specialty_keywords = (
            "ortho",
            "surgery",
            "surgical",
            "procedure",
            "mri",
            "knee",
            "hip",
            "joint",
            "infusion",
            "biologic",
            "cardio",
            "cardiac",
            "oncology",
            "cancer",
            "chemo",
            "chemotherapy",
            "medication",
            "prescribe",
            "treatment",
        )
        nav_agent_ids = {
            "prior-auth-navigator",
            "formulary-guide",
            "claims-appeals-guide",
            "benefits-guide",
        }

        has_auth_kw = any(kw in prompt_lower for kw in auth_keywords)
        has_spec_kw = any(kw in prompt_lower for kw in specialty_keywords)

        coordination_keywords = (
            "coordinate",
            "consult both",
            "both specialists",
            "multi-specialist",
            "multiple specialists",
            "team of specialists",
            "concurrent",
        )
        explicit_coordination = any(ck in prompt_lower for ck in coordination_keywords)

        is_cross_functional = (
            not (is_explicit and not explicit_coordination)
            and (
                (has_auth_kw and has_spec_kw)
                or (target_agent in nav_agent_ids and has_spec_kw)
                or (target_agent not in nav_agent_ids and has_auth_kw)
            )
        )

        if is_cross_functional:
            if "formulary" in prompt_lower:
                secondary_agent = "formulary-guide"
            elif any(k in prompt_lower for k in ("claim", "appeal", "denial")):
                secondary_agent = "claims-appeals-guide"
            elif any(k in prompt_lower for k in ("copay", "deductible", "benefit")):
                secondary_agent = "benefits-guide"
            else:
                secondary_agent = "prior-auth-navigator"

            if target_agent in nav_agent_ids:
                secondary_agent = target_agent
                if any(k in prompt_lower for k in ("ortho", "surgery", "knee", "hip", "joint")):
                    primary_agent = "ortho-guide"
                elif any(k in prompt_lower for k in ("cardio", "heart", "cardiac", "hypertension")):
                    primary_agent = "cardiology-guide"
                elif any(k in prompt_lower for k in ("oncology", "cancer", "tumor", "chemo")):
                    primary_agent = "oncology-navigator"
                else:
                    primary_agent = None

                if primary_agent is None:
                    instructions = decision.instructions if decision and decision.instructions else ""
                    reasoning = (
                        decision.reasoning
                        if decision and decision.reasoning
                        else f"Direct administrative/navigation query handled by {target_agent}"
                    )
                    return ExecutionPlan(
                        mode=ExecutionMode.SINGLE,
                        target_agents=[target_agent],
                        tasks=[
                            AgentTask(
                                agent_id=target_agent,
                                instructions=instructions,
                                task_description=instructions or f"Navigation consultation with {target_agent}",
                                priority=1,
                            )
                        ],
                        reasoning=reasoning,
                    )
            else:
                primary_agent = target_agent

            target_agents = [primary_agent, secondary_agent]
            plan_tasks = [
                AgentTask(
                    agent_id=primary_agent,
                    instructions=f"Clinical evaluation and preparation for {primary_agent}",
                    task_description="Clinical assessment and treatment plan",
                    priority=1,
                ),
                AgentTask(
                    agent_id=secondary_agent,
                    instructions=f"Verify coverage and authorization based on {primary_agent} findings",
                    task_description="Check authorization and coverage",
                    priority=2,
                    depends_on=[primary_agent],
                    dependencies=[primary_agent],
                ),
            ]
            return ExecutionPlan(
                mode=ExecutionMode.PIPELINE,
                target_agents=target_agents,
                tasks=plan_tasks,
                reasoning=f"Cross-functional consultation with insurance authorization dependency ({primary_agent} -> {secondary_agent})",
            )

        # 3. Check for multimorbid presentation (parallel mode)
        # Preserve explicit single-specialist intent unless the user prompt explicitly requests multi-specialist coordination.
        if not (is_explicit and not explicit_coordination):
            condition_patterns = [
                (("heart", "cardio", "cardiac", "hypertension", "blood pressure", "chf", "congestive"), "cardiology-guide"),
                (("kidney", "renal", "ckd", "nephrology", "fluid"), "nephrology-guide"),
                (("diabetes", "glucose", "cgm", "insulin", "endocrinology", "sugar", "a1c"), "endocrinology-guide"),
                (("pulmonary", "pulmonology", "lung", "dyspnea", "breathing", "shortness of breath", "asthma", "copd"), "pulmonology-guide"),
                (("gastro", "gastroenterology", "ibs", "ibd", "bowel", "stomach", "gi tract", "crohn", "colitis"), "gastro-guide"),
                (("neurology", "migraine", "headache", "cognitive", "dementia", "neuropathy", "seizure"), "neurology-guide"),
                (("rheumatology", "arthritis", "lupus", "joint pain", "autoimmune"), "rheuma-guide"),
                (("dermatology", "rash", "skin", "lesion", "eczema", "psoriasis"), "derma-guide"),
                (("orthopedic", "ortho", "joint mobility", "bone", "fracture"), "ortho-guide"),
                (("oncology", "cancer", "tumor", "oncologist"), "oncology-navigator"),
            ]

            multimorbid_agents: List[str] = []
            for keywords, ag_id in condition_patterns:
                if any(kw in prompt_lower for kw in keywords):
                    if ag_id not in multimorbid_agents:
                        multimorbid_agents.append(ag_id)

            if target_agent in multimorbid_agents:
                multimorbid_agents.remove(target_agent)
                multimorbid_agents.insert(0, target_agent)

            if len(multimorbid_agents) >= 2:
                plan_tasks = [
                    AgentTask(
                        agent_id=ag_id,
                        instructions=f"Specialist assessment and tracking for {ag_id}",
                        task_description=f"Specialist evaluation for {ag_id}",
                        priority=1,
                    )
                    for ag_id in multimorbid_agents
                ]
                return ExecutionPlan(
                    mode=ExecutionMode.PARALLEL,
                    target_agents=multimorbid_agents,
                    tasks=plan_tasks,
                    reasoning=f"Multimorbid presentation requiring concurrent specialist guidance from: {', '.join(multimorbid_agents)}",
                )

        # 4. Single-agent mode
        instructions = decision.instructions if decision and decision.instructions else ""
        reasoning = decision.reasoning if decision and decision.reasoning else f"Focused single-specialty question for {target_agent}"
        return ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            target_agents=[target_agent],
            tasks=[
                AgentTask(
                    agent_id=target_agent,
                    instructions=instructions,
                    task_description=instructions or f"Consultation with {target_agent}",
                    priority=1,
                )
            ],
            reasoning=reasoning,
        )

    async def _preflight_prepare_skills_and_docs(
        self,
        target_agent: str,
        missing_skill: Optional[str],
        missing_skill_description: str,
        required_docs: List[str],
        prompt_text: str,
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
        """Proactively provisions missing skills and dynamically resolves reference docs from SkillManifest.references."""
        generated_skills = list(state.get("generated_skills", []))
        generated_skill = None
        provisioned_docs: List[str] = []
        provisioned_references: Dict[str, Dict[str, Any]] = dict(state.get("provisioned_references", {}))

        manifest = self.registry.get(target_agent)
        # 1. Detect missing skill
        if not missing_skill and manifest and manifest.skills:
            loaded_ids = {s.id for s in self.registry.get_loaded_skills(target_agent)}
            for sk_id in manifest.skills:
                if sk_id not in loaded_ids:
                    missing_skill = sk_id
                    missing_skill_description = f"Required declared skill '{sk_id}' for agent '{target_agent}' is missing."
                    break

        if missing_skill:
            logger.info("Orchestrator pre-flight provisioning missing skill '%s'", missing_skill)
            generated_skill = await self.skill_generator.generate_skill(
                skill_id=missing_skill,
                skill_description=missing_skill_description,
                user_query=prompt_text,
                target_agent=target_agent,
                state=state,
            )
            generated_skills.append(generated_skill)

        # 2. Generic Dynamic Reference Provisioner (Zero Hardcoding)
        # Identify all relevant target agents from execution plan or target_agent
        agents_to_scan = [target_agent]
        plan_dict = state.get("execution_plan")
        if isinstance(plan_dict, dict):
            for ag in plan_dict.get("target_agents", []):
                if ag not in agents_to_scan:
                    agents_to_scan.append(ag)

        explicit_reqs = set(required_docs) | set(state.get("required_docs", []))
        req_docs: List[str] = list(explicit_reqs)
        doc_skill_map: Dict[str, str] = {}
        prompt_lower = prompt_text.lower()

        # Dynamic scanning over declared SkillManifest.references
        for ag_id in agents_to_scan:
            ag_manifest = self.registry.get(ag_id)
            if not ag_manifest:
                continue
            for sk_id in (ag_manifest.skills or []):
                sk = self.registry.get_skill(sk_id)
                if not sk or not sk.references:
                    continue
                for ref_doc in sk.references:
                    ref_stem = Path(ref_doc).stem.replace("_", " ").replace("-", " ").lower()
                    stem_tokens = [tok for tok in re.findall(r"\w+", ref_stem) if len(tok) > 3]
                    if ref_doc in explicit_reqs or any(tok in prompt_lower for tok in stem_tokens):
                        if ref_doc not in req_docs:
                            req_docs.append(ref_doc)
                        doc_skill_map[ref_doc] = sk_id

        # Also inspect dynamically generated skills for references
        for gen_sk_item in generated_skills:
            g_id = gen_sk_item.get("id") or ""
            g_refs = gen_sk_item.get("references") or {}
            for ref_doc in g_refs.keys():
                ref_stem = Path(ref_doc).stem.replace("_", " ").replace("-", " ").lower()
                stem_tokens = [tok for tok in re.findall(r"\w+", ref_stem) if len(tok) > 3]
                if ref_doc in explicit_reqs or any(tok in prompt_lower for tok in stem_tokens):
                    if ref_doc not in req_docs:
                        req_docs.append(ref_doc)
                    doc_skill_map[ref_doc] = g_id

        # Fallback assignment for explicitly requested documents not yet tied to a skill
        for doc in req_docs:
            if doc not in doc_skill_map:
                target_sk = None
                if manifest and manifest.skills:
                    for sk_id in manifest.skills:
                        sk = self.registry.get_skill(sk_id)
                        if sk and (doc in sk.references or any(r.lower() == doc.lower() for r in sk.references)):
                            target_sk = sk_id
                            break
                    if target_sk is None:
                        other_skill_owns = False
                        for loaded_sk in getattr(self.registry, "_loaded_skills", {}).values():
                            for item in loaded_sk:
                                if item.id not in manifest.skills and (
                                    doc in item.references or any(r.lower() == doc.lower() for r in item.references)
                                ):
                                    other_skill_owns = True
                                    break
                            if other_skill_owns:
                                break
                        if not other_skill_owns:
                            target_sk = manifest.skills[0]
                doc_skill_map[doc] = target_sk or "general-reference"

        # Resolve target skills directory
        target_skills_dir = self.registry._skills_dir
        if not target_skills_dir:
            if state.get("skills_dir"):
                target_skills_dir = Path(state["skills_dir"]).resolve()
            elif state.get("workspace_root"):
                target_skills_dir = Path(state["workspace_root"]).resolve() / SKILLS_DIR
            else:
                target_skills_dir = settings.get_skills_dir().resolve()

        # Load matched reference documents with in-memory synthesis fallback
        for doc in req_docs:
            sk_id = doc_skill_map.get(doc, "general-reference")
            doc_title = Path(doc).stem.replace("_", " ").replace("-", " ").title()
            doc_content = ""

            # 1. Attempt to read file content from disk if available
            ref_file = target_skills_dir / sk_id / "references" / doc if target_skills_dir and sk_id else None
            if ref_file and ref_file.is_file():
                try:
                    doc_content = ref_file.read_text(encoding="utf-8")
                except Exception:
                    pass

            # 2. Check generated_skills in-memory reference map if present
            if not doc_content:
                for gen_sk_item in generated_skills:
                    refs_map = gen_sk_item.get("references") or {}
                    if doc in refs_map:
                        doc_content = refs_map[doc]
                        break

            # 3. If missing, synthesize via skill_generator
            if not doc_content and hasattr(self.skill_generator, "synthesize_reference_doc"):
                try:
                    synth_res = await self.skill_generator.synthesize_reference_doc(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                        state=state,
                    )
                    doc_content = synth_res.get("content", "")
                except Exception as synth_err:
                    logger.warning("SkillGenerator synthesis error for '%s': %s", doc, synth_err)

            if not doc_content and hasattr(self.skill_generator, "ensure_reference_doc"):
                try:
                    p = await self.skill_generator.ensure_reference_doc(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                        state=state,
                    )
                    if p and Path(p).is_file():
                        doc_content = Path(p).read_text(encoding="utf-8")
                except Exception as ensure_err:
                    logger.warning("ensure_reference_doc error: %s", ensure_err)

            # 4. Guaranteed in-memory fallback
            if not doc_content:
                if hasattr(self.skill_generator, "synthesize_reference_doc_content"):
                    doc_content = self.skill_generator.synthesize_reference_doc_content(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                    )
                elif hasattr(self.skill_generator, "_synthesize_reference_doc_content"):
                    doc_content = self.skill_generator._synthesize_reference_doc_content(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                    )
                else:
                    doc_content = f"# {doc_title}\nSynthesized clinical reference document."

            provisioned_references[doc] = {
                "title": doc_title,
                "content": doc_content,
                "skill_id": sk_id,
            }
            provisioned_docs.append(doc)

        state["provisioned_references"] = provisioned_references
        state["provisioned_docs"] = list(provisioned_references.keys())

        # 3. Reload registry if any skill or doc was provisioned
        if missing_skill or provisioned_docs:
            try:
                self.registry.reload()
            except Exception:
                pass

        return generated_skills, generated_skill, provisioned_docs

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Classifies user intent, selects specialist agent, and outputs routing state."""
        # Extract last human prompt text early for context
        prompt_text = ""
        for m in reversed(state.get("messages", [])):
            if isinstance(m, dict) and m.get("role") in ("user", "human"):
                prompt_text = str(m.get("content") or "")
                break
            elif isinstance(m, HumanMessage) or (isinstance(m, BaseMessage) and getattr(m, "type", "") in ("human", "user")):
                prompt_text = str(getattr(m, "content", "") or "")
                break
        if not prompt_text and state.get("prompt"):
            prompt_text = str(state.get("prompt"))

        # 1. Explicit routing bypass (e.g., user selected agent in UI or pre-routed system state)
        explicit = state.get("explicit_agent") or state.get("routed_subgraph") or state.get("current_agent")
        if explicit and explicit not in ("orchestrator", "supervisor", "unknown"):
            raw_explicit = str(explicit).strip()
            if self.registry.get(raw_explicit) is not None:
                normalized = raw_explicit
            elif raw_explicit.startswith("_"):
                normalized = raw_explicit.lower()
            else:
                normalized = raw_explicit.lower().replace("_", "-")

            # Route execution plan with explicit flag
            plan = self._route(
                target_agent=normalized,
                prompt_text=prompt_text,
                state=state,
                is_explicit=True,
            )
            state["execution_plan"] = plan.model_dump()

            # Pre-flight check and provision skills and docs for explicit target
            missing_sk = state.get("missing_skill") or state.get("required_skill")
            gen_skills, gen_sk, prov_docs = await self._preflight_prepare_skills_and_docs(
                target_agent=normalized,
                missing_skill=missing_sk,
                missing_skill_description=state.get("missing_skill_description", ""),
                required_docs=state.get("required_docs", []),
                prompt_text=prompt_text,
                state=state,
            )

            res_dict: Dict[str, Any] = {
                "current_agent": normalized,
                "routed_subgraph": normalized,
                "agent_id": normalized,
                "orchestrator_reasoning": "Explicitly requested by user or pre-routed system state.",
                "orchestrator_instructions": state.get("orchestrator_instructions", ""),
                "next_step": normalized,
                "execution_plan": plan.model_dump(),
                "provisioned_references": state.get("provisioned_references", {}),
                "provisioned_docs": list(state.get("provisioned_references", {}).keys()),
            }
            if gen_skills:
                res_dict["generated_skills"] = gen_skills
            if gen_sk:
                res_dict["generated_skill"] = gen_sk
            return res_dict

        # 2. Check model availability and routing mode
        candidates: List[AgentManifest] = []
        raw_messages = list(state.get("messages", []))

        if self.model is None:
            # Fallback when model is not provided (e.g. offline unit tests)
            target = self._resolve_pattern_fallback(state, prompt_text)
            decision = OrchestratorDecision(
                agent_id=target,
                reasoning=f"Model unconfigured; externalized pattern or fallback match: {target}",
                instructions="",
            )
        elif self.catalog is None:
            # Backward compatibility: execute single-hop routing flow
            decision = await self._execute_single_hop(state, prompt_text, raw_messages)
        else:
            # Two-Hop routing flow via CatalogPort
            decision, candidates = await self._execute_two_hop(state, prompt_text, raw_messages)

        if decision is None:
            target = self._resolve_pattern_fallback(state, prompt_text)
            decision = OrchestratorDecision(
                agent_id=target,
                reasoning="Default decision fallback",
                instructions="",
            )

        # 3. Validate selected agent_id exists in registry or candidates
        selected_id = str(decision.agent_id).strip().lower().replace("_", "-")
        candidate_ids = {c.id for c in candidates} if candidates else set()
        if not self.registry.get(selected_id) and selected_id not in candidate_ids:
            if candidates:
                fallback_id = candidates[0].id
            else:
                delegatable = self.registry.get_delegatable_agents(exclude=AGENT_ORCHESTRATOR)
                fallback_id = delegatable[0].id if delegatable else DEFAULT_ROUTING_FALLBACK_AGENT
            decision.reasoning += f" (original choice '{decision.agent_id}' not found in registry; fell back to '{fallback_id}')"
            selected_id = fallback_id

        # Route execution plan
        plan = self._route(
            target_agent=selected_id,
            prompt_text=prompt_text,
            state=state,
            decision=decision,
            candidates=candidates,
            is_explicit=False,
        )
        state["execution_plan"] = plan.model_dump()

        # 4. Pre-flight check: provision any missing skills or required reference documents before specialist execution
        missing_skill_name = (
            getattr(decision, "missing_skill", None)
            or state.get("missing_skill")
            or state.get("required_skill")
        )
        missing_skill_desc = (
            getattr(decision, "missing_skill_description", None)
            or state.get("missing_skill_description", "")
        )
        required_docs = list(getattr(decision, "required_docs", []) or [])

        generated_skills, generated_skill, provisioned_docs = await self._preflight_prepare_skills_and_docs(
            target_agent=selected_id,
            missing_skill=missing_skill_name,
            missing_skill_description=missing_skill_desc,
            required_docs=required_docs,
            prompt_text=prompt_text,
            state=state,
        )

        effective_agent = plan.target_agents[0] if plan.target_agents else selected_id

        result_payload: Dict[str, Any] = {
            "current_agent": effective_agent,
            "routed_subgraph": effective_agent,
            "agent_id": effective_agent,
            "orchestrator_reasoning": decision.reasoning,
            "orchestrator_instructions": decision.instructions,
            "next_step": effective_agent,
            "execution_plan": plan.model_dump(),
            "provisioned_references": state.get("provisioned_references", {}),
            "provisioned_docs": list(state.get("provisioned_references", {}).keys()),
        }
        if generated_skills:
            result_payload["generated_skills"] = generated_skills
        if generated_skill:
            result_payload["generated_skill"] = generated_skill

        return result_payload


__all__ = [
    "DomainClassification",
    "OrchestratorDecision",
    "OrchestratorNode",
    "TIER1_DOMAIN_CLASSIFIER_PROMPT",
]
