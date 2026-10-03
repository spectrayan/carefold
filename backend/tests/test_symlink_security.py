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

"""Security Test Suite for Internal Symlink Overwrite & Dangling Symlink Resilience.

Tests:
1. Internal symlinks (absolute, relative, multi-hop) targeting existing notes in workspace/notes/
2. Dangling internal symlinks (single, multi-hop, relative) pointing to nonexistent targets
3. Circular internal symlinks (self-referential, 2-hop loops)
4. Internal directory symlinks pointing within workspace
5. Direct resolve_sandboxed_path behavior across (must_exist, for_write) combinations
6. Fallback notes directory (`<ws_root>/notes`) symlink overwrite & dangling attacks
7. Concurrency stress on symlink protection
8. Integrity of existing notes (verifying content is never altered or truncated)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pytest

from carefold.schemas.manifest import AgentManifest
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path
from carefold.tools.workspace_note import execute_workspace_note


class Context:
    def __init__(self, ws: Path | str, agent_id: str = "security-test-agent"):
        self.workspace_root = ws
        self.agent = AgentManifest(id=agent_id, title="SecurityTest", persona="Role")


@pytest.fixture
def note_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "carefold_ws"
    ws.mkdir(parents=True, exist_ok=True)
    notes = ws / "workspace" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return ws


# =========================================================================
# 1. Internal Symlink Overwrite Attacks (Target Exists)
# =========================================================================

@pytest.mark.asyncio
async def test_internal_symlink_overwrite_absolute_target(note_workspace: Path):
    """Attempting to write to a symlink pointing to an absolute path of an existing internal note."""
    notes_dir = note_workspace / "workspace" / "notes"
    target_note = notes_dir / "confidential_record.md"
    original_text = "---\ntitle: confidential\n---\nOriginal Medical Record"
    target_note.write_text(original_text, encoding="utf-8")

    link_note = notes_dir / "shortcut_abs.md"
    os.symlink(target_note.resolve(), link_note)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "shortcut_abs", "content": "ADVERSARIAL INJECTION ATTEMPT"},
        ctx,
    )

    assert result.success is False
    assert "existing symlink" in result.error or "is a symlink" in result.error
    assert target_note.read_text(encoding="utf-8") == original_text
    assert link_note.is_symlink()


@pytest.mark.asyncio
async def test_internal_symlink_overwrite_relative_target(note_workspace: Path):
    """Attempting to write to a symlink pointing to a relative path of an existing internal note."""
    notes_dir = note_workspace / "workspace" / "notes"
    target_note = notes_dir / "patient_chart.md"
    original_text = "IMMUTABLE PATIENT CHART"
    target_note.write_text(original_text, encoding="utf-8")

    # Relative in same dir
    link_note = notes_dir / "chart_link.md"
    os.symlink("patient_chart.md", link_note)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "chart_link", "content": "TAMPERED PATIENT CHART"},
        ctx,
    )

    assert result.success is False
    assert "existing symlink" in result.error
    assert target_note.read_text(encoding="utf-8") == original_text
    assert link_note.is_symlink()


@pytest.mark.asyncio
async def test_internal_symlink_multihop_chain(note_workspace: Path):
    """Attempting to write to a multi-hop symlink chain (hop1 -> hop2 -> victim)."""
    notes_dir = note_workspace / "workspace" / "notes"
    victim = notes_dir / "victim.md"
    original_text = "GENUINE CLINICAL LOG"
    victim.write_text(original_text, encoding="utf-8")

    hop2 = notes_dir / "hop2.md"
    os.symlink("victim.md", hop2)

    hop1 = notes_dir / "hop1.md"
    os.symlink("hop2.md", hop1)

    ctx = Context(note_workspace)
    # Attack via hop1
    res1 = await execute_workspace_note({"title": "hop1", "content": "PWNED VIA HOP1"}, ctx)
    assert res1.success is False
    assert "existing symlink" in res1.error
    assert victim.read_text(encoding="utf-8") == original_text

    # Attack via hop2
    res2 = await execute_workspace_note({"title": "hop2", "content": "PWNED VIA HOP2"}, ctx)
    assert res2.success is False
    assert "existing symlink" in res2.error
    assert victim.read_text(encoding="utf-8") == original_text


# =========================================================================
# 2. Dangling Internal Symlink Attacks (Target Nonexistent)
# =========================================================================

@pytest.mark.asyncio
async def test_dangling_internal_symlink_direct(note_workspace: Path):
    """Writing through a dangling symlink pointing to a nonexistent file in workspace/notes/."""
    notes_dir = note_workspace / "workspace" / "notes"
    nonexistent = notes_dir / "phantom_note.md"
    dangling = notes_dir / "dangling_proxy.md"
    os.symlink("phantom_note.md", dangling)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "dangling_proxy", "content": "CREATE PHANTOM NOTE"},
        ctx,
    )

    assert result.success is False
    assert "existing symlink" in result.error
    assert not nonexistent.exists(), "Target file must NOT be created through dangling symlink!"
    assert dangling.is_symlink()


@pytest.mark.asyncio
async def test_dangling_multihop_chain(note_workspace: Path):
    """Writing through a dangling multi-hop symlink chain."""
    notes_dir = note_workspace / "workspace" / "notes"
    dangling2 = notes_dir / "dangling_hop2.md"
    os.symlink("nowhere.md", dangling2)

    dangling1 = notes_dir / "dangling_hop1.md"
    os.symlink("dangling_hop2.md", dangling1)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "dangling_hop1", "content": "WRITE VIA DANGLING CHAIN"},
        ctx,
    )

    assert result.success is False
    assert "existing symlink" in result.error
    assert not (notes_dir / "nowhere.md").exists()


# =========================================================================
# 3. Circular Symlinks & Loops
# =========================================================================

@pytest.mark.asyncio
async def test_circular_symlink_self_loop(note_workspace: Path):
    """Writing to a self-referential symlink (loop -> loop) must not crash or loop infinitely."""
    notes_dir = note_workspace / "workspace" / "notes"
    self_loop = notes_dir / "self_loop.md"
    os.symlink("self_loop.md", self_loop)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "self_loop", "content": "INFINITE LOOP TEST"},
        ctx,
    )

    assert result.success is False
    assert "symlink" in result.error.lower()


@pytest.mark.asyncio
async def test_circular_symlink_two_hop_loop(note_workspace: Path):
    """Writing to a mutual reference symlink loop (loop_a <-> loop_b)."""
    notes_dir = note_workspace / "workspace" / "notes"
    loop_a = notes_dir / "loop_a.md"
    loop_b = notes_dir / "loop_b.md"
    os.symlink("loop_b.md", loop_a)
    os.symlink("loop_a.md", loop_b)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "loop_a", "content": "TWO HOP LOOP TEST"},
        ctx,
    )

    assert result.success is False
    assert "symlink" in result.error.lower()


# =========================================================================
# 4. Directory Symlinks & Ancestor Symlinks
# =========================================================================

@pytest.mark.asyncio
async def test_symlink_to_directory(note_workspace: Path):
    """Symlink pointing to an internal directory inside workspace."""
    notes_dir = note_workspace / "workspace" / "notes"
    sub_dir = notes_dir / "nested_folder"
    sub_dir.mkdir()

    dir_symlink = notes_dir / "dir_link.md"
    os.symlink("nested_folder", dir_symlink)

    ctx = Context(note_workspace)
    result = await execute_workspace_note(
        {"title": "dir_link", "content": "DIRECTORY OVERWRITE TEST"},
        ctx,
    )

    assert result.success is False
    assert "existing symlink" in result.error or "is a symlink" in result.error


# =========================================================================
# 5. Direct Sandbox Function Testing (resolve_sandboxed_path)
# =========================================================================

def test_resolve_sandboxed_path_for_write_matrix(tmp_path: Path):
    """Exhaustive check on resolve_sandboxed_path for write scenarios."""
    base = tmp_path / "sandbox_base"
    base.mkdir()

    real_file = base / "real.txt"
    real_file.write_text("REAL")

    internal_link = base / "link_to_real.txt"
    os.symlink("real.txt", internal_link)

    dangling_link = base / "dangling_link.txt"
    os.symlink("missing.txt", dangling_link)

    external_link = base / "ext_link.txt"
    os.symlink("/etc/passwd", external_link)

    # 1. for_write=True on existing internal symlink -> MUST RAISE
    with pytest.raises(SandboxSecurityError) as exc1:
        resolve_sandboxed_path(base, "link_to_real.txt", must_exist=False, for_write=True)
    assert "is an existing symlink" in str(exc1.value)

    # 2. for_write=True on dangling internal symlink -> MUST RAISE
    with pytest.raises(SandboxSecurityError) as exc2:
        resolve_sandboxed_path(base, "dangling_link.txt", must_exist=False, for_write=True)
    assert "is an existing symlink" in str(exc2.value)

    # 3. for_write=True on external symlink -> MUST RAISE
    with pytest.raises(SandboxSecurityError) as exc3:
        resolve_sandboxed_path(base, "ext_link.txt", must_exist=False, for_write=True)
    assert "is a symlink escaping sandbox" in str(exc3.value)

    # 4. Normal new file with for_write=True -> SUCCESS
    p = resolve_sandboxed_path(base, "new_file.txt", must_exist=False, for_write=True)
    assert p == base / "new_file.txt"

    # 5. Existing normal file with for_write=True -> SUCCESS
    p2 = resolve_sandboxed_path(base, "real.txt", must_exist=False, for_write=True)
    assert p2 == real_file.resolve()


# =========================================================================
# 6. Fallback Notes Directory (<workspace_root>/notes) Symlink Protection
# =========================================================================

@pytest.mark.asyncio
async def test_root_notes_fallback_symlink_protection(tmp_path: Path):
    """When workspace/ does not exist, notes are stored in <ws_root>/notes.
    Symlink overwrite and dangling symlinks must be blocked equally there."""
    ws = tmp_path / "simple_ws"
    ws.mkdir()
    notes_dir = ws / "notes"
    notes_dir.mkdir()

    victim = notes_dir / "target.md"
    victim.write_text("FALLBACK ROOT NOTE")
    shortcut = notes_dir / "shortcut.md"
    os.symlink("target.md", shortcut)

    dangling = notes_dir / "dangling.md"
    os.symlink("phantom.md", dangling)

    ctx = Context(str(ws))  # Also testing str workspace_root

    # Overwrite attempt
    res1 = await execute_workspace_note({"title": "shortcut", "content": "TAMPER"}, ctx)
    assert res1.success is False
    assert "existing symlink" in res1.error
    assert victim.read_text() == "FALLBACK ROOT NOTE"

    # Dangling attempt
    res2 = await execute_workspace_note({"title": "dangling", "content": "TAMPER"}, ctx)
    assert res2.success is False
    assert "existing symlink" in res2.error
    assert not (notes_dir / "phantom.md").exists()


# =========================================================================
# 7. Concurrency Stress on Symlink Protection
# =========================================================================

@pytest.mark.asyncio
async def test_concurrency_symlink_defense(note_workspace: Path):
    """Concurrent attempts to overwrite multiple symlinks simultaneously."""
    notes_dir = note_workspace / "workspace" / "notes"

    count = 20
    for i in range(count):
        real_file = notes_dir / f"confidential_{i}.md"
        real_file.write_text(f"CONFIDENTIAL DATA {i}")
        sym = notes_dir / f"sym_{i}.md"
        os.symlink(f"confidential_{i}.md", sym)

    ctx = Context(note_workspace)

    async def attack(idx: int):
        return await execute_workspace_note(
            {"title": f"sym_{idx}", "content": f"MALICIOUS OVERWRITE {idx}"},
            ctx,
        )

    results = await asyncio.gather(*(attack(i) for i in range(count)))

    for i, res in enumerate(results):
        assert res.success is False
        assert "existing symlink" in res.error
        real_file = notes_dir / f"confidential_{i}.md"
        assert real_file.read_text() == f"CONFIDENTIAL DATA {i}"
