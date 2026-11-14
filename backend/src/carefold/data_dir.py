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

"""Unified relocatable local data directory, ACL hardening, and instance lock coordination (#331).

Implements:
1. Canonical data-directory precedence:
   `--data-dir` CLI override -> `CAREFOLD_DATA_DIR` -> `CAREFOLD_HOME` -> `CAREFOLD_HOME_DIR`
   -> legacy `CAREFOLD_WORKSPACE_ROOT` fallback -> `~/.carefold` (`%USERPROFILE%\\.carefold`).
2. Cross-platform filesystem permission hardening (`0700` directories / `0600` files on POSIX;
   current-user-only `icacls` DACLs on Windows), including `<data-dir>/webview/`.
3. Safe coexistence via advisory OS lock (`daemon.lock`), atomic runtime manifest (`daemon.json`),
   and read-only Alembic schema revision compatibility checks prior to DB mutation.
4. Runtime mode & workspace metadata for desktop-friendly `/api/v1/health` first-run diagnostics.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Sequence, Set, Tuple
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

from carefold.constants.defaults import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_VERSION
from carefold.constants.paths import (
    AGENTS_DIR,
    DEFAULT_AUDIT_LOG_FILE,
    DEFAULT_CATALOG_DB,
    DEFAULT_CHECKPOINTS_DB,
    DEFAULT_HOME_DIR,
    LOGS_DIR,
    NOTES_DIR,
    SQL_DB_FILENAME,
    UPLOADS_DIR,
)

ENV_CAREFOLD_DATA_DIR = "CAREFOLD_DATA_DIR"
ENV_CAREFOLD_HOME = "CAREFOLD_HOME"
ENV_CAREFOLD_HOME_DIR = "CAREFOLD_HOME_DIR"
ENV_CAREFOLD_WORKSPACE_ROOT = "CAREFOLD_WORKSPACE_ROOT"
ENV_CAREFOLD_RUNTIME_MODE = "CAREFOLD_RUNTIME_MODE"

WEBVIEW_DIR_NAME = "webview"
CAS_DATA_DIR_NAME = "data"
CAS_FILES_SUBDIR_NAME = "files"
DAEMON_MANIFEST_FILENAME = "daemon.json"
DAEMON_LOCK_FILENAME = "daemon.lock"
MIGRATION_SENTINEL_FILENAME = ".migration_done"

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

RuntimeModeLiteral = Literal["desktop", "local", "server", "dev"]

_CLI_OVERRIDE_LOCK = threading.RLock()
_cli_data_dir_override: Optional[Path] = None

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: Dict[Path, "DataDirInstanceLock"] = {}


class DataDirConflictError(RuntimeError):
    """Base error raised when a Carefold data directory cannot be safely acquired."""


class DataDirLockedError(DataDirConflictError):
    """Raised when another active Carefold instance holds the advisory lock on `<data-dir>`."""

    def __init__(self, data_dir: Path, active_manifest: Optional[Dict[str, Any]] = None) -> None:
        self.data_dir = data_dir
        self.active_manifest = active_manifest or {}
        details: list[str] = []
        if self.active_manifest.get("pid") is not None:
            details.append(f"pid={self.active_manifest['pid']}")
        if self.active_manifest.get("mode"):
            details.append(f"mode={self.active_manifest['mode']}")
        host = self.active_manifest.get("host")
        port = self.active_manifest.get("port")
        if host and port:
            details.append(f"endpoint=http://{host}:{port}")
        if self.active_manifest.get("version"):
            details.append(f"version={self.active_manifest['version']}")
        if self.active_manifest.get("started_at"):
            details.append(f"started_at={self.active_manifest['started_at']}")
        holder_summary = f" ({', '.join(details)})" if details else ""
        super().__init__(
            f"Carefold data directory '{data_dir}' is already locked by another running Carefold "
            f"instance{holder_summary}. Close the other Carefold session or launch with a separate "
            f"--data-dir / CAREFOLD_DATA_DIR."
        )


class DataDirSchemaVersionError(DataDirConflictError):
    """Raised when `<data-dir>/carefold.db` carries a newer schema revision than this runtime supports."""

    def __init__(
        self,
        data_dir: Path,
        version_table: str,
        unknown_revisions: Set[str],
        runtime_version: str,
    ) -> None:
        self.data_dir = data_dir
        self.version_table = version_table
        self.unknown_revisions = set(unknown_revisions)
        self.runtime_version = runtime_version
        revs_str = ", ".join(sorted(unknown_revisions))
        super().__init__(
            f"Carefold database in '{data_dir}' uses a newer schema revision "
            f"({version_table}: {revs_str}) than Carefold {runtime_version} understands. "
            f"Upgrade Carefold to match the database schema or choose a separate --data-dir."
        )


@dataclass(frozen=True)
class DaemonManifest:
    """Runtime discovery manifest persisted atomically to `<data-dir>/daemon.json`."""

    pid: int
    host: str
    port: int
    version: str
    mode: str
    started_at: str
    data_dir: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_user_home_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """Resolves the current OS user's home directory across POSIX and Windows."""
    environ = env if env is not None else os.environ
    home_val = environ.get("HOME", "").strip()
    if home_val:
        return Path(home_val)

    userprofile = environ.get("USERPROFILE", "").strip()
    if userprofile:
        return Path(userprofile)

    homedrive = environ.get("HOMEDRIVE", "").strip()
    homepath = environ.get("HOMEPATH", "").strip()
    if homedrive and homepath:
        return Path(f"{homedrive}{homepath}")

    return Path.home()


