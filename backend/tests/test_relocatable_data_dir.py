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

"""Comprehensive tests for unified relocatable `--data-dir` / `CAREFOLD_DATA_DIR`,
0700/0600 + Windows DACL hardening, `daemon.json` instance lock coexistence,
and Mode L `/api/v1/health` runtime metadata (#331).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from typing import Any, List

from fastapi.testclient import TestClient
import pytest

from carefold.audit.logger import record_audit
from carefold.config import Settings, resolve_carefold_home, settings
from carefold.data_dir import (
    DAEMON_LOCK_FILENAME,
    DAEMON_MANIFEST_FILENAME,
    DataDirInstanceLock,
    DataDirLockedError,
    DataDirSchemaVersionError,
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    apply_data_dir,
    apply_windows_private_dacl,
    build_windows_icacls_command,
    clear_cli_data_dir_override,
    ensure_private_dir,
    harden_data_dir_tree,
    harden_private_file,
    read_daemon_manifest,
    resolve_data_dir,
    resolve_windows_current_principal,
    set_cli_data_dir_override,
    verify_compatible_schema_revisions,
    write_private_file_atomic,
)
from carefold.engine.graph import resolve_checkpointer_path
from carefold.main import create_app, parse_cli_args
from carefold.schemas.audit import AuditEvent
from carefold.storage.cas import store_cas_file


class TestDataDirPrecedenceAndCli:
    """Verifies exact canonical precedence and CLI `--data-dir` parsing."""

    def test_full_precedence_chain(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake_home = tmp_path / "fake_user_home"
        cli_dir = tmp_path / "1_cli_dir"
        env_data_dir = tmp_path / "2_env_data_dir"
        env_home = tmp_path / "3_env_home"
        env_home_dir = tmp_path / "4_env_home_dir"
        env_ws_sandbox = tmp_path / "5_ws_sandbox"
        env_ws_sandbox.mkdir(parents=True)

        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.setenv("CAREFOLD_DATA_DIR", str(env_data_dir))
        monkeypatch.setenv("CAREFOLD_HOME", str(env_home))
        monkeypatch.setenv("CAREFOLD_HOME_DIR", str(env_home_dir))
        monkeypatch.setenv("CAREFOLD_WORKSPACE_ROOT", str(env_ws_sandbox))

        try:
            # 1. Explicit CLI override wins over everything
            set_cli_data_dir_override(cli_dir)
            assert resolve_carefold_home() == cli_dir.resolve()

            # 2. CAREFOLD_DATA_DIR wins over CAREFOLD_HOME / CAREFOLD_HOME_DIR / CAREFOLD_WORKSPACE_ROOT
            clear_cli_data_dir_override()
            assert resolve_carefold_home() == env_data_dir.resolve()

            # 3. CAREFOLD_HOME wins over CAREFOLD_HOME_DIR / CAREFOLD_WORKSPACE_ROOT
            monkeypatch.delenv("CAREFOLD_DATA_DIR")
            assert resolve_carefold_home() == env_home.resolve()

            # 4. CAREFOLD_HOME_DIR wins over CAREFOLD_WORKSPACE_ROOT
            monkeypatch.delenv("CAREFOLD_HOME")
            assert resolve_carefold_home() == env_home_dir.resolve()

            # 5. Legacy CAREFOLD_WORKSPACE_ROOT sandbox fallback
            monkeypatch.delenv("CAREFOLD_HOME_DIR")
            assert resolve_carefold_home() == env_ws_sandbox.resolve()

            # 6. Default <HOME>/.carefold when all overrides unset
            monkeypatch.delenv("CAREFOLD_WORKSPACE_ROOT")
            assert resolve_carefold_home() == (fake_home / ".carefold").resolve()
        finally:
            clear_cli_data_dir_override()

    def test_windows_userprofile_and_tilde_expansion(self, tmp_path: Path) -> None:
        win_profile = tmp_path / "Users" / "Maya"
        env_win = {"USERPROFILE": str(win_profile)}
        assert resolve_data_dir(env=env_win) == (win_profile / ".carefold").resolve()

        env_tilde = {"HOME": str(win_profile), "CAREFOLD_DATA_DIR": "~/EncryptedDrive/carefold-data"}
        assert resolve_data_dir(env=env_tilde) == (
            win_profile / "EncryptedDrive" / "carefold-data"
        ).resolve()

    def test_cli_arg_parsing_for_data_dir_host_and_port(self, tmp_path: Path) -> None:
        custom = tmp_path / "cli_data_root"
        args = parse_cli_args(["--data-dir", str(custom), "--host", "127.0.0.1", "--port", "8123"])
        assert Path(args.data_dir) == custom
        assert args.host == "127.0.0.1"
        assert args.port == 8123

        short_args = parse_cli_args(["-d", str(custom)])
        assert Path(short_args.data_dir) == custom


class TestZeroWritesToDefaultHome:
    """Proves `--data-dir` and `CAREFOLD_DATA_DIR` relocate 100% of state with zero writes to `~/.carefold`."""

    @pytest.mark.asyncio
    async def test_relocated_runtime_writes_zero_files_to_fake_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "isolated_fake_home"
        fake_home.mkdir(parents=True)
        relocated = tmp_path / "relocated_vault_dir"

        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.delenv("CAREFOLD_HOME", raising=False)
        monkeypatch.delenv("CAREFOLD_HOME_DIR", raising=False)
        monkeypatch.setenv("CAREFOLD_DATA_DIR", str(relocated))
        apply_data_dir(relocated, set_cli_override=True)

        try:
            with TestClient(create_app()) as client:
                health_res = client.get("/api/v1/health")
                assert health_res.status_code == 200
                body = health_res.json()
                assert body["dataDirReady"] is True

                # Verify active daemon.json manifest while lifespan is live
                manifest = read_daemon_manifest(relocated)
                assert manifest is not None
                assert manifest["pid"] == os.getpid()
                assert Path(manifest["data_dir"]) == relocated.resolve()

                # Write CAS blob and verify it lands under <relocated>/data/files/
                cas_path, digest, _ = store_cas_file(
                    b"synthetic lab report bytes",
                    user_id="user-1",
                    profile_id="prof-1",
                )
                assert cas_path.is_file()
                assert relocated.resolve() in cas_path.resolve().parents
                assert len(digest) == 64

                # Verify checkpointer path resolves inside <relocated>
                cp_path = resolve_checkpointer_path()
                assert cp_path == relocated.resolve() / "checkpoints.db"
                with sqlite3.connect(str(cp_path)) as conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS cp_probe (id TEXT PRIMARY KEY);")
                    conn.commit()
                harden_private_file(cp_path)

                # Write audit event to canonical audit log path inside <relocated>/logs/audit.jsonl
                await record_audit(
                    event=AuditEvent(agent_id="appointment-prep-coordinator", event="run", allowed=True),
                    log_path=settings.get_audit_log_path(),
                )

            # After clean shutdown, daemon.json is removed while SQLite, CAS, logs, webview remain in <relocated>
            assert not (relocated / DAEMON_MANIFEST_FILENAME).exists()
            assert (relocated / "carefold.db").is_file()
            assert (relocated / "checkpoints.db").is_file()
            assert (relocated / "logs" / "audit.jsonl").is_file()
            assert (relocated / "webview").is_dir()
            assert (relocated / ".migration_done").is_file()

            # Zero writes to <fake_home>/.carefold or anywhere inside fake_home
            assert not (fake_home / ".carefold").exists()
            assert list(fake_home.iterdir()) == []
        finally:
            clear_cli_data_dir_override()

    def test_cli_subprocess_relocates_with_fake_home(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "subproc_fake_home"
        fake_home.mkdir()
        relocated = tmp_path / "subproc_data_dir"
        backend_src = Path(__file__).resolve().parents[1] / "src"

        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["USERPROFILE"] = str(fake_home)
        env.pop("CAREFOLD_HOME", None)
        env.pop("CAREFOLD_HOME_DIR", None)
        env.pop("CAREFOLD_DATA_DIR", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env["PYTHONPATH"] = str(backend_src)

        probe_code = "\n".join(
            [
                "import sys",
                "from carefold.data_dir import DataDirInstanceLock, apply_data_dir, parse_cli_args",
                "args = parse_cli_args(['--data-dir', sys.argv[1]])",
                "resolved = apply_data_dir(args.data_dir, set_cli_override=True)",
                "with DataDirInstanceLock(resolved, host='127.0.0.1', port=8010, mode='desktop') as m:",
                "    assert m.data_dir == str(resolved)",
            ]
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe_code, str(relocated)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert (relocated / "webview").is_dir()
        assert (relocated / DAEMON_LOCK_FILENAME).is_file()
        assert not (fake_home / ".carefold").exists()


class TestPermissionsAndWindowsDacls:
    """Verifies Unix 0700/0600 permissions and Windows user-only DACL construction."""

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits check")
    def test_unix_0700_dirs_and_0600_files_enforced(self, tmp_path: Path) -> None:
        root = tmp_path / "perm_hardened_dir"
        root.mkdir(mode=0o755)
        (root / "webview").mkdir(mode=0o755)
        db_file = root / "carefold.db"
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
            conn.commit()
        db_file.chmod(0o644)
        token_file = root / "runtime.token"
        write_private_file_atomic(token_file, "secret-token-value\n")

        with DataDirInstanceLock(root, host="127.0.0.1", port=8010, mode="desktop", version="0.5.0b2"):
            harden_data_dir_tree(root)
            for subdir in (
                root,
                root / "webview",
                root / "uploads",
                root / "logs",
                root / "data",
                root / "data" / "files",
                root / "notes",
            ):
                mode = stat.S_IMODE(subdir.stat().st_mode)
                assert mode == PRIVATE_DIR_MODE, f"{subdir} had mode {oct(mode)}, expected 0o700"

            for priv_file in (
                db_file,
                token_file,
                root / DAEMON_MANIFEST_FILENAME,
                root / DAEMON_LOCK_FILENAME,
            ):
                fmode = stat.S_IMODE(priv_file.stat().st_mode)
                assert fmode == PRIVATE_FILE_MODE, f"{priv_file} had mode {oct(fmode)}, expected 0o600"

    def test_windows_dacl_builder_and_Simulated_enforcement(self, tmp_path: Path) -> None:
        recorded_cmds: List[List[str]] = []

        def fake_runner(cmd: List[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[0] == "whoami":
                return subprocess.CompletedProcess(
                    cmd, 0, stdout='"DESKTOP\\maya","S-1-5-21-100-200-300-1001"\n', stderr=""
                )
            recorded_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="Successfully processed 1 files", stderr="")

        sid = resolve_windows_current_principal(runner=fake_runner)
        assert sid == "S-1-5-21-100-200-300-1001"

        dir_cmd = build_windows_icacls_command(tmp_path / "win_data", sid, is_dir=True)
        assert dir_cmd == [
            "icacls",
            str(tmp_path / "win_data"),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-100-200-300-1001:(OI)(CI)F",
        ]

        file_cmd = build_windows_icacls_command(tmp_path / "win_data" / "daemon.json", sid, is_dir=False)
        assert file_cmd == [
            "icacls",
            str(tmp_path / "win_data" / "daemon.json"),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-100-200-300-1001:F",
        ]

        win_dir = tmp_path / "simulated_nt"
        ensure_private_dir(
            win_dir,
            platform_name="nt",
            windows_dacl_fn=lambda p, *, is_dir: apply_windows_private_dacl(
                p, is_dir=is_dir, runner=fake_runner
            ),
        )
        secret_file = win_dir / "runtime.token"
        secret_file.write_text("tok", encoding="utf-8")
        harden_private_file(
            secret_file,
            platform_name="nt",
            windows_dacl_fn=lambda p, *, is_dir: apply_windows_private_dacl(
                p, is_dir=is_dir, runner=fake_runner
            ),
        )
        assert len(recorded_cmds) == 2
        assert recorded_cmds[0][-1].endswith(":(OI)(CI)F")
        assert recorded_cmds[1][-1].endswith(":F")


class TestInstanceLockAndWalSafety:
    """Verifies a second runtime detects an active lock cleanly without corrupting or touching SQLite WAL."""

    def test_second_process_detects_lock_without_touching_sqlite_wal(self, tmp_path: Path) -> None:
        shared_dir = tmp_path / "active_locked_data_dir"
        shared_dir.mkdir(parents=True)
        db_path = shared_dir / "carefold.db"
        wal_path = shared_dir / "carefold.db-wal"

        # Open SQLite in WAL mode with uncheckpointed WAL frames held open by an active connection
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA wal_autocheckpoint=0;")
            conn.execute("CREATE TABLE wal_sentinel (id INTEGER PRIMARY KEY, note TEXT);")
            conn.execute("INSERT INTO wal_sentinel (note) VALUES ('uncheckpointed-frame-1');")
            conn.commit()
            conn.execute("INSERT INTO wal_sentinel (note) VALUES ('uncheckpointed-frame-2');")
            conn.commit()

            assert wal_path.is_file() and wal_path.stat().st_size > 0
            wal_hash_before = hashlib.sha256(wal_path.read_bytes()).hexdigest()

            with DataDirInstanceLock(
                shared_dir,
                host="127.0.0.1",
                port=8010,
                mode="desktop",
                version="0.5.0b2",
            ) as active_manifest:
                manifest_bytes_before = (shared_dir / DAEMON_MANIFEST_FILENAME).read_bytes()

                backend_src = Path(__file__).resolve().parents[1] / "src"
                env = os.environ.copy()
                env["PYTHONPATH"] = str(backend_src)
                env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
                env["CAREFOLD_DATA_DIR"] = str(shared_dir)

                contender_script = (
                    "import sys\n"
                    "from pathlib import Path\n"
                    "from carefold.data_dir import DataDirInstanceLock, DataDirLockedError\n"
                    "try:\n"
                    "    DataDirInstanceLock(Path(sys.argv[1]), host='127.0.0.1', port=8011, mode='local').acquire()\n"
                    "except DataDirLockedError as err:\n"
                    "    print(str(err))\n"
                    "    sys.exit(42)\n"
                    "sys.exit(0)\n"
                )
                contender = subprocess.run(
                    [sys.executable, "-c", contender_script, str(shared_dir)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                assert contender.returncode == 42, f"Unexpected contender result: {contender.stdout} {contender.stderr}"
                assert f"pid={active_manifest.pid}" in contender.stdout
                assert "endpoint=http://127.0.0.1:8010" in contender.stdout
                assert "mode=desktop" in contender.stdout

                # Active daemon.json and uncheckpointed SQLite WAL frames must be 100% untouched
                assert (shared_dir / DAEMON_MANIFEST_FILENAME).read_bytes() == manifest_bytes_before
                assert wal_path.is_file()
                wal_hash_after = hashlib.sha256(wal_path.read_bytes()).hexdigest()
                assert wal_hash_after == wal_hash_before

                rows = conn.execute("SELECT note FROM wal_sentinel ORDER BY id;").fetchall()
                assert rows == [("uncheckpointed-frame-1",), ("uncheckpointed-frame-2",)]
                assert conn.execute("PRAGMA integrity_check;").fetchall() == [("ok",)]

            # Lock released cleanly: daemon.json removed, subsequent instance acquires cleanly
            assert not (shared_dir / DAEMON_MANIFEST_FILENAME).exists()
            with DataDirInstanceLock(shared_dir, host="127.0.0.1", port=8012, mode="local") as next_m:
                assert next_m.port == 8012
        finally:
            conn.close()

    def test_newer_schema_revision_raises_clean_diagnostic_without_mutation(self, tmp_path: Path) -> None:
        future_dir = tmp_path / "future_schema_dir"
        future_dir.mkdir(parents=True)
        db_path = future_dir / "carefold.db"

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);")
            conn.execute("INSERT INTO alembic_version (version_num) VALUES ('9999_future_release');")
            conn.commit()

        before_bytes = db_path.read_bytes()
        with pytest.raises(DataDirSchemaVersionError) as exc_info:
            DataDirInstanceLock(future_dir, host="127.0.0.1", port=8010, mode="desktop").acquire()

        assert "9999_future_release" in str(exc_info.value)
        assert not (future_dir / DAEMON_MANIFEST_FILENAME).exists()
        assert db_path.read_bytes() == before_bytes


class TestBackwardCompatAndHealthMetadata:
    """Verifies CAREFOLD_HOME / CAREFOLD_WORKSPACE_ROOT compatibility and `/api/v1/health` runtime metadata."""

    def test_carefold_home_and_workspace_root_backward_compatibility(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        clear_cli_data_dir_override()
        monkeypatch.delenv("CAREFOLD_DATA_DIR", raising=False)

        legacy_home = tmp_path / "legacy_carefold_home"
        monkeypatch.setenv("CAREFOLD_HOME", str(legacy_home))
        s = Settings()
        assert s.get_home_dir() == legacy_home.resolve()
        assert s.get_data_dir() == legacy_home.resolve()
        assert s.get_webview_dir() == legacy_home.resolve() / "webview"

        monkeypatch.delenv("CAREFOLD_HOME")
        monkeypatch.delenv("CAREFOLD_HOME_DIR", raising=False)
        ws_sandbox = tmp_path / "legacy_ws_sandbox"
        ws_sandbox.mkdir()
        monkeypatch.setenv("CAREFOLD_WORKSPACE_ROOT", str(ws_sandbox))
        assert resolve_carefold_home() == ws_sandbox.resolve()

    def test_health_endpoint_exposes_runtime_mode_and_workspace_flags(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CAREFOLD_RUNTIME_MODE", "desktop")
        non_git_ws = tmp_path / "packaged_resources"
        (non_git_ws / "agents" / "appointment-prep-coordinator").mkdir(parents=True)
        (non_git_ws / "skills" / "visit-prep").mkdir(parents=True)
        monkeypatch.setattr(settings, "workspace_root", non_git_ws)

        res = client.get("/api/v1/health")
        assert res.status_code == 200
        payload = res.json()
        assert payload["runtimeMode"] == "desktop"
        assert payload["isGitWorkspace"] is False
        assert payload["dataDirReady"] is True
        assert payload["backendReachable"] is True
