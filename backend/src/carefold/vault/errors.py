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