def expand_tilde_path(raw: Path | str, home: Optional[Path] = None) -> Path:
    """Expands leading `~`, `~/...`, or `~\\...` against `home` deterministically."""
    text = str(raw).strip()
    base_home = home if home is not None else resolve_user_home_dir()
    if text == "~":
        return base_home
    if text.startswith("~/") or text.startswith("~\\"):
        remainder = text[2:]
        return base_home / remainder if remainder else base_home
    return Path(text).expanduser()


def set_cli_data_dir_override(data_dir: Optional[Path | str]) -> Optional[Path]:
    """Sets or clears the highest-precedence `--data-dir` CLI override."""
    global _cli_data_dir_override
    with _CLI_OVERRIDE_LOCK:
        if data_dir is None or not str(data_dir).strip():
            _cli_data_dir_override = None
            return None
        resolved = expand_tilde_path(data_dir).resolve()
        _cli_data_dir_override = resolved
        return resolved


def get_cli_data_dir_override() -> Optional[Path]:
    """Returns the active `--data-dir` CLI override, if any."""
    with _CLI_OVERRIDE_LOCK:
        return _cli_data_dir_override


def clear_cli_data_dir_override() -> None:
    """Clears any active `--data-dir` CLI override."""
    set_cli_data_dir_override(None)


