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

"""Deep Adversarial Test Suite for Tool Sandbox and Runtime Security.

Verifies:
1. attach-read: Path traversal permutations, encoding attacks, scheme injections,
   extension controls, size bounds, corrupt PDF robustness, and multi-hop symlink escapes.
2. workspace-note: Malicious title fuzzing, directory traversal sanitization, external/internal
   symlink overwrites, dangling symlinks, circular loops, and ancestor symlink escapes.
3. skill-docs: Fail-closed unauthenticated gating, undeclared skill access, slug validation,
   doc traversal escapes, and symlink targets outside references/.
4. Tool dispatcher & runner runtime: Undeclared tool execution prevention, unknown tool
   dispatch denial, and audit recording.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import pytest

from carefold.engine.runner import ExecutionContext, execute_agent_run
from carefold.loaders.agent_loader import load_agent
from carefold.model.types import (
    ModelMessage,
    ModelStreamChunk,
    ModelToolCallChunk,
    ModelToolFunction,
    StreamChoice,
    StreamDelta,
)
from carefold.schemas.manifest import AgentManifest, RiskClass, SkillManifest
from carefold.schemas.tool import ToolResult
from carefold.tools.attach_read import execute_attach_read, extract_text_from_pdf_bytes
from carefold.tools.registry import execute_tool
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path
from carefold.tools.skill_docs import execute_skill_docs
from carefold.tools.workspace_note import execute_workspace_note


_SENTINEL = object()

class MockContext:
    def __init__(self, ws_root: Path, agent: Any = _SENTINEL, skills_dir: Path | None = None):
        self.workspace_root = ws_root
        self.skills_dir = skills_dir or (ws_root / "skills")
        if agent is _SENTINEL:
            self.agent = AgentManifest(
                id="test-specialist",
                title="Test Specialist",
                skills=["test-skill"],
                persona="Test Persona",
            )
        else:
            self.agent = agent


@pytest.fixture
def sandbox_env(tmp_path: Path):
    """Sets up a comprehensive workspace with attachments, notes, and skills."""
    ws = tmp_path / "carefold_ws"
    ws.mkdir(parents=True, exist_ok=True)

    att_dir = ws / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)

    notes_dir = ws / "workspace" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    skills_dir = ws / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    test_skill = skills_dir / "test-skill"
    ref_dir = test_skill / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "guide.md").write_text("# Official Guide\nApproved content.", encoding="utf-8")
    (test_skill / "SKILL.md").write_text("# Manifest Header", encoding="utf-8")

    outside_file = tmp_path / "sensitive_system.txt"
    outside_file.write_text("SUPER_CONFIDENTIAL_SYSTEM_DATA", encoding="utf-8")

    valid_txt = att_dir / "valid_sample.txt"
    valid_txt.write_text("Hello attachment", encoding="utf-8")

    return {
        "root": ws,
        "attachments": att_dir,
        "notes": notes_dir,
        "skills": skills_dir,
        "outside": outside_file,
    }


# =========================================================================
# 1. ATTACH-READ ADVERSARIAL STRESS
# =========================================================================

@pytest.mark.asyncio
async def test_attach_read_path_traversal_permutations(sandbox_env):
    """Exhaustively challenges attach-read against 40+ traversal and escape vectors."""
    ws = sandbox_env["root"]
    ctx = MockContext(ws)

    traversal_vectors = [
        "../" * i + "etc/passwd" for i in range(1, 10)
    ] + [
        "attachments/../../../../../../etc/passwd",
        "valid_sample.txt/../../../../etc/passwd",
        "./../../../../etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%252f..%252fetc%252fpasswd",
        "%2e%2e/%2e%2e/etc/passwd",
        "..%5c..%5cetc%5cpasswd",
        "....//....//....//etc/passwd",
        "....////....////etc/passwd",
        "..././..././etc/passwd",
        "..;/..;/etc/passwd",
        "valid_sample.txt\0.pdf",
        "valid_sample.txt\x00/../../etc/passwd",
        "\0/etc/passwd",
        "/etc/passwd",
        "/private/etc/passwd",
        "/",
        "file:///etc/passwd",
        "FILE:///etc/passwd",
        "file://localhost/etc/passwd",
        "http://127.0.0.1:11434/api/tags",
        "https://evil.com/payload.txt",
        "ftp://evil.com/test.txt",
        "gopher://evil.com",
        "data:text/plain;base64,SGVsbG8=",
        "javascript:alert(1)",
        "blob:http://example.com/uuid",
        "about:blank",
        "~/.ssh/id_rsa",
        "$HOME/.bashrc",
        "%USERPROFILE%\\secret.txt",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "\\\\localhost\\c$\\etc\\passwd",
        "\\..\\..\\etc\\passwd",
        "attachments/../attachments/../../etc/passwd",
        "valid_sample.txt/../../outside.txt",
        "valid_sample.txt/..",
    ]

    for vec in traversal_vectors:
        res = await execute_attach_read({"path": vec}, ctx)
        assert res.success is False, f"Vulnerability detected! Traversal vector succeeded: {vec}"
        assert res.output is None
        assert res.error is not None


@pytest.mark.asyncio
async def test_attach_read_extension_and_size_bounds(sandbox_env):
    """Verifies strict format allowlist, case sensitivity, and 10MB bounds."""
    ws = sandbox_env["root"]
    att_dir = sandbox_env["attachments"]
    ctx = MockContext(ws)

    # 1. Disallowed extensions
    bad_exts = [
        "payload.py", "script.sh", "binary.exe", "lib.dll", "config.env",
        "key.pem", "id.key", "app.js", "main.ts", "archive.zip", "data.tar",
        "image.png", "doc.docx", "page.html"
    ]
    for filename in bad_exts:
        f = att_dir / filename
        f.write_text("dummy", encoding="utf-8")
        res = await execute_attach_read({"path": filename}, ctx)
        assert res.success is False, f"Disallowed file format succeeded: {filename}"
        assert "only PDF and plain text" in res.error or "Unsupported" in res.error

    # 2. Allowed extensions & case variations
    allowed_cases = [
        ("report.TXT", "Text report", "text"),
        ("notes.MD", "# Markdown notes", "text"),
        ("data.JSON", '{"key": "value"}', "text"),
        ("table.CSV", "a,b,c\n1,2,3", "csv"),
        ("table.TSV", "a\tb\tc\n1\t2\t3", "tsv"),
        ("config.YAML", "key: value", "text"),
        ("config.YML", "key: value", "text"),
    ]
    for filename, content, expected_format in allowed_cases:
        f = att_dir / filename
        f.write_text(content, encoding="utf-8")
        res = await execute_attach_read({"path": filename}, ctx)
        assert res.success is True, f"Legitimate file failed: {filename}, error: {res.error}"
        assert res.output["format"] == expected_format, f"Unexpected format for {filename}"

    # 3. Size boundary: 10MB + 1 byte
    oversized = att_dir / "oversized.txt"
    with open(oversized, "wb") as f_out:
        f_out.write(b"X" * (10 * 1024 * 1024 + 1))
    res_over = await execute_attach_read({"path": "oversized.txt"}, ctx)
    assert res_over.success is False
    assert "exceeds maximum allowed limit" in res_over.error


@pytest.mark.asyncio
async def test_attach_read_pdf_robustness(sandbox_env):
    """Verifies that pure-Python PDF extractor safely handles malformed/corrupt PDF files."""
    att_dir = sandbox_env["attachments"]
    ctx = MockContext(sandbox_env["root"])

    # 1. Corrupt PDF header
    corrupt1 = att_dir / "corrupt1.pdf"
    corrupt1.write_bytes(b"NOT A REAL PDF AT ALL")
    res1 = await execute_attach_read({"path": "corrupt1.pdf"}, ctx)
    assert res1.success is True
    assert "[Notice: PDF document contains no extractable text layer" in res1.output["content"]

    # 2. Binary random garbage in PDF
    corrupt2 = att_dir / "corrupt2.pdf"
    corrupt2.write_bytes(b"%PDF-1.4\n\x00\xff\xfe\xca\xfe\xba\xbe\x12\x34\n%%EOF")
    res2 = await execute_attach_read({"path": "corrupt2.pdf"}, ctx)
    assert res2.success is True
    assert "[Notice: PDF document contains no extractable text layer" in res2.output["content"]

    # 3. Valid synthetic PDF with text stream
    valid_pdf = att_dir / "valid_stream.pdf"
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Length 50 >> stream\n"
        b"BT\n"
        b"/F1 12 Tf\n"
        b"(Patient Blood Pressure: 120/80) Tj\n"
        b"ET\n"
        b"endstream\n"
        b"endobj\n"
        b"%%EOF"
    )
    valid_pdf.write_bytes(pdf_content)
    res3 = await execute_attach_read({"path": "valid_stream.pdf"}, ctx)
    assert res3.success is True
    assert "Patient Blood Pressure: 120/80" in res3.output["content"]


@pytest.mark.asyncio
async def test_attach_read_symlink_defense(sandbox_env):
    """Verifies attach-read rejects all forms of symlink escapes."""
    att_dir = sandbox_env["attachments"]
    outside_file = sandbox_env["outside"]
    ctx = MockContext(sandbox_env["root"])

    # 1. Direct symlink to external file
    sym1 = att_dir / "sym_outside.txt"
    try:
        os.symlink(outside_file, sym1)
        res = await execute_attach_read({"path": "sym_outside.txt"}, ctx)
        assert res.success is False
        assert "escapes" in res.error.lower()
    except OSError:
        pass

    # 2. Multi-hop symlink chain (sym_hop1 -> sym_hop2 -> outside)
    hop2 = att_dir / "hop2.txt"
    hop1 = att_dir / "hop1.txt"
    try:
        os.symlink(outside_file, hop2)
        os.symlink(hop2, hop1)
        res = await execute_attach_read({"path": "hop1.txt"}, ctx)
        assert res.success is False
        assert "escapes" in res.error.lower()
    except OSError:
        pass

    # 3. Directory symlink pointing to external directory
    ext_dir = sandbox_env["root"].parent / "ext_dir"
    ext_dir.mkdir(exist_ok=True)
    (ext_dir / "secret.txt").write_text("EXTERNAL", encoding="utf-8")
    dir_sym = att_dir / "dir_link"
    try:
        os.symlink(ext_dir, dir_sym)
        res = await execute_attach_read({"path": "dir_link/secret.txt"}, ctx)
        assert res.success is False
        assert "escapes" in res.error.lower()
    except OSError:
        pass


# =========================================================================
# 2. WORKSPACE-NOTE ADVERSARIAL STRESS
# =========================================================================

@pytest.mark.asyncio
async def test_workspace_note_malicious_title_fuzzing(sandbox_env):
    """Fuzzes workspace-note title with traversal, injections, and edge cases."""
    ws = sandbox_env["root"]
    notes_dir = sandbox_env["notes"]
    ctx = MockContext(ws)

    malicious_titles = [
        "../../../../etc/passwd",
        "../../notes_escape",
        "/etc/shadow",
        "C:\\Windows\\System32\\cmd.exe",
        "..\\..\\..\\etc\\passwd",
        "title; rm -rf /",
        "title | whoami",
        "title & dir",
        "title $(whoami)",
        "title `whoami`",
        "<script>alert(1)</script>",
        "<svg onload=alert(1)>",
        "title\0null",
        "title\nwith\nnewlines",
        "title\r\nwith\r\ncrlf",
        "A" * 10000,
        "   ",
        "...",
        "///",
        "\\\\\\",
        "???",
        "---",
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "LPT1",
        "🏥 Medical Record 🩺",
        "Patient #12345 (Follow-up) [Urgent]!",
    ]

    for title in malicious_titles:
        res = await execute_workspace_note({"title": title, "content": "Note content"}, ctx)
        if res.success:
            # Verify the written file is strictly contained within notes_dir
            written_filename = f"{res.output['title']}.md"
            written_path = notes_dir / written_filename
            assert written_path.exists()
            assert written_path.resolve().is_relative_to(notes_dir.resolve())
            assert ".." not in written_filename
            assert "/" not in written_filename
            assert "\\" not in written_filename
        else:
            assert res.error is not None


@pytest.mark.asyncio
async def test_workspace_note_symlink_overwrites_and_ancestors(sandbox_env):
    """Verifies that symlink overwrites, dangling links, and ancestor links are blocked."""
    notes_dir = sandbox_env["notes"]
    outside_file = sandbox_env["outside"]
    ctx = MockContext(sandbox_env["root"])

    # 1. External symlink overwrite
    ext_sym = notes_dir / "ext_note.md"
    try:
        os.symlink(outside_file, ext_sym)
        res = await execute_workspace_note({"title": "ext_note", "content": "OVERWRITE"}, ctx)
        assert res.success is False
        assert "symlink" in res.error.lower()
        assert outside_file.read_text(encoding="utf-8") == "SUPER_CONFIDENTIAL_SYSTEM_DATA"
    except OSError:
        pass

    # 2. Internal victim note symlink overwrite
    victim_note = notes_dir / "victim.md"
    victim_note.write_text("ORIGINAL CONTENT", encoding="utf-8")
    internal_sym = notes_dir / "internal_link.md"
    try:
        os.symlink("victim.md", internal_sym)
        res = await execute_workspace_note({"title": "internal_link", "content": "OVERWRITE"}, ctx)
        assert res.success is False
        assert "existing symlink" in res.error
        assert victim_note.read_text(encoding="utf-8") == "ORIGINAL CONTENT"
    except OSError:
        pass

    # 3. Dangling symlink write
    dangling_sym = notes_dir / "dangling.md"
    phantom = notes_dir / "phantom.md"
    try:
        os.symlink("phantom.md", dangling_sym)
        res = await execute_workspace_note({"title": "dangling", "content": "OVERWRITE"}, ctx)
        assert res.success is False
        assert "existing symlink" in res.error
        assert not phantom.exists()
    except OSError:
        pass

    # 4. Circular symlinks
    circle1 = notes_dir / "circle1.md"
    circle2 = notes_dir / "circle2.md"
    try:
        os.symlink("circle2.md", circle1)
        os.symlink("circle1.md", circle2)
        res = await execute_workspace_note({"title": "circle1", "content": "OVERWRITE"}, ctx)
        assert res.success is False
        assert "symlink" in res.error.lower()
    except OSError:
        pass


@pytest.mark.asyncio
async def test_workspace_note_concurrency_stress(sandbox_env):
    """Stress tests concurrent writes to workspace-note."""
    ctx = MockContext(sandbox_env["root"])

    async def write_note(idx: int):
        return await execute_workspace_note(
            {"title": f"concurrent_note_{idx}", "content": f"Content for note {idx}"},
            ctx,
        )

    results = await asyncio.gather(*(write_note(i) for i in range(40)))
    for i, res in enumerate(results):
        assert res.success is True
        assert res.output["title"] == f"concurrent_note_{i}"
        note_file = sandbox_env["notes"] / f"concurrent_note_{i}.md"
        assert note_file.exists()
        assert f"Content for note {i}" in note_file.read_text(encoding="utf-8")


# =========================================================================
# 3. SKILL-DOCS ADVERSARIAL STRESS
# =========================================================================

@pytest.mark.asyncio
async def test_skill_docs_authorization_and_traversal(sandbox_env):
    """Verifies fail-closed gating, slug regex, and path containment in skill-docs."""
    ws = sandbox_env["root"]
    skills_dir = sandbox_env["skills"]
    outside_file = sandbox_env["outside"]

    # 1. Unauthenticated context (agent is None)
    ctx_no_agent = MockContext(ws, agent=None)
    res = await execute_skill_docs({"skill_id": "test-skill", "doc": "guide.md"}, ctx_no_agent)
    assert res.success is False
    assert "Access denied" in res.error

    # 2. Agent with no skills declared
    agent_empty = AgentManifest(id="empty-agent", title="Empty", skills=[], persona="Role")
    ctx_empty = MockContext(ws, agent=agent_empty)
    res = await execute_skill_docs({"skill_id": "test-skill", "doc": "guide.md"}, ctx_empty)
    assert res.success is False
    assert "not declared" in res.error

    # 3. Agent trying to access undeclared skill
    agent_other = AgentManifest(id="other-agent", title="Other", skills=["other-skill"], persona="Role")
    ctx_other = MockContext(ws, agent=agent_other)
    res = await execute_skill_docs({"skill_id": "test-skill", "doc": "guide.md"}, ctx_other)
    assert res.success is False
    assert "not declared" in res.error

    # 4. Valid agent attempting path traversal in skill_id
    valid_agent = AgentManifest(
        id="valid-agent",
        title="Valid",
        skills=["test-skill"],
        persona="Role",
    )
    ctx_valid = MockContext(ws, agent=valid_agent)

    bad_skill_ids = [
        "../../skills/test-skill",
        "../test-skill",
        "/etc/passwd",
        "test-skill/../../",
        "test skill",
        "test-skill\0",
        "test;rm",
        "test|whoami",
    ]
    for sid in bad_skill_ids:
        res = await execute_skill_docs({"skill_id": sid, "doc": "guide.md"}, ctx_valid)
        assert res.success is False
        assert "Invalid skill_id" in res.error or "Path traversal forbidden" in res.error

    # 5. Path traversal in doc parameter
    bad_docs = [
        "../SKILL.md",
        "../../SKILL.md",
        "../../../carefold.yaml",
        "../../../../etc/passwd",
        "/etc/passwd",
        "guide.md\0.txt",
        "file:///etc/passwd",
        "guide.md/..",
        "guide.md/../../SKILL.md",
    ]
    for d in bad_docs:
        res = await execute_skill_docs({"skill_id": "test-skill", "doc": d}, ctx_valid)
        assert res.success is False
        err_low = res.error.lower()
        assert any(k in err_low for k in ["escapes", "forbidden", "null byte", "unsupported extension"])

    # 6. Disallowed file extension in doc
    ref_dir = skills_dir / "test-skill" / "references"
    (ref_dir / "exploit.sh").write_text("#!/bin/sh\necho hacked", encoding="utf-8")
    res = await execute_skill_docs({"skill_id": "test-skill", "doc": "exploit.sh"}, ctx_valid)
    assert res.success is False
    assert "unsupported extension" in res.error

    # 7. Symlink escape inside references/
    sym_doc = ref_dir / "external_leak.md"
    try:
        os.symlink(outside_file, sym_doc)
        res = await execute_skill_docs({"skill_id": "test-skill", "doc": "external_leak.md"}, ctx_valid)
        assert res.success is False
        assert "escapes" in res.error.lower()
    except OSError:
        pass

    # 8. Legitimate access
    res = await execute_skill_docs({"skill_id": "test-skill", "doc": "guide.md"}, ctx_valid)
    assert res.success is True
    assert "Official Guide" in res.output["content"]


# =========================================================================
# 4. TOOL DISPATCHER & RUNTIME ALLOWLIST GATING
# =========================================================================

@pytest.mark.asyncio
async def test_tool_dispatcher_unknown_tools():
    """Verifies that execute_tool rejects arbitrary or unregistered command names."""
    ctx = None
    unregistered_tools = [
        "bash", "sh", "exec", "eval", "system", "cmd", "powershell",
        "os.system", "__import__", "subprocess", "rm", "cat"
    ]
    for tool_name in unregistered_tools:
        res = await execute_tool(tool_name, {}, ctx)
        assert res.success is False
        assert "not recognized or not available" in res.error


@pytest.mark.asyncio
async def test_runner_runtime_undeclared_tool_interception(sandbox_env):
    """Verifies that execute_agent_run intercepts undeclared tool calls from LLM client."""
    ws = sandbox_env["root"]
    agents_dir = ws / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = agents_dir / "restricted-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Agent declares ONLY attach-read
    (agent_dir / "agent.yaml").write_text(
        """
