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

"""Skill discovery and inspection endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
    ROUTE_SKILL_DETAIL,
    ROUTE_SKILLS,
)
from carefold.loaders.skill_loader import (
    ManifestValidationError,
    find_skill_dir,
    load_all_skills,
    load_skill,
)
from carefold.schemas.manifest import RiskClass, SkillDetailResponse, SkillSummary

router = APIRouter(tags=["Skills"])


@router.get(ROUTE_SKILLS, response_model=List[SkillSummary])
async def list_skills(
    risk_class: Optional[str] = Query(None, description="Filter by risk class"),
    allow_clinical: bool = Query(False, description="Include clinical assist skills"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category or prefix"),
    page: Optional[int] = Query(None, ge=1, description="Page number (1-based)"),
    per_page: int = Query(20, ge=1, description="Items per page"),
) -> List[SkillSummary]:
    """Lists all installed skills."""
    skills_dir = settings.get_skills_dir()
    skills = load_all_skills(skills_dir)

    summaries = [
        SkillSummary(
            id=s.id,
            name=s.name,
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
        )
        for s in skills
    ]

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


@router.get(ROUTE_SKILL_DETAIL, response_model=SkillDetailResponse)
async def get_skill(skill_id: str) -> SkillDetailResponse:
    """Returns detailed information, instructions, and references for a specific skill."""
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

    return SkillDetailResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        version=skill.version,
        risk_class=skill.risk_class.value,
        domain=skill.domain,
        category=skill.category,
        tags=skill.tags,
        tools=skill.tools,
        forbidden=skill.forbidden,
        instructions=skill.instructions,
        references=skill.references,
        has_evals=has_evals,
        is_verified=skill.is_verified,
    )
