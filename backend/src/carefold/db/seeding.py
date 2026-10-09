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

"""Startup seeding service synchronizing bundled agents and skills from git into generic SQL tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.config import settings
from carefold.db.models import Agent, KnowledgeBase, Skill
from carefold.db.session import get_session_factory
from carefold.loaders.agent_loader import find_agent_dir, load_agent, load_agent_starters, load_all_agents
from carefold.loaders.skill_loader import find_skill_dir, load_all_skills
from carefold.logging import get_logger

logger = get_logger("carefold.db.seeding")

SYSTEM_AGENT_IDS = frozenset({
    "orchestrator",
    "document-extractor",
    "quality-reviewer",
    "skill-generator",
    "suggestion-generator",
    "triage-auditor",
})


async def sync_bundled_assets_to_db(session: Optional[AsyncSession] = None) -> dict[str, int]:
    """Synchronizes bundled agents, skills, and reference documents into SQL tables.

    Runs idempotently on application startup:
    - Bundled/system records are inserted or refreshed from disk.
    - User-defined records (`type='user'`) are never overwritten or deleted.
    """
    if session is None:
        session_factory = get_session_factory()
        async with session_factory() as managed_session:
            result = await _do_sync(managed_session)
            await managed_session.commit()
            return result
    else:
        return await _do_sync(session)


async def _do_sync(session: AsyncSession) -> dict[str, int]:
    skills_dir = settings.get_skills_dir()
    agents_dir = settings.get_agents_dir()

    skills_seeded = 0
    agents_seeded = 0
    docs_seeded = 0

    # 1. Sync bundled skills
    if skills_dir.is_dir():
        try:
            loaded_skills = load_all_skills(skills_dir)
        except Exception as err:
            logger.warning("failed_to_load_bundled_skills_for_seeding", error=str(err))
            loaded_skills = []

        for skill in loaded_skills:
            domain_val = skill.domain.value if hasattr(skill.domain, "value") else str(skill.domain)
            risk_val = skill.risk_class.value if hasattr(skill.risk_class, "value") else str(skill.risk_class)

            stmt = select(Skill).where(Skill.id == skill.id)
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing is None:
                new_skill = Skill(
                    id=skill.id,
                    type="bundled",
                    user_id=None,
                    name=skill.name,
                    title=skill.title or skill.name.replace("-", " ").title(),
                    description=skill.description,
                    domain=domain_val,
                    category=skill.category,
                    risk_class=risk_val,
                    tags_json=json.dumps(skill.tags),
                    tools_json=json.dumps(skill.tools),
                    instructions=skill.instructions,
                    forbidden_json=json.dumps(skill.forbidden),
                    is_verified=skill.is_verified,
                    is_public=True,
                )
                session.add(new_skill)
                skills_seeded += 1
            elif existing.type in ("bundled", "system"):
                existing.name = skill.name
                existing.title = skill.title or skill.name.replace("-", " ").title()
                existing.description = skill.description
                existing.domain = domain_val
                existing.category = skill.category
                existing.risk_class = risk_val
                existing.tags_json = json.dumps(skill.tags)
                existing.tools_json = json.dumps(skill.tools)
                existing.instructions = skill.instructions
                existing.forbidden_json = json.dumps(skill.forbidden)
                existing.is_verified = skill.is_verified
                skills_seeded += 1

            # Sync skill reference documents
            skill_folder = find_skill_dir(skills_dir, skill.id)
            if skill_folder:
                refs_dir = skill_folder / "references"
                if refs_dir.is_dir():
                    for ref_file in refs_dir.iterdir():
                        if ref_file.is_file() and not ref_file.name.startswith(".") and ref_file.suffix.lower() in (".md", ".txt"):
                            try:
                                content = ref_file.read_text(encoding="utf-8")
                                kb_stmt = select(KnowledgeBase).where(
                                    KnowledgeBase.target_type == "skill",
                                    KnowledgeBase.target_id == skill.id,
                                    KnowledgeBase.name == ref_file.name,
                                )
                                kb_res = await session.execute(kb_stmt)
                                existing_doc = kb_res.scalar_one_or_none()

                                if existing_doc is None:
                                    new_doc = KnowledgeBase(
                                        type="bundled",
                                        user_id=None,
                                        target_type="skill",
                                        target_id=skill.id,
                                        name=ref_file.name,
                                        title=ref_file.stem.replace("_", " ").replace("-", " ").title(),
                                        content=content,
                                        format="markdown" if ref_file.suffix.lower() == ".md" else "text",
                                        size_bytes=len(content.encode("utf-8")),
                                        metadata_json="{}",
                                    )
                                    session.add(new_doc)
                                    docs_seeded += 1
                                elif existing_doc.type == "bundled":
                                    existing_doc.content = content
                                    existing_doc.size_bytes = len(content.encode("utf-8"))
                                    existing_doc.format = "markdown" if ref_file.suffix.lower() == ".md" else "text"
                                    docs_seeded += 1
                            except Exception as doc_err:
                                logger.warning("failed_to_seed_skill_doc", skill_id=skill.id, file=ref_file.name, error=str(doc_err))

    # 2. Sync bundled agents
    if agents_dir.is_dir():
        candidates = []
        for entry in sorted(agents_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name == "_system":
                for subentry in sorted(entry.iterdir()):
                    if subentry.is_dir() and not subentry.name.startswith((".", "_")):
                        candidates.append((subentry, True))
            elif not entry.name.startswith("_"):
                candidates.append((entry, False))

        for entry, is_system in candidates:
            try:
                agent, _, _ = load_agent(entry, skills_dir)
            except Exception as err:
                logger.warning("failed_to_load_bundled_agent", agent_dir=entry.name, error=str(err))
                continue

            domain_val = agent.domain.value if hasattr(agent.domain, "value") else str(agent.domain)
            risk_val = agent.risk_class.value if hasattr(agent.risk_class, "value") else str(agent.risk_class)
            maturity_val = agent.maturity.value if hasattr(agent.maturity, "value") else str(agent.maturity)
            is_sys = is_system or agent.id.startswith("_") or agent.id in SYSTEM_AGENT_IDS
            agent_type = "system" if is_sys else "bundled"

            if isinstance(agent.persona, str):
                persona_str = agent.persona
            elif hasattr(agent.persona, "model_dump"):
                persona_str = json.dumps(agent.persona.model_dump())
            else:
                persona_str = str(agent.persona)

            if isinstance(agent.model, str):
                model_str = agent.model
            elif hasattr(agent.model, "name"):
                provider = getattr(agent.model, "provider", None)
                model_str = f"{provider}:{agent.model.name}" if provider else agent.model.name
            else:
                model_str = "ollama:llama3.2"

            starters = load_agent_starters(entry)

            stmt = select(Agent).where(Agent.id == agent.id)
            res = await session.execute(stmt)
            existing_agent = res.scalar_one_or_none()

            care_stages_list = [s.value if hasattr(s, "value") else str(s) for s in getattr(agent, "care_stages", []) or []]
            target_audience_list = [t.value if hasattr(t, "value") else str(t) for t in getattr(agent, "target_audience", []) or []]
            forbidden_list = [f.value if hasattr(f, "value") else str(f) for f in getattr(agent, "forbidden", []) or []]

            if existing_agent is None:
                new_agent = Agent(
                    id=agent.id,
                    type=agent_type,
                    user_id=None,
                    title=agent.title,
                    description=agent.description,
                    persona=persona_str,
                    model=model_str,
                    skills_json=json.dumps(agent.skills),
                    tools_json=json.dumps(agent.tools),
                    starters_json=json.dumps(starters),
                    domain=domain_val,
                    category=agent.category,
                    risk_class=risk_val,
                    tags_json=json.dumps(agent.tags),
                    care_stages_json=json.dumps(care_stages_list),
                    target_audience_json=json.dumps(target_audience_list),
                    forbidden_json=json.dumps(forbidden_list),
                    icon=agent.icon,
                    maturity=maturity_val,
                    can_delegate=agent.can_delegate,
                    max_iterations=agent.max_iterations,
                    hidden=agent.hidden,
                    is_public=True,
                )
                session.add(new_agent)
                agents_seeded += 1
            elif existing_agent.type in ("bundled", "system"):
                existing_agent.title = agent.title
                existing_agent.description = agent.description
                existing_agent.persona = persona_str
                existing_agent.model = model_str
                existing_agent.skills_json = json.dumps(agent.skills)
                existing_agent.tools_json = json.dumps(agent.tools)
                existing_agent.starters_json = json.dumps(starters)
                existing_agent.domain = domain_val
                existing_agent.category = agent.category
                existing_agent.risk_class = risk_val
                existing_agent.tags_json = json.dumps(agent.tags)
                existing_agent.care_stages_json = json.dumps(care_stages_list)
                existing_agent.target_audience_json = json.dumps(target_audience_list)
                existing_agent.forbidden_json = json.dumps(forbidden_list)
                existing_agent.icon = agent.icon
                existing_agent.maturity = maturity_val
                existing_agent.can_delegate = agent.can_delegate
                existing_agent.max_iterations = agent.max_iterations
                existing_agent.hidden = agent.hidden
                agents_seeded += 1

            # Sync agent reference documents if present
            agent_folder = find_agent_dir(agents_dir, agent.id)
            if agent_folder:
                refs_dir = agent_folder / "references"
                if refs_dir.is_dir():
                    for ref_file in refs_dir.iterdir():
                        if ref_file.is_file() and not ref_file.name.startswith(".") and ref_file.suffix.lower() in (".md", ".txt"):
                            try:
                                content = ref_file.read_text(encoding="utf-8")
                                kb_stmt = select(KnowledgeBase).where(
                                    KnowledgeBase.target_type == "agent",
                                    KnowledgeBase.target_id == agent.id,
                                    KnowledgeBase.name == ref_file.name,
                                )
                                kb_res = await session.execute(kb_stmt)
                                existing_doc = kb_res.scalar_one_or_none()

                                if existing_doc is None:
                                    new_doc = KnowledgeBase(
                                        type="bundled",
                                        user_id=None,
                                        target_type="agent",
                                        target_id=agent.id,
                                        name=ref_file.name,
                                        title=ref_file.stem.replace("_", " ").replace("-", " ").title(),
                                        content=content,
                                        format="markdown" if ref_file.suffix.lower() == ".md" else "text",
                                        size_bytes=len(content.encode("utf-8")),
                                        metadata_json="{}",
                                    )
                                    session.add(new_doc)
                                    docs_seeded += 1
                                elif existing_doc.type == "bundled":
                                    existing_doc.content = content
                                    existing_doc.size_bytes = len(content.encode("utf-8"))
                                    existing_doc.format = "markdown" if ref_file.suffix.lower() == ".md" else "text"
                                    docs_seeded += 1
                            except Exception as doc_err:
                                logger.warning("failed_to_seed_agent_doc", agent_id=agent.id, file=ref_file.name, error=str(doc_err))

    logger.info(
        "bundled_assets_seeded_to_database",
        skills_count=skills_seeded,
        agents_count=agents_seeded,
        docs_count=docs_seeded,
    )
    return {
        "skills": skills_seeded,
        "agents": agents_seeded,
        "docs": docs_seeded,
    }