id: "restricted-agent"
title: "Restricted Agent"
version: "0.1.0"
risk_class: "wellness"
skills: []
tools:
  - "attach-read"
persona:
  role: "Restricted Assistant"
""",
        encoding="utf-8",
    )

    # Custom mock model that maliciously attempts to invoke workspace-note and bash
    class MaliciousToolMockClient:
        def __init__(self):
            self.turn = 0

        async def stream_chat(self, messages, tools=None, temperature=0.2):
            self.turn += 1
            if self.turn == 1:
                # Attempt to invoke workspace-note (undeclared Phase 0 tool)
                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(
                                content=None,
                                tool_calls=[
                                    ModelToolCallChunk(
                                        index=0,
                                        id="call_ws_note",
                                        function=ModelToolFunction(
                                            name="workspace-note",
                                            arguments='{"title": "hacked", "content": "pwned"}',
                                        ),
                                    )
                                ],
                            ),
                        )
                    ]
                )
            elif self.turn == 2:
                # Attempt to invoke arbitrary shell command
                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(
                                content=None,
                                tool_calls=[
                                    ModelToolCallChunk(
                                        index=0,
                                        id="call_bash",
                                        function=ModelToolFunction(
                                            name="bash",
                                            arguments='{"cmd": "whoami"}',
                                        ),
                                    )
                                ],
                            ),
                        )
                    ]
                )
            else:
                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(
                                content="I was unable to run unauthorized tools.",
                                tool_calls=None,
                            ),
                        )
                    ]
                )

    events: List[Dict[str, Any]] = []
    async for event in execute_agent_run(
        agent_id="restricted-agent",
        prompt="Please run note and bash",
        model_client=MaliciousToolMockClient(),
        workspace_root=ws,
    ):
        events.append(event)

    # Verify both tool calls were denied
    tool_ends = [e for e in events if e.get("type") == "tool_end"]
    assert len(tool_ends) == 2
    assert tool_ends[0]["tool"] == "workspace-note"
    assert tool_ends[0]["status"] == "denied"
    assert tool_ends[0]["allowed"] is False
    assert "undeclared tool" in tool_ends[0]["result"]["error"]

    assert tool_ends[1]["tool"] == "bash"
    assert tool_ends[1]["status"] == "denied"
    assert tool_ends[1]["allowed"] is False

    # Verify no note was written to notes directory
    notes_dir = ws / "workspace" / "notes"
    hacked_note = notes_dir / "hacked.md"
    assert not hacked_note.exists()
