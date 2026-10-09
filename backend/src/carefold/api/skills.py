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

"""Skill discovery, inspection, and user-defined CRUD endpoints backed by SQL database."""

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
    ROUTE_SKILL_DETAIL,
    ROUTE_SKILL_DOC_DETAIL,
    ROUTE_SKILL_DOCS,
    ROUTE_SKILLS,
)
from carefold.db.models import KnowledgeBase, Skill
from carefold.db.session import get_db
from carefold.loaders.skill_loader import (
    ManifestValidationError,
    find_skill_dir,
    load_all_skills,
    load_skill,
)
from carefold.logging import get_logger
import carefold.memory.factory as memory_factory
from carefold.schemas.manifest import (
    DOC_FILENAME_REGEX,
    AgentDomain,
    DocCreateRequest,
    DocDetailResponse,
    DocSummary,
    DocUpdateRequest,
    RiskClass,
    SkillCreateRequest,
    SkillDetailResponse,
    SkillManifest,
    SkillSummary,
    SkillUpdateRequest,
)

logger = get_logger("carefold.api.skills")

router = APIRouter(tags=["Skills"])

MANDATORY_SAFETY_STATEMENTS = [
    "Not a clinician and not emergency care",
    "If this is an emergency, contact local emergency services",
    "Do not change medication without the prescribing clinician",
]


def ensure_safety_disclosures(instructions: str) -> str:
    """Appends mandatory non-clinical intended use disclosures if missing."""
    text = instructions or ""
    missing = [line for line in MANDATORY_SAFETY_STATEMENTS if line.lower() not in text.lower()]
    if not missing:
        return text

    notice_block = "\n\n## Mandatory Safety Disclosures\n" + "\n".join(f"- {line}" for line in missing) + "\n"
    return text.rstrip() + notice_block


