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

"""Agent catalog discovery, inspection, and user-defined CRUD endpoints backed by SQL database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.api.deps import get_current_user, resolve_owner_user_id
from carefold.auth.ports import UserProfile
from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    ROUTE_AGENT_DETAIL,
    ROUTE_AGENT_DOC_DETAIL,
    ROUTE_AGENT_DOCS,
    ROUTE_AGENTS,
    ROUTE_AGENTS_CATEGORIES,
)
from carefold.constants.defaults import BUNDLED_AGENT_IDS
from carefold.constants.paths import SYSTEM_AGENTS_DIR
from carefold.db.models import Agent, KnowledgeBase, Skill
from carefold.db.session import get_db
from carefold.loaders.agent_loader import (
    ManifestValidationError,
    compute_effective_tools,
    extract_fallback_description,
    find_agent_dir,
    load_agent,
    load_agent_readme,
    load_agent_starters,
    load_all_agents,
)
from carefold.loaders.skill_loader import find_skill_dir, load_skill
from carefold.logging import get_logger
import carefold.memory.factory as memory_factory
from carefold.schemas.manifest import (
    DOC_FILENAME_REGEX,
    SLUG_REGEX,
    AgentCreateRequest,
    AgentDetailResponse,
    AgentDocsResponse,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    AgentSummary,
    DocCreateRequest,
    DocDetailResponse,
    DocSummary,
    DocUpdateRequest,
    PHASE_0_REGISTRY,
    ResolvedSkillSummary,
    RiskClass,
    ToolDefinitionSchema,
    AgentUpdateRequest,
)
from carefold.tools.registry import CLOSED_TOOL_DEFINITIONS

logger = get_logger("carefold.api.agents")

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
    db: AsyncSession = Depends(get_db),
) -> List[AgentSummary]:
    """Lists all available agents from the database (falling back to disk if unseeded)."""
    agents: List[AgentSummary] = []

    # 1. Try querying database agents
    try:
        stmt = select(Agent).order_by(Agent.title)
        res = await db.execute(stmt)
        db_agents = res.scalars().all()
        if db_agents:
            for a in db_agents:
                is_bundled = a.type in ("bundled", "system")
                starters = a.get_starters()
                tools = a.get_tools()
                skills = a.get_skills()

                effective_tools = compute_effective_tools(tools, None)

                clinical_enabled = False if a.risk_class == RiskClass.CLINICAL_ASSIST.value and not allow_clinical else True
                agents.append(
                    AgentSummary(
                        id=a.id,
                        title=a.title,
                        version="0.1.0",
                        risk_class=a.risk_class,
                        domain=AgentDomain(a.domain) if a.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
                        category=a.category,
                        tags=a.get_tags(),
                        care_stages=a.get_care_stages(),
                        target_audience=a.get_target_audience(),
                        forbidden=a.get_forbidden(),
                        icon=a.icon,
                        maturity=AgentMaturity(a.maturity) if a.maturity in [m.value for m in AgentMaturity] else AgentMaturity.STABLE,
                        skills=skills,
                        effectiveTools=effective_tools,
                        tools=tools,
                        starters=starters,
                        startersCount=len(starters),
                        description=a.description,
                        can_delegate=a.can_delegate,
                        max_iterations=a.max_iterations,
                        is_bundled=is_bundled,
                        isBundled=is_bundled,
                        type=a.type,
                        clinical_enabled=clinical_enabled,
                        verified=True,
                        hidden=a.hidden,
                    )
                )
    except Exception as err:
        logger.warning("db_agent_query_failed_falling_back_to_disk", error=str(err))

    # 2. Fallback to disk if database had no records
    if not agents:
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
            if a.risk_class == RiskClass.CLINICAL_ASSIST.value or a.risk_class == "clinical_assist":
                a.clinical_enabled = False

    if page is not None:
        start = (page - 1) * per_page
        end = start + per_page
        filtered = filtered[start:end]

    return filtered


@router.get(ROUTE_AGENTS_CATEGORIES, response_model=Dict[str, Any])
async def get_agent_categories() -> Dict[str, Any]:
    """Returns the full hierarchical category tree and agent counts across all domains."""
    try:
        catalog = memory_factory.get_catalog_port()
        tree = await catalog.get_category_tree()
        total_count = tree.get("total", 0) if isinstance(tree, dict) else 0
        if total_count == 0 and isinstance(tree, dict):
            domains_dict = tree.get("domains", tree)
            if isinstance(domains_dict, dict):
                total_count = sum(v.get("count", 0) for v in domains_dict.values() if isinstance(v, dict))

        if total_count > 0:
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


@router.post(ROUTE_AGENTS, response_model=AgentDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentDetailResponse:
    """Creates a new user-defined specialist agent in the database."""
    stmt = select(Agent).where(Agent.id == payload.id)
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with ID '{payload.id}' already exists.",
        )

    domain_val = payload.domain.value if hasattr(payload.domain, "value") else str(payload.domain)
    risk_val = payload.risk_class.value if hasattr(payload.risk_class, "value") else str(payload.risk_class)

    new_agent = Agent(
        id=payload.id,
        type="user",
        user_id=resolve_owner_user_id(user),
        title=payload.title,
        description=payload.description,
        persona=payload.persona,
        model=payload.model,
        skills_json=json.dumps(payload.skills),
        tools_json=json.dumps(payload.tools),
        starters_json=json.dumps(payload.starters),
        domain=domain_val,
        category=payload.category,
        risk_class=risk_val,
        tags_json=json.dumps(payload.tags),
        icon=payload.icon,
        maturity="stable",
        can_delegate=payload.can_delegate,
        max_iterations=payload.max_iterations,
        hidden=False,
        is_public=payload.is_public,
    )
    db.add(new_agent)
    await db.commit()
    await db.refresh(new_agent)

    # Index in CatalogPort
    try:
        catalog = memory_factory.get_catalog_port()
        manifest = AgentManifest(
            id=new_agent.id,
            title=new_agent.title,
            description=new_agent.description,
            persona=new_agent.persona,
            model=new_agent.model,
            skills=payload.skills,
            tools=payload.tools,
            domain=payload.domain,
            category=new_agent.category,
            risk_class=payload.risk_class,
            tags=payload.tags,
            icon=new_agent.icon,
            can_delegate=new_agent.can_delegate,
            max_iterations=new_agent.max_iterations,
        )
        await catalog.index_agent(manifest)
    except Exception as idx_err:
        logger.warning("failed_to_index_created_agent", agent_id=new_agent.id, error=str(idx_err))

    effective_tools = compute_effective_tools(payload.tools, [])

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
        id=new_agent.id,
        title=new_agent.title,
        version="0.1.0",
        risk_class=new_agent.risk_class,
        domain=payload.domain,
        category=new_agent.category,
        tags=payload.tags,
        icon=new_agent.icon,
        maturity=AgentMaturity.STABLE,
        model=new_agent.model,
        can_delegate=new_agent.can_delegate,
        max_iterations=new_agent.max_iterations,
        description=new_agent.description,
        hidden=new_agent.hidden,
        persona=new_agent.persona,
        personaSummary=new_agent.description or new_agent.persona[:120],
        skills=payload.skills,
        resolvedSkills=[],
        tools=payload.tools,
        effectiveTools=effective_tools,
        toolDefinitions=tool_definitions,
        starters=payload.starters,
        forbidden=[],
        is_bundled=False,
        isBundled=False,
        type="user",
        clinical_requires_flag=(new_agent.risk_class == RiskClass.CLINICAL_ASSIST.value),
    )


@router.get(ROUTE_AGENT_DETAIL, response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    allow_clinical: bool = Query(False, description="Explicit consent for clinical assist"),
    db: AsyncSession = Depends(get_db),
) -> AgentDetailResponse:
    """Returns detailed configuration, persona, tools, and resolved skills for a specific agent."""
    if not SLUG_REGEX.match(agent_id) or agent_id.startswith((".", "_")):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    # 1. Query database
    db_agent = None
    try:
        stmt = select(Agent).where(Agent.id == agent_id)
        res = await db.execute(stmt)
        db_agent = res.scalar_one_or_none()
    except Exception as db_err:
        logger.warning("db_get_agent_query_failed", agent_id=agent_id, error=str(db_err))

    if db_agent is not None:
        if db_agent.risk_class == RiskClass.CLINICAL_ASSIST.value and not allow_clinical:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"Agent '{agent_id}' is a clinical_assist agent. Explicit user consent (allow_clinical=true) is required.",
            )

        agent_skills = db_agent.get_skills()
        agent_tools = db_agent.get_tools()
        starters = db_agent.get_starters()

        # Resolve skills from Skill table
        resolved_skills: List[ResolvedSkillSummary] = []
        skill_tools: List[str] = []
        if agent_skills:
            try:
                sk_stmt = select(Skill).where(Skill.id.in_(agent_skills))
                sk_res = await db.execute(sk_stmt)
                for sk in sk_res.scalars().all():
                    resolved_skills.append(
                        ResolvedSkillSummary(
                            id=sk.id,
                            name=sk.name,
                            title=sk.title,
                            description=sk.description,
                            version="0.1.0",
                            risk_class=sk.risk_class,
                            tools=sk.get_tools(),
                        )
                    )
                    skill_tools.extend(sk.get_tools())
            except Exception as sk_err:
                logger.warning("db_resolve_agent_skills_failed", agent_id=agent_id, error=str(sk_err))

        effective_tools = compute_effective_tools(agent_tools, resolved_skills)

        tool_definitions = [
            ToolDefinitionSchema(
                name=t_name,
                description=CLOSED_TOOL_DEFINITIONS[t_name]["description"],
                parameters=CLOSED_TOOL_DEFINITIONS[t_name]["parameters"],
            )
            for t_name in effective_tools
            if t_name in CLOSED_TOOL_DEFINITIONS
        ]

        is_bundled = db_agent.type in ("bundled", "system")
        return AgentDetailResponse(
            id=db_agent.id,
            title=db_agent.title,
            version="0.1.0",
            risk_class=db_agent.risk_class,
            domain=AgentDomain(db_agent.domain) if db_agent.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
            category=db_agent.category,
            tags=db_agent.get_tags(),
            care_stages=db_agent.get_care_stages(),
            target_audience=db_agent.get_target_audience(),
            forbidden=db_agent.get_forbidden(),
            icon=db_agent.icon,
            maturity=AgentMaturity(db_agent.maturity) if db_agent.maturity in [m.value for m in AgentMaturity] else AgentMaturity.STABLE,
            model=db_agent.model,
            can_delegate=db_agent.can_delegate,
            max_iterations=db_agent.max_iterations,
            description=db_agent.description,
            hidden=db_agent.hidden,
            persona=db_agent.persona,
            personaSummary=db_agent.description or db_agent.persona[:120],
            skills=agent_skills,
            resolvedSkills=resolved_skills,
            tools=agent_tools,
            effectiveTools=effective_tools,
            toolDefinitions=tool_definitions,
            starters=starters,
            is_bundled=is_bundled,
            isBundled=is_bundled,
            type=db_agent.type,
            clinical_requires_flag=(db_agent.risk_class == RiskClass.CLINICAL_ASSIST.value),
        )

    # 2. Fallback to disk
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

    persona_summary = agent.description or extract_fallback_description(agent.persona)
    persona_val = agent.persona if isinstance(agent.persona, (str, dict)) else agent.persona.model_dump()

    model_val = agent.model if isinstance(agent.model, str) else (agent.model.model_dump() if agent.model is not None else None)

    resolved_skills = [
        ResolvedSkillSummary(
            id=s.id,
            name=s.name,
            title=getattr(s, "title", None) or s.name.replace("_", " ").replace("-", " ").title(),
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
        type="bundled",
        clinical_requires_flag=(agent.risk_class == RiskClass.CLINICAL_ASSIST),
        readmeText=readme_text,
    )


@router.put(ROUTE_AGENT_DETAIL, response_model=AgentDetailResponse)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentDetailResponse:
    """Updates metadata, persona, and skill attachments for an agent."""
    stmt = select(Agent).where(Agent.id == agent_id)
    res = await db.execute(stmt)
    agent = res.scalar_one_or_none()

    if agent is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    if agent.type in ("bundled", "system") and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Cannot modify system/bundled agent '{agent_id}'. Only custom agents can be updated.",
        )

    if payload.title is not None:
        agent.title = payload.title
    if payload.description is not None:
        agent.description = payload.description
    if payload.persona is not None:
        agent.persona = payload.persona
    if payload.model is not None:
        agent.model = payload.model
    if payload.skills is not None:
        agent.set_skills(payload.skills)
    if payload.tools is not None:
        agent.set_tools(payload.tools)
    if payload.starters is not None:
        agent.set_starters(payload.starters)
    if payload.domain is not None:
        agent.domain = payload.domain.value if hasattr(payload.domain, "value") else str(payload.domain)
    if payload.category is not None:
        agent.category = payload.category
    if payload.risk_class is not None:
        agent.risk_class = payload.risk_class.value if hasattr(payload.risk_class, "value") else str(payload.risk_class)
    if payload.tags is not None:
        agent.set_tags(payload.tags)
    if payload.icon is not None:
        agent.icon = payload.icon
    if payload.can_delegate is not None:
        agent.can_delegate = payload.can_delegate
    if payload.max_iterations is not None:
        agent.max_iterations = payload.max_iterations
    if payload.is_public is not None:
        agent.is_public = payload.is_public

    await db.commit()
    await db.refresh(agent)

    # Update CatalogPort
    try:
        catalog = memory_factory.get_catalog_port()
        manifest = AgentManifest(
            id=agent.id,
            title=agent.title,
            description=agent.description,
            persona=agent.persona,
            model=agent.model,
            skills=agent.get_skills(),
            tools=agent.get_tools(),
            domain=AgentDomain(agent.domain) if agent.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
            category=agent.category,
            risk_class=RiskClass(agent.risk_class) if agent.risk_class in [r.value for r in RiskClass] else RiskClass.CLINICAL_ASSIST,
            tags=agent.get_tags(),
            icon=agent.icon,
            can_delegate=agent.can_delegate,
            max_iterations=agent.max_iterations,
        )
        await catalog.index_agent(manifest)
    except Exception as idx_err:
        logger.warning("failed_to_update_catalog_agent", agent_id=agent.id, error=str(idx_err))

    return await get_agent(agent_id=agent.id, allow_clinical=True, db=db)


@router.delete(ROUTE_AGENT_DETAIL)
async def delete_agent(
    agent_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a user-defined agent and attached direct documents from the database."""
    stmt = select(Agent).where(Agent.id == agent_id)
    res = await db.execute(stmt)
    agent = res.scalar_one_or_none()

    if agent is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    if agent.type in ("bundled", "system"):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Cannot delete bundled or system agent '{agent_id}'.",
        )

    # Delete attached documents from knowledge_base
    await db.execute(
        delete(KnowledgeBase).where(
            KnowledgeBase.target_type == "agent",
            KnowledgeBase.target_id == agent_id,
        )
    )
    # Delete agent
    await db.delete(agent)
    await db.commit()

    # Remove from CatalogPort
    try:
        catalog = memory_factory.get_catalog_port()
        await catalog.remove_agent(agent_id)
    except Exception as err:
        logger.warning("failed_to_remove_agent_from_catalog", agent_id=agent_id, error=str(err))

    return {"deleted": True, "id": agent_id}


