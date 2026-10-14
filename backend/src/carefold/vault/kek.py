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

"""Key Encryption Key (KEK) Provider Hierarchy for Carefold Vault.

Implements the 4-tier KEK resolution hierarchy:
1. Mode L OS Keychain: keyring.get_password("carefold_vault", "kek_master")
2. Mode S Mounted Secret File: path from CAREFOLD_VAULT_KEK_FILE (32 raw bytes or 64 hex chars)
3. Argon2id Passphrase Fallback: 32-byte key derivation (Type ID, 64MB memory, 3 iterations, 4 parallelism, 16-byte salt)
4. Fail-closed: missing, empty, or inaccessible KEK raises VaultLockedError.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Literal, Optional, Protocol

import argon2.low_level
from argon2.low_level import Type as Argon2Type

from carefold.vault.errors import KeyDerivationError, VaultLockedError

logger = logging.getLogger("carefold.vault.kek")

DEFAULT_ARGON2_SALT = b"carefold_kek_sal"  # Exactly 16 bytes (128-bit fixed instance salt)

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    keyring = None  # type: ignore[assignment]
    HAS_KEYRING = False


class KekProvider(Protocol):
    """Protocol for Key Encryption Key providers."""

    def get_kek(self) -> bytes:
        """Resolve and return a 32-byte KEK, or raise VaultLockedError."""
        ...


def derive_argon2id_kek(passphrase: str, salt: bytes = DEFAULT_ARGON2_SALT) -> bytes:
    """Derive a 256-bit (32-byte) KEK from an interactive passphrase using Argon2id.

    Args:
        passphrase: User-supplied master passphrase.
        salt: Salt bytes (truncated or padded to exactly 16 bytes).

    Returns:
        32 raw bytes derived encryption key.

    Raises:
        VaultLockedError: If passphrase is empty or whitespace-only.
        KeyDerivationError: If Argon2id key derivation fails.
    """
    if not passphrase or not passphrase.strip():
        raise VaultLockedError("Passphrase cannot be empty for KEK derivation.")

    clean_salt = bytes(salt)[:16].ljust(16, b"0")

    try:
        return argon2.low_level.hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=clean_salt,
            time_cost=3,
            memory_cost=65536,  # 64 MiB
            parallelism=4,
            hash_len=32,
            type=Argon2Type.ID,
        )
    except Exception as exc:
        raise KeyDerivationError(f"Argon2id key derivation failed: {exc}") from exc


def _resolve_from_secret_file(file_path: str) -> bytes:
    """Read a KEK from a mounted secret file, asserting 32 raw bytes or 64 hex characters."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise VaultLockedError(f"Secret file does not exist or is not a file: {file_path}")

    try:
        raw_content = path.read_bytes()
    except Exception as exc:
        raise VaultLockedError(f"Failed to read secret file '{file_path}': {exc}") from exc

    # Invariant: Never strip whitespace from raw 32-byte binary data
    if len(raw_content) == 32:
        return raw_content

    # Handle single trailing newline from file editors
    if len(raw_content) == 33 and raw_content.endswith(b"\n"):
        return raw_content[:32]
    if len(raw_content) == 34 and raw_content.endswith(b"\r\n"):
        return raw_content[:32]

    # Check for 64-character hexadecimal representation
    cleaned_text = raw_content.strip()
    if len(cleaned_text) == 64:
        try:
            decoded = bytes.fromhex(cleaned_text.decode("ascii"))
            if len(decoded) == 32:
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass

    raise VaultLockedError(
        f"Secret file '{file_path}' must contain exactly 32 raw bytes or 64 hex characters (got {len(raw_content)} bytes). Fail-closed."
    )


def resolve_kek(
    mode: Literal["local", "server"] = "local",
    keyring_store: Optional[Dict[str, str]] = None,
    kek_file_path: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> bytes:
    """Resolve the master KEK through the 4-tier precedence hierarchy.

    Hierarchy:
    1. Mode L OS Keychain: Queries keyring.get_password("carefold_vault", "kek_master")
    2. Mode S Mounted Secret File: Reads CAREFOLD_VAULT_KEK_FILE or kek_file_path
    3. Argon2id Passphrase Fallback: Derives 32-byte key via derive_argon2id_kek
    4. Fail-closed: Raises VaultLockedError if missing or inaccessible.

    Args:
        mode: Runtime deployment mode ('local' for Mode L, 'server' for Mode S).
        keyring_store: Optional in-memory mapping to simulate OS keychain in tests.
        kek_file_path: Optional explicit path to secret file.
        passphrase: Optional interactive passphrase.

    Returns:
        Exactly 32 bytes (256-bit) KEK.

    Raises:
        VaultLockedError: If KEK cannot be resolved. Zero plaintext fallback.
    """
    # 1. Mode L: OS Keychain
    if mode == "local":
        if keyring_store is not None:
            # Test fixture / mock keychain store
            raw = keyring_store.get("kek_master") or keyring_store.get("carefold_kek")
            if raw is not None:
                cleaned = raw.strip()
                if not cleaned:
                    raise VaultLockedError("Empty or whitespace keyring value found. Fail-closed.")
                if len(cleaned) == 64:
                    try:
                        return bytes.fromhex(cleaned)
                    except ValueError:
                        pass
                raw_bytes = cleaned.encode("utf-8")
                if len(raw_bytes) == 32:
                    return raw_bytes
                try:
                    decoded = bytes.fromhex(cleaned)
                    if len(decoded) == 32:
                        return decoded
                except ValueError:
                    pass
                raise VaultLockedError(f"Invalid keyring KEK value: {raw}. Fail-closed.")
        elif HAS_KEYRING and keyring is not None:
            try:
                raw_str = (
                    keyring.get_password("carefold_vault", "kek_master")
                    or keyring.get_password("carefold_vault", "carefold_kek")
                )
                if raw_str and raw_str.strip():
                    cleaned = raw_str.strip()
                    if len(cleaned) == 64:
                        try:
                            return bytes.fromhex(cleaned)
                        except ValueError:
                            pass
                    try:
                        decoded = bytes.fromhex(cleaned)
                        if len(decoded) == 32:
                            return decoded
                    except ValueError:
                        pass
                    if len(cleaned.encode("utf-8")) == 32:
                        return cleaned.encode("utf-8")
            except Exception as exc:
                logger.warning("OS keychain lookup failed in Mode L: %s", exc)

    # 2. Mode S: Mounted Secret File
    kek_env_file = kek_file_path or os.environ.get("CAREFOLD_VAULT_KEK_FILE")
    if kek_env_file:
        return _resolve_from_secret_file(kek_env_file)
    elif mode == "server" and not passphrase:
        raise VaultLockedError(
            "Mode S server requires CAREFOLD_VAULT_KEK_FILE or mounted secret file. Fail-closed."
        )

    # 3. Interactive Passphrase Fallback (Argon2id)
    resolved_passphrase = passphrase or os.environ.get("CAREFOLD_VAULT_PASSPHRASE")
    if resolved_passphrase is not None:
        return derive_argon2id_kek(resolved_passphrase)

    # 4. Fail-closed: Zero plaintext fallback
    raise VaultLockedError(
        "KEK is unavailable across OS keyring, secret file, and passphrase. Fail-closed."
    )


def get_kek() -> bytes:
    """Convenience entry point resolving KEK for production runtime using active environment."""
    mode_str = os.environ.get("CAREFOLD_MODE", "local").lower()
    mode: Literal["local", "server"] = "server" if mode_str in ("server", "s") else "local"
    return resolve_kek(mode=mode)
