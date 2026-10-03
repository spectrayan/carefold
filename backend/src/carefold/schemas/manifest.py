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

"""Carefold manifest and catalog schemas."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskClass(str, Enum):
    WELLNESS = "wellness"
    ADMIN = "admin"
    EDUCATION = "education"
    CLINICAL_ASSIST = "clinical_assist"


class AgentDomain(str, Enum):
    WELLNESS = "wellness"
    CLINICAL = "clinical"
    THERAPY = "therapy"
    NAVIGATION = "navigation"
    EDUCATION = "education"
    FINANCE = "finance"
    RETAIL = "retail"
    OPERATIONS = "operations"
    GENERAL = "general"


class AgentMaturity(str, Enum):
    DRAFT = "draft"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


PHASE_0_REGISTRY = frozenset({
    "attach-read",
    "workspace-note",
    "skill-docs",
    "delegate_to_agent",
    "list_agents",
    "sanitize_pii",
    "extract_structured_data",
    "validate_grounding",
})
SLUG_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class AgentModelConfig(BaseModel):
    provider: Optional[str] = None
    name: str
    temperature: Optional[float] = None


class AgentPersonaObject(BaseModel):
    role: Optional[str] = None
    tone: Optional[str] = None
    instructions: Optional[str] = None


class AgentManifest(BaseModel):
    id: str
    title: str
    version: str = "0.1.0"
    license: Optional[str] = None
    risk_class: RiskClass = RiskClass.WELLNESS
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    care_stages: List[str] = Field(default_factory=list)
    target_audience: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    icon: str = "Shield"
    maturity: AgentMaturity = AgentMaturity.STABLE
    model: Optional[Union[str, AgentModelConfig]] = None
    can_delegate: bool = False
    max_iterations: int = 3
    description: str = ""
    hidden: bool = False
    skills: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    persona: Union[str, AgentPersonaObject]
    persona_file: Optional[str] = None
    prompt_template: Optional[str] = None
    suggestions: Optional[Dict[str, Any]] = None

    @field_validator("id")
    @classmethod
    def validate_id_slug(cls, v: str) -> str:
        if not SLUG_REGEX.match(v):
            raise ValueError(f'Agent id "{v}" must be an alphanumeric slug.')
        return v

    @field_validator("skills")
    @classmethod
    def validate_skills_slugs(cls, v: List[str]) -> List[str]:
        for s in v:
            if not SLUG_REGEX.match(s):
                raise ValueError(f'Skill id "{s}" must be an alphanumeric slug.')
        return v


class CarefoldYaml(BaseModel):
    id: Optional[str] = None
    version: Optional[str] = None
    license: Optional[str] = None
    risk_class: Optional[RiskClass] = None
    domain: Optional[AgentDomain] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    forbidden: Optional[List[str]] = None
    evals: Optional[str] = None


class SkillFrontmatterMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    author: Optional[str] = None
    version: Optional[str] = None
    risk_class: Optional[RiskClass] = None
    domain: Optional[AgentDomain] = None
    category: Optional[str] = None
    tools: Optional[List[str]] = None
    forbidden: Optional[List[str]] = None
    evals: Optional[str] = None
    tags: Optional[List[str]] = None


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    description: str
    license: Optional[str] = None
    domain: Optional[AgentDomain] = AgentDomain.WELLNESS
    category: str = ""
    tags: List[str] = Field(default_factory=list)
    allowed_tools: Optional[str] = Field(default=None, alias="allowed-tools")
    compatibility: Optional[str] = None
    metadata: Optional[SkillFrontmatterMetadata] = None

    @field_validator("name")
    @classmethod
    def validate_name_slug(cls, v: str) -> str:
        if not SLUG_REGEX.match(v):
            raise ValueError(f'Skill name "{v}" must be an alphanumeric slug.')
        return v


class SkillManifest(BaseModel):
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    license: Optional[str] = None
    risk_class: RiskClass = RiskClass.WELLNESS
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    tags: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    instructions: str = ""
    references: List[str] = Field(default_factory=list)
    evals: Optional[str] = None
    is_verified: bool = True
    unverified: bool = False


class AgentSummary(BaseModel):
    id: str
    title: str
    version: str = "0.1.0"
    risk_class: str = "wellness"
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    care_stages: List[str] = Field(default_factory=list)
    target_audience: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    icon: str = "Shield"
    maturity: AgentMaturity = AgentMaturity.STABLE
    skills: List[str] = Field(default_factory=list)
    effectiveTools: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
    startersCount: int = 0
    description: str = ""
    can_delegate: bool = False
    max_iterations: int = 3
    is_bundled: bool = False
    isBundled: bool = False
    clinical_enabled: bool = True
    verified: bool = True
    hidden: bool = False
    persona_file: Optional[str] = None
    error: Optional[str] = None


class ResolvedSkillSummary(BaseModel):
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    risk_class: str = "wellness"
    tools: List[str] = Field(default_factory=list)


class ToolDefinitionSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]


class AgentDetailResponse(BaseModel):
    id: str
    title: str
    version: str = "0.1.0"
    license: Optional[str] = None
    risk_class: str = "wellness"
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    care_stages: List[str] = Field(default_factory=list)
    target_audience: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    icon: str = "Shield"
    maturity: AgentMaturity = AgentMaturity.STABLE
    model: Optional[Union[str, Dict[str, Any]]] = None
    can_delegate: bool = False
    max_iterations: int = 3
    description: str = ""
    hidden: bool = False
    persona: Union[str, Dict[str, Any]]
    personaSummary: str
    persona_file: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    resolvedSkills: List[ResolvedSkillSummary] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    effectiveTools: List[str] = Field(default_factory=list)
    toolDefinitions: List[ToolDefinitionSchema] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    is_bundled: bool = False
    isBundled: bool = False
    clinical_requires_flag: bool = False
    readmeText: Optional[str] = None


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    risk_class: str = "wellness"
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    tags: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    is_verified: bool = True
    unverified: bool = False
    error: Optional[str] = None


class SkillDetailResponse(BaseModel):
    id: str
    name: str
    description: str
    version: str = "0.1.0"
    risk_class: str = "wellness"
    domain: AgentDomain = AgentDomain.WELLNESS
    category: str = ""
    tags: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    instructions: str = ""
    references: List[str] = Field(default_factory=list)
    has_evals: bool = False
    is_verified: bool = True