@router.get(ROUTE_SKILLS, response_model=List[SkillSummary])
async def list_skills(
    risk_class: Optional[str] = Query(None, description="Filter by risk class"),
    allow_clinical: bool = Query(False, description="Include clinical assist skills"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category or prefix"),
    page: Optional[int] = Query(None, ge=1, description="Page number (1-based)"),
    per_page: int = Query(20, ge=1, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> List[SkillSummary]:
    """Lists all skills stored in the database (falling back to disk if database is unseeded)."""
    summaries: List[SkillSummary] = []

    # 1. Try querying database skills
    try:
        stmt = select(Skill).order_by(Skill.name)
        res = await db.execute(stmt)
        db_skills = res.scalars().all()
        if db_skills:
            for s in db_skills:
                is_bundled = s.type in ("bundled", "system")
                summaries.append(
                    SkillSummary(
                        id=s.id,
                        name=s.name,
                        title=s.title,
                        description=s.description,
                        version="0.1.0",
                        risk_class=s.risk_class,
                        domain=AgentDomain(s.domain) if s.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
                        category=s.category,
                        tags=s.get_tags(),
                        tools=s.get_tools(),
                        forbidden=s.get_forbidden(),
                        is_verified=s.is_verified,
                        unverified=not s.is_verified,
                        is_bundled=is_bundled,
                        isBundled=is_bundled,
                        type=s.type,
                    )
                )
    except Exception as err:
        logger.warning("db_skill_query_failed_falling_back_to_disk", error=str(err))

    # 2. Fallback to disk if database had no records
    if not summaries:
        skills_dir = settings.get_skills_dir()
        disk_skills = load_all_skills(skills_dir)
        summaries = [
            SkillSummary(
                id=s.id,
                name=s.name,
                title=s.title,
                description=s.description,
                version=s.version,
                risk_class=s.risk_class.value,
                domain=s.domain,
                category=s.category,
                tags=s.tags,
                tools=s.tools,
                forbidden=s.forbidden,
                is_verified=s.is_verified,
                unverified=s.unverified,
                is_bundled=True,
                isBundled=True,
                type="bundled",
            )
            for s in disk_skills
        ]

    # Filters
    if risk_class:
        summaries = [s for s in summaries if s.risk_class.lower() == risk_class.lower()]

    if domain:
        d = domain.lower().strip()
        summaries = [
            s for s in summaries
            if (s.domain.value if hasattr(s.domain, "value") else str(s.domain or "")).lower() == d
        ]

    if category:
        c = category.lower().strip()
        summaries = [
            s for s in summaries
            if (s.category or "").lower() == c or (s.category or "").lower().startswith(f"{c}.")
        ]

    if page is not None:
        start = (page - 1) * per_page
        end = start + per_page
        summaries = summaries[start:end]

    return summaries


@router.post(ROUTE_SKILLS, response_model=SkillDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillDetailResponse:
    """Creates a new user-defined skill in the database with mandatory clinical safety boundaries."""
    # Check for duplicate
    stmt = select(Skill).where(Skill.id == payload.id)
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill with ID '{payload.id}' already exists.",
        )

    # Enforce clinical safety boundary disclosure
    instructions = ensure_safety_disclosures(payload.instructions)

    domain_val = payload.domain.value if hasattr(payload.domain, "value") else str(payload.domain)
    risk_val = payload.risk_class.value if hasattr(payload.risk_class, "value") else str(payload.risk_class)

    new_skill = Skill(
        id=payload.id,
        type="user",
        user_id=resolve_owner_user_id(user),
        name=payload.name,
        title=payload.title or payload.name.replace("-", " ").title(),
        description=payload.description,
        domain=domain_val,
        category=payload.category,
        risk_class=risk_val,
        tags_json=json.dumps(payload.tags),
        tools_json=json.dumps(payload.tools),
        instructions=instructions,
        forbidden_json=json.dumps(payload.forbidden),
        is_verified=True,
        is_public=payload.is_public,
    )
    db.add(new_skill)
    await db.commit()
    await db.refresh(new_skill)

    # Index in CatalogPort for search
    try:
        catalog = memory_factory.get_catalog_port()
        manifest = SkillManifest(
            id=new_skill.id,
            name=new_skill.name,
            title=new_skill.title,
            description=new_skill.description,
            domain=payload.domain,
            category=new_skill.category,
            risk_class=payload.risk_class,
            tags=new_skill.get_tags(),
            tools=new_skill.get_tools(),
            instructions=new_skill.instructions,
            forbidden=new_skill.get_forbidden(),
            is_verified=new_skill.is_verified,
        )
        await catalog.index_skill(manifest)
    except Exception as idx_err:
        logger.warning("failed_to_index_created_skill", skill_id=new_skill.id, error=str(idx_err))

    return SkillDetailResponse(
        id=new_skill.id,
        name=new_skill.name,
        title=new_skill.title,
        description=new_skill.description,
        version="0.1.0",
        risk_class=new_skill.risk_class,
        domain=payload.domain,
        category=new_skill.category,
        tags=new_skill.get_tags(),
        tools=new_skill.get_tools(),
        forbidden=new_skill.get_forbidden(),
        instructions=new_skill.instructions,
        references=[],
        has_evals=False,
        is_verified=new_skill.is_verified,
        is_bundled=False,
        isBundled=False,
        type="user",
    )


@router.get(ROUTE_SKILL_DETAIL, response_model=SkillDetailResponse)
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
) -> SkillDetailResponse:
    """Returns detailed information, instructions, and references for a specific skill."""
    # 1. Query DB
    db_skill = None
    ref_names: List[str] = []
    try:
        stmt = select(Skill).where(Skill.id == skill_id)
        res = await db.execute(stmt)
        db_skill = res.scalar_one_or_none()

        if db_skill is not None:
            # Load references from knowledge_base table
            kb_stmt = select(KnowledgeBase.name).where(
                KnowledgeBase.target_type == "skill",
                KnowledgeBase.target_id == skill_id,
            )
            kb_res = await db.execute(kb_stmt)
            ref_names = [name for (name,) in kb_res.all()]
    except Exception as db_err:
        logger.warning("db_get_skill_query_failed", skill_id=skill_id, error=str(db_err))

    if db_skill is not None:

        is_bundled = db_skill.type in ("bundled", "system")
        return SkillDetailResponse(
            id=db_skill.id,
            name=db_skill.name,
            title=db_skill.title,
            description=db_skill.description,
            version="0.1.0",
            risk_class=db_skill.risk_class,
            domain=AgentDomain(db_skill.domain) if db_skill.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
            category=db_skill.category,
            tags=db_skill.get_tags(),
            tools=db_skill.get_tools(),
            forbidden=db_skill.get_forbidden(),
            instructions=db_skill.instructions,
            references=ref_names,
            has_evals=False,
            is_verified=db_skill.is_verified,
            is_bundled=is_bundled,
            isBundled=is_bundled,
            type=db_skill.type,
        )

    # 2. Fallback to disk
    skills_dir = settings.get_skills_dir()
    skill_dir = find_skill_dir(skills_dir, skill_id)

    if not skill_dir or not skill_dir.is_dir():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")

    try:
        skill = load_skill(skill_dir)
    except ManifestValidationError as err:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to load skill: {err}")

    has_evals = bool(skill.evals and (skill_dir / skill.evals).is_file())
    ref_names = []
    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        ref_names = [f.name for f in refs_dir.iterdir() if f.is_file() and not f.name.startswith(".")]

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        title=skill.title,
        description=skill.description,
        version=skill.version,
        risk_class=skill.risk_class.value,
        domain=skill.domain,
        category=skill.category,
        tags=skill.tags,
        tools=skill.tools,
        forbidden=skill.forbidden,
        instructions=skill.instructions,
        references=ref_names,
        has_evals=has_evals,
        is_verified=skill.is_verified,
        is_bundled=True,
        isBundled=True,
        type="bundled",
    )


@router.put(ROUTE_SKILL_DETAIL, response_model=SkillDetailResponse)
async def update_skill(
    skill_id: str,
    payload: SkillUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillDetailResponse:
    """Updates metadata and instructions for a user-defined skill."""
    stmt = select(Skill).where(Skill.id == skill_id)
    res = await db.execute(stmt)
    skill = res.scalar_one_or_none()

    if skill is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")

    if skill.type in ("bundled", "system") and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Cannot modify system/bundled skill '{skill_id}'. Only custom skills can be updated.",
        )

    if payload.title is not None:
        skill.title = payload.title
    if payload.description is not None:
        skill.description = payload.description
    if payload.domain is not None:
        skill.domain = payload.domain.value if hasattr(payload.domain, "value") else str(payload.domain)
    if payload.category is not None:
        skill.category = payload.category
    if payload.risk_class is not None:
        skill.risk_class = payload.risk_class.value if hasattr(payload.risk_class, "value") else str(payload.risk_class)
    if payload.tags is not None:
        skill.set_tags(payload.tags)
    if payload.tools is not None:
        skill.set_tools(payload.tools)
    if payload.forbidden is not None:
        skill.set_forbidden(payload.forbidden)
    if payload.is_public is not None:
        skill.is_public = payload.is_public
    if payload.instructions is not None:
        skill.instructions = ensure_safety_disclosures(payload.instructions)

    await db.commit()
    await db.refresh(skill)

    # Update CatalogPort
    try:
        catalog = memory_factory.get_catalog_port()
        manifest = SkillManifest(
            id=skill.id,
            name=skill.name,
            title=skill.title,
            description=skill.description,
            domain=AgentDomain(skill.domain) if skill.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
            category=skill.category,
            risk_class=RiskClass(skill.risk_class) if skill.risk_class in [r.value for r in RiskClass] else RiskClass.CLINICAL_ASSIST,
            tags=skill.get_tags(),
            tools=skill.get_tools(),
            instructions=skill.instructions,
            forbidden=skill.get_forbidden(),
            is_verified=skill.is_verified,
        )
        await catalog.index_skill(manifest)
    except Exception as idx_err:
        logger.warning("failed_to_update_catalog_skill", skill_id=skill.id, error=str(idx_err))

    # Fetch references
    kb_stmt = select(KnowledgeBase.name).where(
        KnowledgeBase.target_type == "skill",
        KnowledgeBase.target_id == skill_id,
    )
    kb_res = await db.execute(kb_stmt)
    ref_names = [name for (name,) in kb_res.all()]

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        title=skill.title,
        description=skill.description,
        version="0.1.0",
        risk_class=skill.risk_class,
        domain=AgentDomain(skill.domain) if skill.domain in [d.value for d in AgentDomain] else AgentDomain.WELLNESS,
        category=skill.category,
        tags=skill.get_tags(),
        tools=skill.get_tools(),
        forbidden=skill.get_forbidden(),
        instructions=skill.instructions,
        references=ref_names,
        has_evals=False,
        is_verified=skill.is_verified,
        is_bundled=(skill.type in ("bundled", "system")),
        isBundled=(skill.type in ("bundled", "system")),
        type=skill.type,
    )


