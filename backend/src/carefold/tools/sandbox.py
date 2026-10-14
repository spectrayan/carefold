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

"""Sandbox security utilities for path traversal and symlink escape prevention."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union


class SandboxSecurityError(ValueError):
    """Raised when a path traversal, symlink escape, or security violation is detected."""


URI_SCHEME_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+-.]*://")


def resolve_sandboxed_path(
    base_dir: Union[Path, str],
    user_path: str,
    must_exist: bool = False,
    for_write: bool = False,
) -> Path:
    """Resolves and validates a user-provided path against an allowed base directory.

    Enforces:
    1. Rejection of empty or invalid path input.
    2. Rejection of null bytes (poison null byte attack).
    3. Rejection of URI protocols (e.g. file://, http://).
    4. Strict directory boundary containment (no `../` traversal escapes).
    5. Ancestor directory symlink resolution to prevent escaping symlinks.
    6. Target symlink check (prevents symlinks pointing outside the sandbox and symlink overwrite attacks).
    """
    if not user_path or not isinstance(user_path, str):
        raise SandboxSecurityError("Invalid path: path must be a non-empty string.")

    # 1. Null byte check
    if "\0" in user_path:
        raise SandboxSecurityError("Path traversal forbidden: Null byte detected in path.")

    # 2. URI scheme check
    if URI_SCHEME_REGEX.match(user_path):
        raise SandboxSecurityError("Path traversal forbidden: URI schemes are not permitted.")

    base_path = Path(base_dir).resolve()
    base_path.mkdir(parents=True, exist_ok=True)
    real_base = base_path.resolve()

    # 3. Handle path joining safely
    # If user provided absolute path, verify it is directly under base
    clean_user_path = user_path.strip()
    if os.path.isabs(clean_user_path):
        candidate = Path(clean_user_path)
    else:
        # Prevent Path / "/foo" stripping the left side
        clean_rel = clean_user_path.lstrip("/\\")
        candidate = real_base / clean_rel

    # Guard against symlink write/overwrite attacks prior to path resolution
    if for_write or not must_exist:
        if os.path.islink(candidate) or candidate.is_symlink():
            try:
                real_target = candidate.resolve()
                real_target.relative_to(real_base)
            except (ValueError, RuntimeError, OSError):
                raise SandboxSecurityError(
                    f'Path traversal forbidden: Target path "{user_path}" is a symlink escaping sandbox (escapes allowed directory).'
                )
            raise SandboxSecurityError(
                f'Path traversal forbidden: Target note "{user_path}" is an existing symlink.'
            )

    # 4. Check existing ancestor directories for escaping symlinks before resolution
    current = candidate.parent
    while current != real_base and real_base in current.parents:
        if current.is_symlink() or os.path.islink(current):
            try:
                real_dir = current.resolve()
                real_dir.relative_to(real_base)
            except (ValueError, RuntimeError, OSError):
                raise SandboxSecurityError(
                    f'Path traversal forbidden: Directory symlink "{current}" escapes sandbox "{real_base}".'
                )
            if for_write:
                raise SandboxSecurityError(
                    f'Path traversal forbidden: Target path "{user_path}" contains directory symlink "{current.name}".'
                )
        current = current.parent

    # Lexically normalize to catch traversal through non-directories or unresolvable segments
    norm_candidate = Path(os.path.normpath(candidate))
    try:
        norm_candidate.relative_to(real_base)
        if norm_candidate == real_base and clean_user_path not in ("", "."):
            raise SandboxSecurityError(
                f'Path traversal forbidden: Path "{user_path}" escapes allowed directory "{base_dir}".'
            )
    except ValueError:
        raise SandboxSecurityError(
            f'Path traversal forbidden: Path "{user_path}" escapes allowed directory "{base_dir}".'
        )

    # Resolve normalized path without following nonexistent final symlink yet
    try:
        resolved_candidate = candidate.resolve()
    except Exception:
        resolved_candidate = norm_candidate

    # Boundary check on resolved path
    try:
        resolved_candidate.relative_to(real_base)
        if resolved_candidate == real_base and clean_user_path not in ("", "."):
            raise SandboxSecurityError(
                f'Path traversal forbidden: Path "{user_path}" escapes allowed directory "{base_dir}".'
            )
    except ValueError:
        raise SandboxSecurityError(
            f'Path traversal forbidden: Path "{user_path}" escapes allowed directory "{base_dir}".'
        )

    # 5. Existence and symlink handling
    if must_exist:
        if not resolved_candidate.exists():
            raise FileNotFoundError(f"File not found: {user_path}")

        real_target = resolved_candidate.resolve()
        try:
            real_target.relative_to(real_base)
        except ValueError:
            raise SandboxSecurityError(
                f'Path traversal forbidden: Symlink target "{real_target}" escapes sandbox "{real_base}".'
            )
        return real_target

    # When must_exist is False or for_write is True, guard against symlink overwrite attacks
    if for_write or not must_exist:
        if os.path.islink(candidate) or candidate.is_symlink():
            raise SandboxSecurityError(
                f'Path traversal forbidden: Target note "{user_path}" is an existing symlink.'
            )

    return resolved_candidate
