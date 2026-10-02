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

"""Agent catalog discovery and detail endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    ROUTE_AGENT_DETAIL,
    ROUTE_AGENTS,
    ROUTE_AGENTS_CATEGORIES,
)
from carefold.constants.defaults import BUNDLED_AGENT_IDS
from carefold.constants.paths import SYSTEM_AGENTS_DIR
from carefold.loaders.agent_loader import (
    ManifestValidationError,
    extract_fallback_description,
    find_agent_dir,
    load_agent,
    load_agent_readme,
    load_agent_starters,
    load_all_agents,
)
from carefold.schemas.manifest import (
    SLUG_REGEX,
    AgentDetailResponse,
    AgentSummary,
    ResolvedSkillSummary,
    RiskClass,
    ToolDefinitionSchema,
)
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS

router = APIRouter(tags=["Agents"])


@router.get(ROUTE_AGENTS, response_model=List[AgentSummary])
async def list_agents(
    risk_class: Optional[str] = Query(None, description="Filter by risk class"),
    search: Optional[str] = Query(None, description="Search term for title/id"),
    allow_clinical: bool = Query(False, description="Enable clinical agents"),
    include_hidden: bool = Query(False, description="Include internal helper agents"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category or prefix"),
    page: Optional[int] = Query(None, ge=1, description="Page number (1-based)"),
    per_page: int = Query(20, ge=1, description="Items per page"),
) -> List[AgentSummary]:
    """Lists all available agents in the workspace."""
    agents_dir = settings.get_agents_dir()
    skills_dir = settings.get_skills_dir()

    agents = load_all_agents(agents_dir, skills_dir)

    filtered = agents
    if not include_hidden:
        filtered = [a for a in filtered if not getattr(a, "hidden", False)]

    if risk_class:
        filtered = [a for a in filtered if a.risk_class.lower() == risk_class.lower()]

    if search:
        s_term = search.lower()
        filtered = [
            a for a in filtered
            if s_term in a.id.lower() or s_term in a.title.lower() or s_term in a.description.lower()
        ]

    if domain:
        d = domain.lower().strip()
        filtered = [
            a for a in filtered
            if (a.domain.value if hasattr(a.domain, "value") else str(a.domain or "")).lower() == d
        ]

    if category:
        c = category.lower().strip()
        filtered = [
            a for a in filtered
            if (a.category or "").lower() == c or (a.category or "").lower().startswith(f"{c}.")
        ]

    if not allow_clinical:
        for a in filtered:
            if a.risk_class == RiskClass.CLINICAL_ASSIST.value:
                a.clinical_enabled = False

    if page is not None:
        start = (page - 1) * per_page
        end = start + per_page
        filtered = filtered[start:end]

    return filtered


@router.get(ROUTE_AGENTS_CATEGORIES, response_model=Dict[str, Any])
async def get_agent_categories() -> Dict[str, Any]:
    """Returns hierarchical category tree with counts."""
    try:
        from carefold.memory.factory import get_catalog_port
        catalog = get_catalog_port()
        tree = await catalog.get_category_tree()
        if tree and (tree.get("total", 0) > 0 or (isinstance(tree, dict) and any(k not in ("total", "domains") for k in tree))):
            res = dict(tree)
            if "domains" in res and isinstance(res["domains"], dict):
                for k, v in res["domains"].items():
                    if k not in res:
                        res[k] = v
            return res
    except Exception:
        pass

    # Fallback computed directly from loaded agent manifests
    agents_dir = settings.get_agents_dir()
    skills_dir = settings.get_skills_dir()
    agents = load_all_agents(agents_dir, skills_dir)
    rows = []
    for a in agents:
        if getattr(a, "hidden", False):
            continue
        domain_val = a.domain.value if hasattr(a.domain, "value") else str(a.domain or "wellness")
        rows.append({"domain": domain_val, "category": a.category or ""})

    from carefold.memory.adapters.sqlite.catalog_adapter import build_category_tree_from_rows
    tree = build_category_tree_from_rows(rows)
    res = dict(tree)
    if "domains" in res and isinstance(res["domains"], dict):
        for k, v in res["domains"].items():
            if k not in res:
                res[k] = v
    return res


@router.get(ROUTE_AGENT_DETAIL, response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    allow_clinical: bool = Query(False, description="Explicit consent for clinical assist"),
) -> AgentDetailResponse:
    """Returns detailed configuration, persona, tools, and resolved skills for a specific agent."""
    if not SLUG_REGEX.match(agent_id) or agent_id.startswith((".", "_")):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    agents_dir = settings.get_agents_dir().resolve()
    skills_dir = settings.get_skills_dir().resolve()
    agent_dir = find_agent_dir(agents_dir, agent_id)

    if not agent_dir or not agent_dir.is_dir():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    is_system = agent_dir.parent.name == SYSTEM_AGENTS_DIR

    try:
        agent, effective_tools, skills = load_agent(agent_dir, skills_dir)
        if is_system:
            agent.hidden = True
    except ManifestValidationError as err:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load agent: {err}")

    if agent.risk_class == RiskClass.CLINICAL_ASSIST and not allow_clinical:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Agent '{agent_id}' is a clinical_assist agent. Explicit user consent (allow_clinical=true) is required.",
        )

    starters = load_agent_starters(agent_dir)
    readme_text = load_agent_readme(agent_dir)
    is_bundled = agent_id in BUNDLED_AGENT_IDS

    # Persona summary
    persona_summary = agent.description or extract_fallback_description(agent.persona)

    if isinstance(agent.persona, (str, dict)):
        persona_val = agent.persona
    else:
        persona_val = agent.persona.model_dump()

    # Model configuration
    model_val = None
    if isinstance(agent.model, str):
        model_val = agent.model
    elif agent.model is not None:
        model_val = agent.model.model_dump() if hasattr(agent.model, "model_dump") else dict(agent.model)

    resolved_skills = [
        ResolvedSkillSummary(
            id=s.id,
            name=s.name,
            description=s.description,
            version=s.version,
            risk_class=s.risk_class.value,
            tools=s.tools,
        )
        for s in skills
    ]

    tool_definitions = [
        ToolDefinitionSchema(
            name=t_name,
            description=CLOSED_TOOL_DEFINITIONS[t_name]["description"],
            parameters=CLOSED_TOOL_DEFINITIONS[t_name]["parameters"],
        )
        for t_name in effective_tools
        if t_name in CLOSED_TOOL_DEFINITIONS
    ]

    return AgentDetailResponse(
        id=agent.id,
        title=agent.title,
        version=agent.version,
        license=agent.license,
        risk_class=agent.risk_class.value,
        domain=agent.domain,
        category=agent.category,
        care_stages=agent.care_stages,
        target_audience=agent.target_audience,
        tags=agent.tags,
        icon=agent.icon,
        maturity=agent.maturity,
        model=model_val,
        can_delegate=agent.can_delegate,
        max_iterations=agent.max_iterations,
        description=agent.description or persona_summary,
        hidden=agent.hidden,
        persona=persona_val,
        personaSummary=persona_summary,
        persona_file=agent.persona_file,
        skills=agent.skills,
        resolvedSkills=resolved_skills,
        tools=agent.tools,
        effectiveTools=effective_tools,
        toolDefinitions=tool_definitions,
        starters=starters,
        forbidden=agent.forbidden,
        is_bundled=is_bundled,
        isBundled=is_bundled,
        clinical_requires_flag=(agent.risk_class == RiskClass.CLINICAL_ASSIST),
        readmeText=readme_text,
    )