@router.delete(ROUTE_SKILL_DETAIL)
async def delete_skill(
    skill_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a user-defined skill and associated knowledge base documents from the database."""
    stmt = select(Skill).where(Skill.id == skill_id)
    res = await db.execute(stmt)
    skill = res.scalar_one_or_none()

    if skill is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")

    if skill.type in ("bundled", "system"):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Cannot delete bundled or system skill '{skill_id}'.",
        )

    # Delete attached documents from knowledge_base
    await db.execute(
        delete(KnowledgeBase).where(
            KnowledgeBase.target_type == "skill",
            KnowledgeBase.target_id == skill_id,
        )
    )
    # Delete skill
    await db.delete(skill)
    await db.commit()

    # Remove from CatalogPort
    try:
        catalog = memory_factory.get_catalog_port()
        await catalog.remove_skill(skill_id)
    except Exception as err:
        logger.warning("failed_to_remove_skill_from_catalog", skill_id=skill_id, error=str(err))

    return {"deleted": True, "id": skill_id}


# ============================================================================
# Knowledge Base Reference Document Endpoints for Skills
# ============================================================================


@router.get(ROUTE_SKILL_DOCS, response_model=List[DocSummary])
async def list_skill_docs(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
) -> List[DocSummary]:
    """Lists all reference documents in the knowledge base attached to this skill."""
    stmt = (
        select(KnowledgeBase)
        .where(
            KnowledgeBase.target_type == "skill",
            KnowledgeBase.target_id == skill_id,
        )
        .order_by(KnowledgeBase.name)
    )
    res = await db.execute(stmt)
    docs = res.scalars().all()

    # If DB returned documents, return them
    if docs:
        return [
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
            for d in docs
        ]

    # Fallback to filesystem
    skills_dir = settings.get_skills_dir()
    skill_dir = find_skill_dir(skills_dir, skill_id)
    if skill_dir:
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            summaries = []
            for f in sorted(refs_dir.iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in (".md", ".txt"):
                    stat = f.stat()
                    summaries.append(
                        DocSummary(
                            id=f"{skill_id}-{f.name}",
                            name=f.name,
                            title=f.stem.replace("_", " ").title(),
                            target_type="skill",
                            target_id=skill_id,
                            format="markdown" if f.suffix.lower() == ".md" else "text",
                            size_bytes=stat.st_size,
                            type="bundled",
                        )
                    )
            return summaries

    return []


@router.post(ROUTE_SKILL_DOCS, response_model=DocDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_skill_doc(
    skill_id: str,
    payload: DocCreateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Adds a new reference document to this skill's knowledge base."""
    # Check if doc exists
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "skill",
        KnowledgeBase.target_id == skill_id,
        KnowledgeBase.name == payload.name,
    )
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{payload.name}' already exists for skill '{skill_id}'.",
        )

    title_val = payload.title or payload.name.rsplit(".", 1)[0].replace("_", " ").title()
    content_bytes = len(payload.content.encode("utf-8"))

    new_doc = KnowledgeBase(
        type="user",
        user_id=resolve_owner_user_id(user),
        target_type="skill",
        target_id=skill_id,
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


@router.get(ROUTE_SKILL_DOC_DETAIL, response_model=DocDetailResponse)
async def get_skill_doc(
    skill_id: str,
    doc_name: str,
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Reads a reference document from the skill's knowledge base."""
    if not DOC_FILENAME_REGEX.match(doc_name):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid document filename.",
        )

    # 1. Query database
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "skill",
        KnowledgeBase.target_id == skill_id,
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

    # 2. Fallback to filesystem
    skills_dir = settings.get_skills_dir()
    skill_dir = find_skill_dir(skills_dir, skill_id)
    if skill_dir:
        file_path = skill_dir / "references" / doc_name
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8", errors="replace")
            stat = file_path.stat()
            return DocDetailResponse(
                id=f"{skill_id}-{doc_name}",
                name=doc_name,
                title=file_path.stem.replace("_", " ").title(),
                target_type="skill",
                target_id=skill_id,
                content=content,
                format="markdown" if file_path.suffix.lower() == ".md" else "text",
                size_bytes=stat.st_size,
                type="bundled",
            )

    raise HTTPException(
        status_code=HTTP_404_NOT_FOUND,
        detail=f"Document '{doc_name}' not found for skill '{skill_id}'.",
    )


@router.put(ROUTE_SKILL_DOC_DETAIL, response_model=DocDetailResponse)
async def update_skill_doc(
    skill_id: str,
    doc_name: str,
    payload: DocUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocDetailResponse:
    """Updates a reference document in the knowledge base."""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "skill",
        KnowledgeBase.target_id == skill_id,
        KnowledgeBase.name == doc_name,
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_name}' not found for skill '{skill_id}'.",
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


@router.delete(ROUTE_SKILL_DOC_DETAIL)
async def delete_skill_doc(
    skill_id: str,
    doc_name: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a reference document from the knowledge base."""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.target_type == "skill",
        KnowledgeBase.target_id == skill_id,
        KnowledgeBase.name == doc_name,
    )
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_name}' not found for skill '{skill_id}'.",
        )

    if doc.type == "bundled" and getattr(user, "role", "member") != "admin":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Cannot delete bundled reference document without administrative privileges.",
        )

    await db.delete(doc)
    await db.commit()
    return {"deleted": True, "name": doc_name}
