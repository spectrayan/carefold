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

"""Carefold Cryptographic Keyring Vault.

Implements two-tier envelope encryption (KEK -> DEK -> Credentials),
strict AAD binding, and fail-closed key resolution.
"""

from carefold.vault.crypto import decrypt, encrypt
from carefold.vault.dek import (
    compute_aad_binding,
    compute_dek_wrapping_aad,
    decrypt_credential,
    delete_profile_keys,
    encrypt_credential,
    get_or_create_dek,
    rotate_dek,
)
from carefold.vault.errors import (
    DecryptionError,
    KeyDerivationError,
    VaultError,
    VaultLockedError,
)
from carefold.vault.kek import derive_argon2id_kek, get_kek, resolve_kek

__all__ = [
    "encrypt",
    "decrypt",
    "get_kek",
    "resolve_kek",
    "derive_argon2id_kek",
    "get_or_create_dek",
    "encrypt_credential",
    "decrypt_credential",
    "compute_aad_binding",
    "compute_dek_wrapping_aad",
    "rotate_dek",
    "delete_profile_keys",
    "VaultError",
    "VaultLockedError",
    "DecryptionError",
    "KeyDerivationError",
]
