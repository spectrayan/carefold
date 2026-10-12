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

"""AES-256-GCM Symmetric Cryptographic Engine for Carefold Vault.

Provides authenticated symmetric encryption with contextual Authenticated Additional
Data (AAD) binding to prevent ciphertext relocation across rows, profiles, or connections.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from carefold.vault.errors import DecryptionError

NONCE_LENGTH = 12  # 96-bit nonce for AES-GCM
TAG_LENGTH = 16    # 128-bit authentication tag
MIN_PAYLOAD_LENGTH = NONCE_LENGTH + TAG_LENGTH  # 28 bytes


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM with contextual Authenticated Additional Data (AAD).

    Args:
        key: Exactly 32 bytes (256 bits) binary encryption key.
        plaintext: Plaintext bytes to encrypt.
        aad: Contextual Authenticated Additional Data bytes bound to the ciphertext.

    Returns:
        12-byte nonce + ciphertext + 16-byte authentication tag.

    Raises:
        ValueError: If key is not exactly 32 bytes.
        TypeError: If key, plaintext, or aad are not bytes-like objects.
    """
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError(
            f"AES-256 requires exactly 32-byte key, got {len(key) if isinstance(key, (bytes, bytearray)) else type(key)}"
        )
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError(f"Plaintext must be bytes-like object, got {type(plaintext)}")
    if isinstance(aad, str):
        aad = aad.encode("utf-8")
    if not isinstance(aad, (bytes, bytearray)):
        raise TypeError(f"AAD must be bytes-like object, got {type(aad)}")

    nonce = os.urandom(NONCE_LENGTH)
    aesgcm = AESGCM(bytes(key))
    ct_and_tag = aesgcm.encrypt(nonce, bytes(plaintext), bytes(aad))
    return nonce + ct_and_tag


def decrypt(key: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Decrypt AES-256-GCM payload and verify authentication tag against AAD.

    Args:
        key: Exactly 32 bytes (256 bits) binary decryption key.
        ciphertext: Encrypted payload (12-byte nonce + ciphertext + 16-byte tag).
        aad: Contextual Authenticated Additional Data bytes that must match encryption.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        ValueError: If key is not exactly 32 bytes.
        TypeError: If key, ciphertext, or aad are not bytes-like objects.
        DecryptionError: If payload is truncated (<28 bytes), ciphertext is corrupted,
                         or authentication tag / AAD verification fails.
    """
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError(
            f"AES-256 requires exactly 32-byte key, got {len(key) if isinstance(key, (bytes, bytearray)) else type(key)}"
        )
    if not isinstance(ciphertext, (bytes, bytearray)):
        raise TypeError(f"Ciphertext must be bytes-like object, got {type(ciphertext)}")
    if isinstance(aad, str):
        aad = aad.encode("utf-8")
    if not isinstance(aad, (bytes, bytearray)):
        raise TypeError(f"AAD must be bytes-like object, got {type(aad)}")

    if len(ciphertext) < MIN_PAYLOAD_LENGTH:
        raise DecryptionError(
            f"Ciphertext payload too short for AES-256-GCM (nonce+tag min {MIN_PAYLOAD_LENGTH} bytes, got {len(ciphertext)})"
        )

    nonce = bytes(ciphertext[:NONCE_LENGTH])
    ct_and_tag = bytes(ciphertext[NONCE_LENGTH:])
    aesgcm = AESGCM(bytes(key))

    try:
        return aesgcm.decrypt(nonce, ct_and_tag, bytes(aad))
    except InvalidTag as exc:
        raise DecryptionError(f"Authentication tag verification failed or AAD mismatch: {exc}") from exc
    except Exception as exc:
        raise DecryptionError(f"Decryption failed: {exc}") from exc
