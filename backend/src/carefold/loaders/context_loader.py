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

"""Context ingestion loader for Carefold workflows.

Ingests user query, checkpoints, attachments (attachments/), user notes (notes/),
and agent catalog summary into unified AgentState prior to orchestrator planning.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from carefold.config import settings


class ContextLoader:
    """Multi-source context loader for Carefold LangGraph workflows."""

    def __init__(
        self,
        workspace_root: Optional[Union[Path, str]] = None,
        registry: Optional[Any] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self.registry = registry

    def load(
        self,
        state: Dict[str, Any],
        workspace_root: Optional[Union[Path, str]] = None,
    ) -> Dict[str, Any]:
        """Instance method to load context into state."""
        ws = workspace_root or self.workspace_root
        return self.load_context(state, ws)

    @classmethod
    def load_context(
        cls,
        state: Dict[str, Any],
        workspace_root: Optional[Union[Path, str]] = None,
    ) -> Dict[str, Any]:
        """Ingests attachments, notes, and catalog summary into AgentState.

        Args:
            state: AgentState dictionary or mutable state mapping.
            workspace_root: Filesystem workspace root path. If omitted, resolved from
                state or application settings.

        Returns:
            Updated state dictionary with populated attachments, notes, and catalog_summary.
        """
        updated = dict(state)

        # Resolve workspace root
        if workspace_root is not None:
            ws_root = Path(workspace_root)
        else:
            state_ws = updated.get("workspace_root")
            if state_ws:
                ws_root = Path(state_ws)
            else:
                ws_root = Path(settings.workspace_root)

        # 1. Ingest attachments from attachments/ directory
        attachments_dir = ws_root / "attachments"
        discovered_attachments: List[str] = []
        if attachments_dir.is_dir():
            for p in sorted(attachments_dir.glob("*")):
                if p.is_file() and not p.name.startswith("."):
                    # Security check: ignore directory traversal attempts
                    if ".." not in p.name:
                        try:
                            discovered_attachments.append(str(p.resolve()))
                        except Exception:
                            discovered_attachments.append(str(p))

        # Merge with existing attachments in state without duplicates
        existing_attachments = list(updated.get("attachments") or [])
        combined_attachments = list(existing_attachments)
        for att in discovered_attachments:
            if att not in combined_attachments:
                combined_attachments.append(att)
        updated["attachments"] = combined_attachments

        # 2. Ingest notes from workspace/notes or notes
        notes_dir = ws_root / "workspace" / "notes"
        if not notes_dir.is_dir():
            notes_dir = ws_root / "notes"

        discovered_notes: List[Dict[str, Any]] = []
        if notes_dir.is_dir():
            for np in sorted(notes_dir.glob("*.md")):
                if np.is_file() and not np.name.startswith("."):
                    try:
                        content = np.read_text(encoding="utf-8")
                    except Exception:
                        content = ""
                    snippet = content[:200].replace("\n", " ").strip()
                    discovered_notes.append({
                        "title": np.stem.replace("_", " ").title(),
                        "path": str(np.resolve()),
                        "snippet": snippet,
                    })

        existing_notes = list(updated.get("notes") or [])
        combined_notes = list(existing_notes)
        existing_note_paths = {n.get("path") for n in existing_notes if isinstance(n, dict)}
        for note in discovered_notes:
            if note.get("path") not in existing_note_paths:
                combined_notes.append(note)
        updated["notes"] = combined_notes

        # 3. Ingest catalog summary from agents directory or AgentRegistry
        agents_dir = ws_root / "agents"
        summary_lines: List[str] = []
        if agents_dir.is_dir():
            for ad in sorted(agents_dir.glob("*")):
                if ad.is_dir() and not ad.name.startswith((".", "_")):
                    desc = "healthcare navigation specialist"
                    manifest_file = ad / "agent.yaml"
                    if manifest_file.is_file():
                        try:
                            import yaml
                            data = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
                            desc = data.get("description") or desc
                        except Exception:
                            pass
                    summary_lines.append(f"- {ad.name}: {desc}")

        updated["catalog_summary"] = "\n".join(summary_lines)

        return updated


__all__ = ["ContextLoader"]