# ============================================================================
# Knowledge Base Reference Document Endpoints for Agents
# ============================================================================


@router.get(ROUTE_AGENT_DOCS, response_model=AgentDocsResponse)
async def list_agent_docs(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> AgentDocsResponse:
    """Lists both direct knowledge base documents and attached skill documents for an agent."""
    # 1. Direct agent docs
    stmt_direct = (
        select(KnowledgeBase)
        .where(
            KnowledgeBase.target_type == "agent",
            KnowledgeBase.target_id == agent_id,
        )
        .order_by(KnowledgeBase.name)
    )
    res_direct = await db.execute(stmt_direct)
    direct_records = res_direct.scalars().all()
    direct_docs = [
        DocSummary(
            id=d.id,
            name=d.name,
            title=d.title,
            target_type=d.target_type,
            target_id=d.target_id,
            format=d.format,
            size_bytes=d.size_bytes,
            type=d.type,
            updated_at=d.updated_at.isoformat() if d.updated_at else None,
        )
        for d in direct_records
    ]

    # 2. Skill docs attached to this agent
    skill_docs: List[DocSummary] = []
    # Get agent declared skills
    agent_stmt = select(Agent).where(Agent.id == agent_id)
    agent_res = await db.execute(agent_stmt)
    agent_obj = agent_res.scalar_one_or_none()

    skills_to_query: List[str] = []
    if agent_obj:
        skills_to_query = agent_obj.get_skills()
    else:
        # Fallback check on filesystem
        agents_dir = settings.get_agents_dir()
        agent_dir = find_agent_dir(agents_dir, agent_id)
        if agent_dir:
            try:
                a_manifest, _, _ = load_agent(agent_dir, settings.get_skills_dir())
                skills_to_query = a_manifest.skills
            except Exception:
                pass

    if skills_to_query:
        stmt_skills = (
            select(KnowledgeBase)
            .where(
                KnowledgeBase.target_type == "skill",
                KnowledgeBase.target_id.in_(skills_to_query),
            )
            .order_by(KnowledgeBase.target_id, KnowledgeBase.name)
        )
        res_skills = await db.execute(stmt_skills)
        for d in res_skills.scalars().all():
            skill_docs.append(
                DocSummary(
                    id=d.id,
                    name=d.name,
                    title=d.title,
                    target_type=d.target_type,
                    target_id=d.target_id,
                    format=d.format,
                    size_bytes=d.size_bytes,
                    type=d.type,
                    updated_at=d.updated_at.isoformat() if d.updated_at else None,
                )
            )

    return AgentDocsResponse(
        agent_id=agent_id,
        direct_docs=direct_docs,
        skill_docs=skill_docs,
    )


@router.post(ROUTE_AGENT_DOCS, response_model=DocDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_doc(
    agent_id: str,
    payload: DocCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Adds a new direct reference document to this agent's knowledge base."""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "agent",
        KnowledgeBase.target_id == agent_id,
        KnowledgeBase.name == payload.name,
    )
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{payload.name}' already exists for agent '{agent_id}'.",
        )

    title_val = payload.title or payload.name.rsplit(".", 1)[0].replace("_", " ").title()
    content_bytes = len(payload.content.encode("utf-8"))

    new_doc = KnowledgeBase(
        type="user",
        user_id=resolve_owner_user_id(user),
        target_type="agent",
        target_id=agent_id,
        name=payload.name,
        title=title_val,
        content=payload.content,
        format=payload.format,
        size_bytes=content_bytes,
        metadata_json="{}",
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return DocDetailResponse(
        id=new_doc.id,
        name=new_doc.name,
        title=new_doc.title,
        target_type=new_doc.target_type,
        target_id=new_doc.target_id,
        content=new_doc.content,
        format=new_doc.format,
        size_bytes=new_doc.size_bytes,
        type=new_doc.type,
        created_at=new_doc.created_at.isoformat() if new_doc.created_at else None,
        updated_at=new_doc.updated_at.isoformat() if new_doc.updated_at else None,
    )


@router.get(ROUTE_AGENT_DOC_DETAIL, response_model=DocDetailResponse)
async def get_agent_doc(
    agent_id: str,
    doc_name: str,
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Reads a direct reference document from the agent's knowledge base."""
    if not DOC_FILENAME_REGEX.match(doc_name):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid document filename.",
        )

    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "agent",
        KnowledgeBase.target_id == agent_id,
        KnowledgeBase.name == doc_name,
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if doc is not None:
        return DocDetailResponse(
            id=doc.id,
            name=doc.name,
            title=doc.title,
            target_type=doc.target_type,
            target_id=doc.target_id,
            content=doc.content,
            format=doc.format,
            size_bytes=doc.size_bytes,
            type=doc.type,
            created_at=doc.created_at.isoformat() if doc.created_at else None,
            updated_at=doc.updated_at.isoformat() if doc.updated_at else None,
        )

    # Check filesystem
    agents_dir = settings.get_agents_dir()
    agent_dir = find_agent_dir(agents_dir, agent_id)
    if agent_dir:
        file_path = agent_dir / "references" / doc_name
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8", errors="replace")
            stat = file_path.stat()
            return DocDetailResponse(
                id=f"{agent_id}-{doc_name}",
                name=doc_name,
                title=file_path.stem.replace("_", " ").title(),
                target_type="agent",
                target_id=agent_id,
                content=content,
                format="markdown" if file_path.suffix.lower() == ".md" else "text",
                size_bytes=stat.st_size,
                type="bundled",
            )

    raise HTTPException(
        status_code=HTTP_404_NOT_FOUND,
        detail=f"Document '{doc_name}' not found for agent '{agent_id}'.",
    )


@router.put(ROUTE_AGENT_DOC_DETAIL, response_model=DocDetailResponse)
async def update_agent_doc(
    agent_id: str,
    doc_name: str,
    payload: DocUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Updates a direct reference document in the agent's knowledge base."""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "agent",
        KnowledgeBase.target_id == agent_id,
        KnowledgeBase.name == doc_name,
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_name}' not found for agent '{agent_id}'.",
        )

    if doc.type == "bundled" and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Cannot modify bundled reference document without administrative privileges.",
        )

    if payload.title is not None:
        doc.title = payload.title
    if payload.content is not None:
        doc.content = payload.content
        doc.size_bytes = len(payload.content.encode("utf-8"))
    if payload.format is not None:
        doc.format = payload.format

    await db.commit()
    await db.refresh(doc)

    return DocDetailResponse(
        id=doc.id,
        name=doc.name,
        title=doc.title,
        target_type=doc.target_type,
        target_id=doc.target_id,
        content=doc.content,
        format=doc.format,
        size_bytes=doc.size_bytes,
        type=doc.type,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
        updated_at=doc.updated_at.isoformat() if doc.updated_at else None,
    )


@router.delete(ROUTE_AGENT_DOC_DETAIL)
async def delete_agent_doc(
    agent_id: str,
    doc_name: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a direct reference document from the agent's knowledge base."""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "agent",
        KnowledgeBase.target_id == agent_id,
        KnowledgeBase.name == doc_name,
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_name}' not found for agent '{agent_id}'.",
        )

    if doc.type == "bundled" and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Cannot delete bundled reference document without administrative privileges.",
        )

    await db.delete(doc)
    await db.commit()
    return {"deleted": True, "name": doc_name}
