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

"""Carefold Vault Exception Hierarchy.

Defines domain-specific errors for the cryptographic keyring vault,
ensuring fail-closed semantics and zero-silent-plaintext leaks.
"""

from __future__ import annotations


class VaultError(Exception):
    """Base exception for all Carefold cryptographic vault operations."""


class VaultLockedError(VaultError):
    """Raised when the master Key Encryption Key (KEK) is missing, empty, or inaccessible.

    Carefold strictly enforces a fail-closed policy: under no circumstance will the runtime
    silently fall back to unencrypted storage or a hardcoded default key.
    """


class DecryptionError(VaultError):
    """Raised when AES-256-GCM ciphertext decryption or authentication fails.

    Occurs on authentication tag mismatches, corrupted or truncated payloads (<28 bytes),
    bit flips, or mismatches in Authenticated Additional Data (AAD).
    """


class KeyDerivationError(VaultError):
    """Raised when cryptographic key derivation (e.g. Argon2id) fails."""
