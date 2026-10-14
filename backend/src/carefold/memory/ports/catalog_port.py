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

"""CatalogPort interface for hexagonal agent and skill discovery and indexing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from carefold.schemas.manifest import AgentManifest, SkillManifest


class CatalogPort(ABC):
    """Abstract port interface for agent and skill discovery, indexing, and taxonomy queries."""

    @abstractmethod
    async def index_agent(self, manifest: AgentManifest) -> None:
        """Indexes or updates an agent manifest in the catalog.
        
        Args:
            manifest: Full AgentManifest containing identity, taxonomy, persona, and tools.
        """
        ...

    @abstractmethod
    async def index_skill(self, manifest: SkillManifest) -> None:
        """Indexes or updates a skill manifest in the catalog.
        
        Args:
            manifest: Full SkillManifest containing identity, taxonomy, and tool bindings.
        """
        ...

    @abstractmethod
    async def remove_agent(self, agent_id: str) -> None:
        """Removes an agent from the catalog index.
        
        Args:
            agent_id: Identifier of the agent to remove.
        """
        ...

    @abstractmethod
    async def remove_skill(self, skill_id: str) -> None:
        """Removes a skill from the catalog index.
        
        Args:
            skill_id: Identifier of the skill to remove.
        """
        ...

    @abstractmethod
    async def search_agents(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[AgentManifest]:
        """Searches and filters indexed agents.
        
        Args:
            query: Optional full-text search string matched against title, description,
                   tags, and persona.
            domain: Optional exact filter on AgentDomain ('clinical', 'therapy', 'wellness',
                    'navigation', 'education').
            category: Optional dot-notated category filter or prefix (e.g. 'navigation.insurance').
            limit: Maximum number of agent manifests to return (defaults to 10).
            
        Returns:
            List of matching AgentManifest instances.
        """
        ...

    @abstractmethod
    async def search_skills(
        self,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[SkillManifest]:
        """Searches and filters indexed skills.
        
        Args:
            query: Optional full-text search string matched against name, description,
                   tags, and instructions.
            domain: Optional exact filter on AgentDomain.
            category: Optional dot-notated category filter.
            limit: Maximum number of skill manifests to return (defaults to 10).
            
        Returns:
            List of matching SkillManifest instances.
        """
        ...

    @abstractmethod
    async def get_category_tree(self) -> Dict[str, Any]:
        """Builds a hierarchical category tree with agent counts across domains and categories.
        
        Returns:
            Dictionary containing:
            - 'total': total number of indexed agents
            - 'domains': mapping of domain names to category hierarchy nodes with counts:
              {
                  "total": 3,
                  "domains": {
                      "clinical": {"count": 0, "categories": {}},
                      "therapy": {"count": 0, "categories": {}},
                      "wellness": {"count": 1, "categories": {"habits": {"count": 1, "subcategories": {}}}},
                      "navigation": {"count": 2, "categories": {"insurance": {"count": 1, "subcategories": {}}}},
                      "education": {"count": 0, "categories": {}}
                  }
              }
        """
        ...

    async def close(self) -> None:
        """Closes any underlying resources (database connections, network sessions).
        
        Default implementation is a no-op; adapters override if cleanup is needed.
        """
        pass


__all__ = [
    "CatalogPort",
]
