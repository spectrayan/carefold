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

"""Comprehensive Boundary Penetration Test Suite for Carefold Phase 0 Tools Sandbox.

Executes penetration attacks covering:
1. Path traversal in attach-read (../, ..%2f, null bytes, file:// URIs, absolute paths)
2. Symlink escape attacks (pointing into root or sensitive system files)
3. Symlink overwrite attacks in workspace-note (overwriting existing symlinks or writing outside workspace/notes/)
4. Skill authorization bypass in skill-docs (undeclared skills, accessing files outside references/)
"""

import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable, Dict, List, NamedTuple

from carefold.schemas.manifest import AgentManifest
from carefold.tools.attach_read import execute_attach_read
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path
from carefold.tools.skill_docs import execute_skill_docs
from carefold.tools.workspace_note import execute_workspace_note


class TestResult(NamedTuple):
    category: str
    name: str
    passed: bool
    detail: str
    expected_blocked: bool
    actual_blocked: bool


class PenetrationSuite:
    def __init__(self):
        self.results: List[TestResult] = []
        self.temp_dir: Path = None

    def record(
        self,
        category: str,
        name: str,
        passed: bool,
        detail: str,
        expected_blocked: bool = True,
        actual_blocked: bool = True,
    ):
        res = TestResult(category, name, passed, detail, expected_blocked, actual_blocked)
        self.results.append(res)
        status_str = "PASS" if passed else "FAIL [VULNERABILITY]"
        print(f"[{status_str}] {category} -> {name}: {detail}")

    async def run_all(self):
        with tempfile.TemporaryDirectory(prefix="carefold_pentest_") as td:
            self.temp_dir = Path(td)
            print("=" * 80)
            print(f"RUNNING CAREFOLD BOUNDARY PENETRATION SUITE")
            print(f"Temporary test workspace: {self.temp_dir}")
            print("=" * 80)

            await self.test_attach_read_path_traversal()
            await self.test_symlink_escape_attacks()
            await self.test_workspace_note_attacks()
            await self.test_skill_docs_authorization_attacks()

            print("=" * 80)
            print("PENETRATION TEST SUMMARY")
            print("=" * 80)
            total = len(self.results)
            passed = sum(1 for r in self.results if r.passed)
            failed = total - passed
            print(f"Total penetration test cases: {total}")
            print(f"Passed (security controls held): {passed}")
            print(f"Failed (vulnerabilities detected): {failed}")
            print("=" * 80)

            return passed, failed

    async def test_attach_read_path_traversal(self):
        category = "1. attach-read Path Traversal"
        ws = self.temp_dir / "ws_attach"
        att_dir = ws / "attachments" / "test-user" / "test-profile"
        att_dir.mkdir(parents=True, exist_ok=True)

        valid_file = att_dir / "lab_results.txt"
        valid_file.write_text("Normal Lab Results: Hemoglobin 14.5", encoding="utf-8")

        class Ctx:
            workspace_root = ws
            agent = AgentManifest(id="test-agent", title="Test", persona="Role")
            user_id = "test-user"
            profile_id = "test-profile"

        ctx = Ctx()

        # 1.1 Relative ../ traversal outside attachments
        traversal_paths = [
            "../../etc/passwd",
            "../../../etc/passwd",
            "attachments/../../etc/passwd",
            "../attachments/../../etc/passwd",
        ]
        for p in traversal_paths:
            res = await execute_attach_read({"path": p}, ctx)
            blocked = not res.success
            self.record(
                category,
                f"Traversal via '{p}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )

        # 1.2 URL encoded ../ traversal
        url_paths = [
            "..%2fetc/passwd",
            "..%2Fetc%2Fpasswd",
            "..%252fetc/passwd",
            "%2e%2e%2fetc%2fpasswd",
        ]
        for p in url_paths:
            res = await execute_attach_read({"path": p}, ctx)
            blocked = not res.success
            self.record(
                category,
                f"URL encoded traversal '{p}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )

        # 1.3 Null byte injection
        null_paths = [
            "lab_results.txt\0.pdf",
            "\0/etc/passwd",
            "lab_results.txt\x00/../../etc/passwd",
        ]
        for p in null_paths:
            res = await execute_attach_read({"path": p}, ctx)
            blocked = not res.success
            self.record(
                category,
                f"Null byte injection '{repr(p)}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )

        # 1.4 URI scheme injection
        uri_paths = [
            "file:///etc/passwd",
            "file://localhost/etc/passwd",
            "FILE:///etc/passwd",
            "http://127.0.0.1:11434/api/tags",
            "gopher://evil.com",
        ]
        for p in uri_paths:
            res = await execute_attach_read({"path": p}, ctx)
            blocked = not res.success
            self.record(
                category,
                f"URI scheme '{p}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )

        # 1.5 Absolute paths outside attachments
        abs_paths = [
            "/etc/passwd",
            "/private/etc/passwd",
            "/",
            str(self.temp_dir),
        ]
        for p in abs_paths:
            res = await execute_attach_read({"path": p}, ctx)
            blocked = not res.success
            self.record(
                category,
                f"Absolute path '{p}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )

        # 1.6 Disallowed file extension (.py, .sh, .exe, .bin)
        bad_ext_file = att_dir / "exploit.py"
        bad_ext_file.write_text("import os; os.system('echo pwned')", encoding="utf-8")
        res = await execute_attach_read({"path": "exploit.py"}, ctx)
        blocked = not res.success
        self.record(
            category,
            "Disallowed extension 'exploit.py'",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=blocked,
        )

        # 1.7 Directory instead of file
        res = await execute_attach_read({"path": "."}, ctx)
        blocked = not res.success
        self.record(
            category,
            "Directory read '.'",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=blocked,
        )

        # 1.8 Legitimate attachment reading
        res = await execute_attach_read({"path": "lab_results.txt"}, ctx)
        allowed = res.success and "Hemoglobin" in (res.output.get("content") or "")
        self.record(
            category,
            "Legitimate attachment reading 'lab_results.txt'",
            passed=allowed,
            detail=f"Success={res.success}, OutputContent={res.output.get('content') if res.output else None}",
            expected_blocked=False,
            actual_blocked=not res.success,
        )

    async def test_symlink_escape_attacks(self):
        category = "2. Symlink Escape Attacks"
        ws = self.temp_dir / "ws_symlinks"
        att_dir = ws / "attachments" / "test-user" / "test-profile"
        att_dir.mkdir(parents=True, exist_ok=True)

        class Ctx:
            workspace_root = ws
            agent = AgentManifest(id="test-agent", title="Test", persona="Role")
            user_id = "test-user"
            profile_id = "test-profile"

        ctx = Ctx()

        # 2.1 Direct symlink to /etc/passwd
        link_to_passwd = att_dir / "passwd_link.txt"
        try:
            os.symlink("/etc/passwd", link_to_passwd)
            res = await execute_attach_read({"path": "passwd_link.txt"}, ctx)
            blocked = not res.success
            self.record(
                category,
                "Direct symlink to /etc/passwd",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )
        except OSError as e:
            self.record(category, "Direct symlink to /etc/passwd (skip)", True, f"Symlink creation skipped: {e}")

        # 2.2 Directory symlink to root '/'
        dir_symlink = att_dir / "root_dir"
        try:
            os.symlink("/", dir_symlink)
            res = await execute_attach_read({"path": "root_dir/etc/passwd"}, ctx)
            blocked = not res.success
            self.record(
                category,
                "Directory symlink to root '/'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )
        except OSError as e:
            self.record(category, "Directory symlink to root '/' (skip)", True, f"Symlink creation skipped: {e}")

        # 2.3 Nested symlink chain escaping sandbox
        outside_secret = self.temp_dir / "classified.txt"
        outside_secret.write_text("TOP SECRET CLASSIFIED CONTENT", encoding="utf-8")
        hop2 = att_dir / "hop2"
        hop1 = att_dir / "hop1"
        try:
            os.symlink(outside_secret, hop2)
            os.symlink(hop2, hop1)
            res = await execute_attach_read({"path": "hop1"}, ctx)
            blocked = not res.success
            self.record(
                category,
                "Nested symlink chain (hop1 -> hop2 -> outside)",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )
        except OSError as e:
            self.record(category, "Nested symlink chain (skip)", True, f"Symlink creation skipped: {e}")

        # 2.4 Symlink directory to external folder with relative path
        ext_folder = self.temp_dir / "external_folder"
        ext_folder.mkdir(exist_ok=True)
        (ext_folder / "data.txt").write_text("SENSITIVE EXTERNAL DATA", encoding="utf-8")
        sym_ext = att_dir / "ext_link"
        try:
            os.symlink(ext_folder, sym_ext)
            res = await execute_attach_read({"path": "ext_link/data.txt"}, ctx)
            blocked = not res.success
            self.record(
                category,
                "Symlink folder pointing to external directory",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=blocked,
            )
        except OSError as e:
            self.record(category, "Symlink folder (skip)", True, f"Symlink creation skipped: {e}")

    async def test_workspace_note_attacks(self):
        category = "3. workspace-note Symlink & Boundary Attacks"
        ws = self.temp_dir / "ws_notes"
        notes_dir = ws / "workspace" / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        class Ctx:
            workspace_root = ws
            agent = AgentManifest(id="test-agent", title="Test", persona="Role")

        ctx = Ctx()

        # 3.1 Directory traversal in title escaping workspace/notes
        escape_titles = [
            "../../../../etc/cron.d/evil",
            "../../notes_escape",
            "/etc/shadow",
            "../../../workspace/notes/escape",
            "..\\..\\..\\etc\\passwd",
        ]
        for t in escape_titles:
            res = await execute_workspace_note({"title": t, "content": "MALICIOUS NOTE"}, ctx)
            if res.success:
                written_file = notes_dir / f"{res.output['title']}.md"
                # Check that the written file is strictly contained within notes_dir
                contained = False
                try:
                    written_file.resolve().relative_to(notes_dir.resolve())
                    contained = True
                except ValueError:
                    contained = False
                self.record(
                    category,
                    f"Title traversal sanitization '{t}'",
                    passed=contained,
                    detail=f"Sanitized to '{res.output['title']}.md', strictly contained in notes_dir: {contained}",
                    expected_blocked=False,
                    actual_blocked=False,
                )
            else:
                self.record(
                    category,
                    f"Title traversal '{t}' rejected",
                    passed=True,
                    detail=f"Blocked with error: {res.error}",
                    expected_blocked=True,
                    actual_blocked=True,
                )

        # 3.2 Overwrite external file via symlink in notes_dir
        victim_external = self.temp_dir / "victim_external.txt"
        victim_external.write_text("SENSITIVE EXTERNAL CONTENT", encoding="utf-8")
        symlink_ext_note = notes_dir / "external-symlink.md"
        try:
            if symlink_ext_note.is_symlink() or symlink_ext_note.exists():
                symlink_ext_note.unlink()
            os.symlink(victim_external, symlink_ext_note)
            res = await execute_workspace_note(
                {"title": "external-symlink", "content": "OVERWRITE EXTERNAL"}, ctx
            )
            victim_unchanged = victim_external.read_text(encoding="utf-8") == "SENSITIVE EXTERNAL CONTENT"
            blocked = not res.success and victim_unchanged
            self.record(
                category,
                "Symlink overwrite of external target",
                passed=blocked,
                detail=f"Blocked={blocked}, Success={res.success}, Error={res.error}, VictimUnchanged={victim_unchanged}",
                expected_blocked=True,
                actual_blocked=not res.success,
            )
        except OSError as e:
            self.record(category, "Symlink overwrite external (skip)", True, f"Skipped: {e}")

        # 3.3 Overwrite existing symlink pointing INSIDE notes_dir (Vulnerability Test)
        # Requirement: Tool must NOT overwrite existing symlinks or use them to overwrite existing notes!
        victim_internal = notes_dir / "confidential_doctor_note.md"
        victim_internal.write_text("CONFIDENTIAL DOCTOR INSTRUCTIONS - DO NOT ALTER", encoding="utf-8")
        symlink_internal = notes_dir / "shortcut_note.md"
        try:
            if symlink_internal.is_symlink() or symlink_internal.exists():
                symlink_internal.unlink()
            os.symlink(victim_internal, symlink_internal)

            # Attack: execute workspace-note with title "shortcut_note"
            res = await execute_workspace_note(
                {"title": "shortcut_note", "content": "MALICIOUS OVERWRITE CONTENT"}, ctx
            )

            current_victim_text = victim_internal.read_text(encoding="utf-8")
            is_overwritten = "MALICIOUS OVERWRITE CONTENT" in current_victim_text
            # Security requirement: Operation must be REJECTED, and existing symlink must NOT be followed/overwritten
            # Expected: res.success is False, is_overwritten is False
            passed = (res.success is False) and (not is_overwritten)
            self.record(
                category,
                "Symlink overwrite of internal target (shortcut_note -> confidential_doctor_note)",
                passed=passed,
                detail=f"TargetOverwritten={is_overwritten}, ToolSuccess={res.success}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=not res.success,
            )
        except OSError as e:
            self.record(category, "Symlink overwrite internal (skip)", True, f"Skipped: {e}")

        # 3.4 Writing through dangling symlink inside notes_dir
        target_nonexistent = notes_dir / "target_never_existed.md"
        dangling_symlink = notes_dir / "dangling_link.md"
        try:
            if dangling_symlink.is_symlink() or dangling_symlink.exists():
                dangling_symlink.unlink()
            if target_nonexistent.exists():
                target_nonexistent.unlink()
            os.symlink(target_nonexistent, dangling_symlink)

            res = await execute_workspace_note(
                {"title": "dangling_link", "content": "WRITING THROUGH DANGLING SYMLINK"}, ctx
            )

            # Expected: operation should be rejected because target note is an existing symlink
            passed = res.success is False
            target_created = target_nonexistent.exists()
            self.record(
                category,
                "Writing through dangling internal symlink",
                passed=passed,
                detail=f"ToolSuccess={res.success}, TargetCreatedViaSymlink={target_created}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=not res.success,
            )
        except OSError as e:
            self.record(category, "Dangling symlink (skip)", True, f"Skipped: {e}")

    async def test_skill_docs_authorization_attacks(self):
        category = "4. skill-docs Authorization & Boundary Attacks"
        ws = self.temp_dir / "ws_skills"
        skills_dir = ws / "skills"
        skill1_dir = skills_dir / "visit-prep"
        ref1_dir = skill1_dir / "references"
        ref1_dir.mkdir(parents=True, exist_ok=True)
        (ref1_dir / "checklist.md").write_text("# Visit Preparation Checklist", encoding="utf-8")
        (skill1_dir / "SKILL.md").write_text("# SKILL MANIFEST", encoding="utf-8")

        skill2_dir = skills_dir / "benefits-explainer"
        ref2_dir = skill2_dir / "references"
        ref2_dir.mkdir(parents=True, exist_ok=True)
        (ref2_dir / "copay_guide.md").write_text("# Copay Guide", encoding="utf-8")

        class Ctx:
            workspace_root = ws
            skills_dir = ws / "skills"
            agent = AgentManifest(
                id="visit-specialist",
                title="Visit Specialist",
                skills=["visit-prep"],
                persona="Role",
            )

        ctx_auth = Ctx()

        # 4.1 Access undeclared skill
        res = await execute_skill_docs({"skill_id": "benefits-explainer", "doc": "copay_guide.md"}, ctx_auth)
        blocked = not res.success and "not declared" in (res.error or "")
        self.record(
            category,
            "Undeclared skill access (benefits-explainer)",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=not res.success,
        )

        # 4.2 Unauthenticated context (agent=None)
        class CtxNoAgent:
            workspace_root = ws
            skills_dir = ws / "skills"
            agent = None

        res = await execute_skill_docs({"skill_id": "visit-prep", "doc": "checklist.md"}, CtxNoAgent())
        blocked = not res.success and "Access denied" in (res.error or "")
        self.record(
            category,
            "Unauthenticated agent context",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=not res.success,
        )

        # 4.3 Traversal outside references/ via doc parameter
        traversal_docs = [
            "../SKILL.md",
            "../../carefold.yaml",
            "../../../etc/passwd",
            "/etc/passwd",
            "file:///etc/passwd",
            "checklist.md\0.txt",
        ]
        for d in traversal_docs:
            res = await execute_skill_docs({"skill_id": "visit-prep", "doc": d}, ctx_auth)
            blocked = not res.success
            self.record(
                category,
                f"Traversal in doc '{d}'",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=not res.success,
            )

        # 4.4 Disallowed file extension (.py, .sh)
        (ref1_dir / "exploit.py").write_text("print('pwned')", encoding="utf-8")
        res = await execute_skill_docs({"skill_id": "visit-prep", "doc": "exploit.py"}, ctx_auth)
        blocked = not res.success and "unsupported extension" in (res.error or "")
        self.record(
            category,
            "Disallowed file extension 'exploit.py'",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=not res.success,
        )

        # 4.5 Symlink escape in references/
        sym_doc = ref1_dir / "shadow_link.md"
        try:
            os.symlink("/etc/passwd", sym_doc)
            res = await execute_skill_docs({"skill_id": "visit-prep", "doc": "shadow_link.md"}, ctx_auth)
            blocked = not res.success and "escapes" in (res.error or "").lower()
            self.record(
                category,
                "Symlink escape in references/ to /etc/passwd",
                passed=blocked,
                detail=f"Blocked={blocked}, Error={res.error}",
                expected_blocked=True,
                actual_blocked=not res.success,
            )
        except OSError as e:
            self.record(category, "Symlink escape in references/ (skip)", True, f"Skipped: {e}")

        # 4.6 Path traversal in skill_id
        res = await execute_skill_docs({"skill_id": "../../skills/benefits-explainer", "doc": "copay_guide.md"}, ctx_auth)
        blocked = not res.success
        self.record(
            category,
            "Path traversal in skill_id",
            passed=blocked,
            detail=f"Blocked={blocked}, Error={res.error}",
            expected_blocked=True,
            actual_blocked=not res.success,
        )

        # 4.7 Legitimate declared skill doc access
        res = await execute_skill_docs({"skill_id": "visit-prep", "doc": "checklist.md"}, ctx_auth)
        allowed = res.success and "Visit Preparation" in (res.output.get("content") or "")
        self.record(
            category,
            "Legitimate declared skill doc access",
            passed=allowed,
            detail=f"Success={res.success}, ContentLength={len(res.output.get('content') or '') if res.output else 0}",
            expected_blocked=False,
            actual_blocked=not res.success,
        )


if __name__ == "__main__":
    suite = PenetrationSuite()
    passed, failed = asyncio.run(suite.run_all())
    sys.exit(0 if failed == 0 else 1)
