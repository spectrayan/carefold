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

"""Hexagonal search index port and normalized result models for cognitive search."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field, model_validator


class SearchResult(BaseModel):
    """Normalized search result representing a retrieved document chunk across lexical and semantic stores."""

    document_id: str = Field(..., description="Parent document or note identifier")
    chunk_id: str = Field(..., description="Deterministic chunk identifier: f'{document_id}#c{idx}'")
    content: str = Field(default="", description="Text content of the retrieved chunk")
    score: float = Field(default=0.0, description="Normalized relevance score in [0.0, 1.0]")
    lexical_score: float = Field(default=0.0, description="BM25 lexical relevance score")
    semantic_score: float = Field(default=0.0, description="Dense vector cosine similarity score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document and chunk metadata attributes")
    profile_id: str = Field(default="", description="Care profile identifier owning this chunk")
    source: str = Field(default="search", description="Source modality: search, internal, upload, note, external")

    @model_validator(mode="before")
    @classmethod
    def _normalize_content_and_text(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "content" not in data and "text" in data:
                data["content"] = data["text"]
            elif "text" not in data and "content" in data:
                data["text"] = data["content"]
        return data

    @computed_field
    @property
    def text(self) -> str:
        """Alias property for content, ensuring backward-compatibility with ADR-0007 and legacy callers."""
        return self.content


class SearchIndex(ABC):
    """Hexagonal abstract port for profile-scoped hybrid document and note search."""

    @abstractmethod
    async def index_document(
        self,
        document_id: str,
        text: str,
        metadata: Dict[str, Any],
        profile_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Chunks and indexes document text into lexical and semantic stores.

        Args:
            document_id: Unique identifier for the document or note.
            text: Raw extracted or authored text content.
            metadata: Associated document attributes (filename, sha256, source, etc.).
            profile_id: Mandatory profile partition identifier.
            user_id: Optional user identifier.

        Raises:
            ValueError: If profile_id is empty or whitespace.
        """
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        profile_id: str,
        limit: int = 10,
        mode: Union[Literal["hybrid", "lexical", "semantic"], str] = "hybrid",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Executes profile-scoped search against indexed chunks.

        Args:
            query: Natural language search string or keywords.
            profile_id: Mandatory profile partition identifier.
            limit: Maximum number of search results to return (default: 10).
            mode: Search execution mode ('hybrid', 'lexical', 'semantic').
            filters: Optional dictionary of metadata key-value filters.

        Returns:
            List of SearchResult objects ordered by descending relevance score.

        Raises:
            ValueError: If profile_id is empty or whitespace.
        """
        ...

    @abstractmethod
    async def delete_document(self, document_id: str, profile_id: str) -> bool:
        """Removes all indexed chunks for a document from the index.

        Args:
            document_id: Unique identifier of document to remove.
            profile_id: Mandatory profile partition identifier.

        Returns:
            True if one or more chunks were deleted, False if document was not found.

        Raises:
            ValueError: If profile_id is empty or whitespace.
        """
        ...

    async def delete_profile_index(self, profile_id: str) -> int:
        """Purges all index data for a profile during crypto-shredding / deletion.

        Args:
            profile_id: Mandatory profile partition identifier.

        Returns:
            Number of chunks purged from the index.

        Raises:
            ValueError: If profile_id is empty or whitespace.
        """
        return await self.reindex_all(profile_id)

    async def purge_profile(self, profile_id: str) -> int:
        """Default alias for delete_profile_index(), used by api/profiles.py cascade hook."""
        return await self.delete_profile_index(profile_id)

    @abstractmethod
    async def reindex_all(self, profile_id: str) -> int:
        """Optimizes or rebuilds index data for the specified profile.

        Args:
            profile_id: Mandatory profile partition identifier.

        Returns:
            Count of indexed chunks available in the profile index.

        Raises:
            ValueError: If profile_id is empty or whitespace.
        """
        ...

    async def close(self) -> None:
        """Closes client connections and underlying database resources."""
        pass