def resolve_data_dir(
    cli_override: Optional[Path | str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Resolves the canonical Carefold local data directory.

    Precedence (highest to lowest):
    1. Explicit `--data-dir <path>` CLI override (`cli_override` or process CLI state)
    2. `CAREFOLD_DATA_DIR` environment variable
    3. `CAREFOLD_HOME` environment variable
    4. `CAREFOLD_HOME_DIR` environment variable
    5. Legacy `CAREFOLD_WORKSPACE_ROOT` fallback heuristic
    6. Cross-platform user home default (`~/.carefold` / `%USERPROFILE%\\.carefold`)
    """
    environ = env if env is not None else os.environ
    user_home = resolve_user_home_dir(environ)

    active_cli = cli_override if cli_override is not None else (
        get_cli_data_dir_override() if env is None else None
    )
    if active_cli is not None and str(active_cli).strip():
        return expand_tilde_path(active_cli, home=user_home).resolve()

    for env_key in (ENV_CAREFOLD_DATA_DIR, ENV_CAREFOLD_HOME, ENV_CAREFOLD_HOME_DIR):
        raw_val = environ.get(env_key, "")
        if raw_val and raw_val.strip():
            return expand_tilde_path(raw_val.strip(), home=user_home).resolve()

    env_ws = environ.get(ENV_CAREFOLD_WORKSPACE_ROOT, "")
    if env_ws and env_ws.strip():
        ws_path = expand_tilde_path(env_ws.strip(), home=user_home).resolve()
        if ws_path.name == DEFAULT_HOME_DIR:
            return ws_path
        if (ws_path / DEFAULT_HOME_DIR).is_dir():
            return (ws_path / DEFAULT_HOME_DIR).resolve()
        if not (ws_path / AGENTS_DIR).is_dir() and not (ws_path / "backend").is_dir():
            return ws_path

    return (user_home / DEFAULT_HOME_DIR).resolve()


def apply_data_dir(data_dir: Path | str, *, set_cli_override: bool = False) -> Path:
    """Applies a resolved data directory across process env, Carefold settings, and yarvelle_core."""
    resolved = expand_tilde_path(data_dir).resolve()
    if set_cli_override:
        set_cli_data_dir_override(resolved)

    os.environ[ENV_CAREFOLD_DATA_DIR] = str(resolved)
    os.environ[ENV_CAREFOLD_HOME] = str(resolved)

    cfg_mod = sys.modules.get("carefold.config")
    if cfg_mod is not None and hasattr(cfg_mod, "settings"):
        settings = cfg_mod.settings
        old_home = settings.home_dir
        settings.home_dir = resolved

        if not os.getenv("CAREFOLD_DATABASE_URL") and not os.getenv("DATABASE_URL"):
            current_db = settings.database_url or ""
            if (
                not current_db
                or current_db == f"sqlite+aiosqlite:///{old_home}/{settings.db_filename}"
                or (
                    current_db.startswith("sqlite+aiosqlite:///")
                    and current_db.endswith(f"/{settings.db_filename}")
                )
            ):
                settings.database_url = f"sqlite+aiosqlite:///{resolved}/{settings.db_filename}"

    return resolved


def resolve_active_host_and_port(env: Optional[Mapping[str, str]] = None) -> Tuple[str, int]:
    """Resolves the active bind host and port from Carefold environment variables."""
    environ = env if env is not None else os.environ
    env_port = environ.get("CAREFOLD_BACKEND_PORT") or environ.get("PORT")
    port = int(env_port) if env_port and env_port.isdigit() else DEFAULT_PORT
    host = (
        environ.get("CAREFOLD_HOST")
        or environ.get("CAREFOLD_BACKEND_HOST")
        or environ.get("HOST")
        or DEFAULT_HOST
    )
    return host, port


def parse_cli_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parses `carefold-server` / `python -m carefold` CLI arguments."""
    from carefold import __version__ as _cf_pkg_version

    default_host, default_port = resolve_active_host_and_port()
    parser = argparse.ArgumentParser(
        prog="carefold-server",
        description="Carefold local health runtime and API server.",
    )
    parser.add_argument(
        "-d",
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Local Carefold data directory (overrides CAREFOLD_DATA_DIR and CAREFOLD_HOME; defaults to ~/.carefold).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Bind host address (default: {default_host}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind TCP port (default: {default_port}).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"carefold {_cf_pkg_version}",
    )
    if argv is None and Path(sys.argv[0]).name.startswith("pytest"):
        parsed = parser.parse_args([])
    else:
        parsed = parser.parse_args(list(argv) if argv is not None else None)
    parsed.explicit_host = parsed.host
    parsed.explicit_port = parsed.port
    if parsed.host is None:
        parsed.host = default_host
    if parsed.port is None:
        parsed.port = default_port
    return parsed


# ============================================================================
# Cross-Platform Filesystem Permission / DACL Hardening
# ============================================================================


def resolve_windows_current_principal(
    env: Optional[Mapping[str, str]] = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Optional[str]:
    """Resolves the current Windows user's SID (preferred, locale-safe) or DOMAIN\\USERNAME."""
    environ = env if env is not None else os.environ
    try:
        proc = runner(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            row = next(csv.reader(io.StringIO(proc.stdout.strip())), [])
            if len(row) >= 2 and row[1].strip().startswith("S-1-"):
                return row[1].strip()
    except Exception:
        pass

    username = environ.get("USERNAME", "").strip()
    userdomain = environ.get("USERDOMAIN", "").strip()
    if username and userdomain:
        return f"{userdomain}\\{username}"
    if username:
        return username
    return None


def build_windows_icacls_command(path: Path, principal: str, *, is_dir: bool) -> list[str]:
    """Builds the `icacls` command restricting `path` strictly to `principal` (no inheritance)."""
    clean_principal = principal.strip()
    if not clean_principal:
        raise ValueError("Windows principal for icacls must be non-empty.")
    target = f"*{clean_principal}" if clean_principal.startswith("S-1-") else clean_principal
    grant_perm = f"{target}:(OI)(CI)F" if is_dir else f"{target}:F"
    return [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        grant_perm,
    ]


def apply_windows_private_dacl(
    path: Path,
    *,
    is_dir: bool,
    principal: Optional[str] = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Applies a current-user-only DACL on Windows via `icacls`."""
    resolved_principal = principal or resolve_windows_current_principal(runner=runner)
    if not resolved_principal:
        return False
    cmd = build_windows_icacls_command(path, resolved_principal, is_dir=is_dir)
    try:
        proc = runner(cmd, check=False, capture_output=True, text=True, timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


def ensure_private_dir(
    path: Path,
    *,
    platform_name: Optional[str] = None,
    windows_dacl_fn: Callable[..., bool] = apply_windows_private_dacl,
) -> Path:
    """Creates `path` (and parents) and enforces `0700` on POSIX or user-only DACL on Windows."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise PermissionError(f"Refusing to use symlinked Carefold data directory: {target}")

    active_os = platform_name or os.name
    if active_os == "nt":
        windows_dacl_fn(target, is_dir=True)
    else:
        try:
            os.chmod(target, PRIVATE_DIR_MODE)
        except OSError:
            pass
    return target


def harden_private_file(
    path: Path,
    *,
    platform_name: Optional[str] = None,
    windows_dacl_fn: Callable[..., bool] = apply_windows_private_dacl,
) -> None:
    """Enforces `0600` on POSIX or user-only DACL on Windows for an existing regular file."""
    target = Path(path)
    if not target.exists() or target.is_symlink() or not target.is_file():
        return

    active_os = platform_name or os.name
    if active_os == "nt":
        windows_dacl_fn(target, is_dir=False)
    else:
        try:
            os.chmod(target, PRIVATE_FILE_MODE)
        except OSError:
            pass


def write_private_file_atomic(
    path: Path,
    content: bytes | str,
    *,
    platform_name: Optional[str] = None,
    windows_dacl_fn: Callable[..., bool] = apply_windows_private_dacl,
) -> None:
    """Atomically writes `path` with `0600` POSIX permissions / Windows current-user DACL."""
    target = Path(path)
    ensure_private_dir(target.parent, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)

    raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    tmp_path = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(tmp_path), flags, PRIVATE_FILE_MODE)
        try:
            os.write(fd, raw_bytes)
            try:
                os.fsync(fd)
            except OSError:
                pass
        finally:
            os.close(fd)
        harden_private_file(tmp_path, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)
        os.replace(tmp_path, target)
        harden_private_file(target, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def harden_data_dir_tree(
    data_dir: Path,
    *,
    platform_name: Optional[str] = None,
    windows_dacl_fn: Callable[..., bool] = apply_windows_private_dacl,
) -> Path:
    """Creates and hardens the canonical `<data-dir>` hierarchy (`0700` dirs, `0600` sensitive files)."""
    root = Path(data_dir).resolve()
    managed_dirs = (
        root,
        root / WEBVIEW_DIR_NAME,
        root / UPLOADS_DIR,
        root / LOGS_DIR,
        root / CAS_DATA_DIR_NAME,
        root / CAS_DATA_DIR_NAME / CAS_FILES_SUBDIR_NAME,
        root / NOTES_DIR,
    )
    for directory in managed_dirs:
        ensure_private_dir(directory, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)

    sqlite_bases = (
        root / SQL_DB_FILENAME,
        root / DEFAULT_CHECKPOINTS_DB,
        root / DEFAULT_CATALOG_DB,
    )
    sensitive_files: list[Path] = [
        root / DAEMON_MANIFEST_FILENAME,
        root / DAEMON_LOCK_FILENAME,
        root / MIGRATION_SENTINEL_FILENAME,
        root / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE,
    ]
    for db_base in sqlite_bases:
        sensitive_files.append(db_base)
        for suffix in ("-wal", "-shm", "-journal"):
            sensitive_files.append(db_base.with_name(f"{db_base.name}{suffix}"))

    for pattern in ("*.token", "*.key"):
        for secret_file in root.glob(pattern):
            sensitive_files.append(secret_file)

    for file_path in sensitive_files:
        harden_private_file(file_path, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)

    cas_root = root / CAS_DATA_DIR_NAME / CAS_FILES_SUBDIR_NAME
    if cas_root.is_dir() and not cas_root.is_symlink():
        for dirpath, dirnames, filenames in os.walk(cas_root, followlinks=False):
            dp = Path(dirpath)
            if not dp.is_symlink() and dp != cas_root:
                ensure_private_dir(dp, platform_name=platform_name, windows_dacl_fn=windows_dacl_fn)
            dirnames[:] = [d for d in dirnames if not (dp / d).is_symlink()]
            for fname in filenames:
                harden_private_file(
                    dp / fname,
                    platform_name=platform_name,
                    windows_dacl_fn=windows_dacl_fn,
                )

    return root


# ============================================================================
# Runtime Manifest (`daemon.json`), Schema Guard & Advisory Instance Lock
# ============================================================================


def read_daemon_manifest(data_dir: Path) -> Optional[Dict[str, Any]]:
    """Reads `<data-dir>/daemon.json` if present and valid JSON."""
    manifest_path = Path(data_dir) / DAEMON_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _bundled_alembic_revisions(script_cfg: Any) -> Set[str]:
    import alembic.script

    script = alembic.script.ScriptDirectory.from_config(script_cfg)
    return {rev.revision for rev in script.walk_revisions() if rev.revision}


def verify_compatible_schema_revisions(
    data_dir: Path,
    *,
    runtime_version: Optional[str] = None,
    db_filename: str = SQL_DB_FILENAME,
) -> None:
    """Verifies `<data-dir>/carefold.db` does not carry a newer Alembic revision before mutation.

    Opens SQLite strictly in read-only `query_only` mode so WAL frames are never checkpointed or
    modified during preflight inspection.
    """
    db_path = Path(data_dir).resolve() / db_filename
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return

    from carefold import __version__ as _cf_pkg_version

    active_version = runtime_version or _cf_pkg_version
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only = ON;")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('alembic_version', 'alembic_version_health');"
            ).fetchall()
        }
        if not tables:
            return

        from carefold.db.session import (
            get_alembic_config,
            get_pack_alembic_config,
            resolve_health_migrations_dir,
        )

        if "alembic_version" in tables:
            db_core_revs = {
                str(r[0])
                for r in conn.execute("SELECT version_num FROM alembic_version;").fetchall()
                if r and r[0]
            }
            if db_core_revs:
                known_core = _bundled_alembic_revisions(get_alembic_config())
                unknown_core = db_core_revs - known_core
                if unknown_core:
                    raise DataDirSchemaVersionError(
                        Path(data_dir).resolve(),
                        "alembic_version",
                        unknown_core,
                        active_version,
                    )

        if "alembic_version_health" in tables:
            pack_dir = resolve_health_migrations_dir()
            if pack_dir.is_dir():
                db_pack_revs = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT version_num FROM alembic_version_health;"
                    ).fetchall()
                    if r and r[0]
                }
                if db_pack_revs:
                    known_pack = _bundled_alembic_revisions(
                        get_pack_alembic_config(pack_dir, "alembic_version_health")
                    )
                    unknown_pack = db_pack_revs - known_pack
                    if unknown_pack:
                        raise DataDirSchemaVersionError(
                            Path(data_dir).resolve(),
                            "alembic_version_health",
                            unknown_pack,
                            active_version,
                        )
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        # If SQLite cannot read headers yet, defer to normal DB initialization/error handling.
        return
    finally:
        conn.close()


def _lock_fd_nonblocking(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:  # pragma: no cover - Windows
        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"1")
            os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def _unlock_fd(fd: int) -> None:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        return
    if msvcrt is not None:  # pragma: no cover - Windows
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


class DataDirInstanceLock:
    """Coordinates exclusive Mode L runtime ownership of `<data-dir>` via `daemon.lock` + `daemon.json`."""

    def __init__(
        self,
        data_dir: Path,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        mode: str = "local",
        version: Optional[str] = None,
    ) -> None:
        from carefold import __version__ as _cf_pkg_version

        self.data_dir = Path(data_dir).resolve()
        self.host = host
        self.port = int(port)
        self.mode = mode
        self.version = version or _cf_pkg_version
        self._fd: Optional[int] = None
        self._refcount = 0
        self.manifest: Optional[DaemonManifest] = None

    @property
    def lock_path(self) -> Path:
        return self.data_dir / DAEMON_LOCK_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / DAEMON_MANIFEST_FILENAME

    def acquire(self, *, check_schema: bool = True) -> DaemonManifest:
        """Acquires the non-blocking OS lock, validates schema compatibility, and writes `daemon.json`."""
        with _PROCESS_LOCKS_GUARD:
            existing = _PROCESS_LOCKS.get(self.data_dir)
            if existing is not None and existing._fd is not None:
                existing._refcount += 1
                assert existing.manifest is not None
                return existing.manifest

            ensure_private_dir(self.data_dir)
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(str(self.lock_path), flags, PRIVATE_FILE_MODE)
            harden_private_file(self.lock_path)

            try:
                _lock_fd_nonblocking(fd)
            except (BlockingIOError, PermissionError, OSError) as exc:
                os.close(fd)
                active = read_daemon_manifest(self.data_dir)
                raise DataDirLockedError(self.data_dir, active_manifest=active) from exc

            try:
                if check_schema:
                    verify_compatible_schema_revisions(self.data_dir, runtime_version=self.version)

                harden_data_dir_tree(self.data_dir)
                manifest = DaemonManifest(
                    pid=os.getpid(),
                    host=self.host,
                    port=self.port,
                    version=self.version,
                    mode=self.mode,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    data_dir=str(self.data_dir),
                )
                write_private_file_atomic(
                    self.manifest_path,
                    json.dumps(manifest.to_dict(), indent=2) + "\n",
                )
            except Exception:
                _unlock_fd(fd)
                os.close(fd)
                raise

            self._fd = fd
            self._refcount = 1
            self.manifest = manifest
            _PROCESS_LOCKS[self.data_dir] = self
            return manifest

    def release(self) -> None:
        """Releases the advisory lock and removes `daemon.json` if owned by this process."""
        with _PROCESS_LOCKS_GUARD:
            owner = _PROCESS_LOCKS.get(self.data_dir)
            if owner is None:
                return
            owner._refcount -= 1
            if owner._refcount > 0:
                return

            _PROCESS_LOCKS.pop(self.data_dir, None)
            try:
                current = read_daemon_manifest(self.data_dir)
                if current is None or current.get("pid") == os.getpid():
                    self.manifest_path.unlink(missing_ok=True)
            except OSError:
                pass

            if owner._fd is not None:
                _unlock_fd(owner._fd)
                try:
                    os.close(owner._fd)
                except OSError:
                    pass
                owner._fd = None

    def __enter__(self) -> DaemonManifest:
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


# ============================================================================
# Runtime Mode & `/api/v1/health` Metadata (#331)
# ============================================================================


def is_git_workspace(workspace_root: Optional[Path] = None) -> bool:
    """Returns True when `workspace_root` (or an immediate parent) is a Git checkout."""
    from carefold.config import settings

    root = Path(workspace_root or settings.workspace_root).resolve()
    return (root / ".git").exists() or (root.parent / ".git").exists()


def detect_runtime_mode(
    workspace_root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> RuntimeModeLiteral:
    """Classifies the active runtime mode (`desktop`, `local`, `server`, or `dev`)."""
    environ = env if env is not None else os.environ
    explicit = (
        environ.get(ENV_CAREFOLD_RUNTIME_MODE)
        or environ.get("CAREFOLD_MODE")
        or ""
    ).strip().lower()
    if explicit in ("desktop", "tauri"):
        return "desktop"
    if explicit in ("server", "mode_s", "s"):
        return "server"
    if explicit in ("local", "mode_l", "l", "installed"):
        return "local"
    if explicit in ("dev", "development"):
        return "dev"

    from carefold.config import settings

    db_url = settings.get_database_url().lower()
    if db_url.startswith("postgresql") or db_url.startswith("postgres"):
        return "server"

    return "dev" if is_git_workspace(workspace_root) else "local"


_HEALTH_COMPONENTS: Optional[Tuple[Any, Any, Any]] = None


def get_carefold_health_components() -> Tuple[Any, Any, Any]:
    """Lazily builds `(CarefoldHealthResponse, get_carefold_health, router)` so CLI/lock imports stay fast."""
    global _HEALTH_COMPONENTS
    if _HEALTH_COMPONENTS is not None:
        return _HEALTH_COMPONENTS

    from fastapi import APIRouter
    import yarvelle_core.api.health as _yc_health
    from yarvelle_core.constants.api import ROUTE_HEALTH
    from yarvelle_core.schemas.health import HealthResponse as _CoreHealthResponse

    class CarefoldHealthResponse(_CoreHealthResponse):
        """Backward-compatible Carefold `/api/v1/health` payload with Mode L runtime metadata."""

        runtimeMode: RuntimeModeLiteral = "local"
        isGitWorkspace: bool = False
        dataDirReady: bool = True

    health_router = APIRouter(tags=["Health"])

    @health_router.get(ROUTE_HEALTH, response_model=CarefoldHealthResponse)
    async def get_carefold_health() -> CarefoldHealthResponse:
        """Returns Carefold health, Ollama reachability, workspace stats, and Mode L readiness metadata."""
        from carefold.config import settings

        _yc_health.DEFAULT_VERSION = DEFAULT_VERSION
        base = await _yc_health.get_health()
        git_ws = is_git_workspace(settings.workspace_root)
        mode = detect_runtime_mode(settings.workspace_root)
        home_ready = settings.get_home_dir().exists()
        return CarefoldHealthResponse(
            **base.model_dump(),
            runtimeMode=mode,
            isGitWorkspace=git_ws,
            dataDirReady=home_ready,
        )

    _HEALTH_COMPONENTS = (CarefoldHealthResponse, get_carefold_health, health_router)
    return _HEALTH_COMPONENTS
