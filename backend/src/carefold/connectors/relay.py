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

"""Stateless PKCE OAuth 2.0 Callback Bounce Relay (AU-70 / ADR-0008).

Provides a zero-storage, HMAC-SHA256 state-sealed callback bounce mechanism
that validates short-lived (`<= 120s` TTL) relay tickets in constant time,
enforces single-use nonce replay protection, and constructs a strict
loopback (`http://127.0.0.1:...`) or companion (`carefold://...`) redirect
without ever exchanging or persisting OAuth tokens or PHI.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, Optional, Set, Union
from urllib.parse import urlparse

MAX_RELAY_TICKET_TTL_SECONDS: int = 120
DEFAULT_RELAY_TICKET_TTL_SECONDS: int = 120


def _b64url_encode(data: bytes) -> str:
    """Encodes raw bytes as unpadded URL-safe base64 string."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Decodes an unpadded URL-safe base64 string into raw bytes."""
    clean = (data or "").strip()
    padding = "=" * ((4 - len(clean) % 4) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii"))


def _normalize_secret_key(secret_key: Union[bytes, str]) -> bytes:
    """Validates and normalizes an HMAC signing key into non-empty bytes."""
    if isinstance(secret_key, str):
        key_bytes = secret_key.encode("utf-8")
    elif isinstance(secret_key, (bytes, bytearray)):
        key_bytes = bytes(secret_key)
    else:
        raise ValueError("secret_key must be bytes or str.")
    if not key_bytes:
        raise ValueError("secret_key cannot be empty.")
    return key_bytes


def validate_relay_callback_target(loopback_callback_url: str) -> str:
    """Validates that a callback URL is strictly local loopback or `carefold://` companion scheme.

    Allowed targets:
    - `http://127.0.0.1(:port)/...`
    - `carefold://...`

    Raises:
        ValueError: If the target URL uses an untrusted host, scheme, or contains userinfo.
    """
    clean_url = (loopback_callback_url or "").strip()
    if not clean_url:
        raise ValueError("loopback_callback_url is required.")

    parsed = urlparse(clean_url)
    scheme = (parsed.scheme or "").lower()

    if parsed.username or parsed.password:
        raise ValueError("loopback_callback_url must not contain userinfo credentials.")

    if scheme == "carefold":
        if not parsed.netloc and not parsed.path:
            raise ValueError("carefold:// callback URL must specify a target path or host.")
        return clean_url

    if scheme == "http":
        hostname = (parsed.hostname or "").lower()
        if hostname != "127.0.0.1":
            raise ValueError(
                f"HTTP relay callback target must bind strictly to 127.0.0.1; got '{parsed.hostname}'."
            )
        if parsed.port is not None and (parsed.port < 1 or parsed.port > 65535):
            raise ValueError(f"Invalid loopback port in callback URL: {parsed.port}")
        return clean_url

    raise ValueError(
        f"Unsupported relay callback URL '{loopback_callback_url}'. "
        "Only 'http://127.0.0.1:...' or 'carefold://...' targets are permitted."
    )


def create_relay_ticket(
    user_id: str,
    profile_id: str,
    connection_id: str,
    loopback_callback_url: str,
    secret_key: Union[bytes, str],
    ttl_seconds: int = DEFAULT_RELAY_TICKET_TTL_SECONDS,
    *,
    now_ts: Optional[int] = None,
) -> str:
    """Creates an HMAC-SHA256 signed stateless relay ticket (`<= 120s` TTL).

    Args:
        user_id: Initiating user identifier.
        profile_id: Target care profile identifier.
        connection_id: Target connection identifier.
        loopback_callback_url: Validated `http://127.0.0.1:...` or `carefold://...` target URL.
        secret_key: HMAC-SHA256 signing key.
        ttl_seconds: Ticket lifetime in seconds (must be in `1..120`, default `120`).
        now_ts: Optional override timestamp for deterministic testing.

    Returns:
        Signed relay ticket formatted as `<base64url_payload>.<hmac_sha256_hex>`.
    """
    clean_user_id = (user_id or "").strip()
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    if not clean_user_id or not clean_profile_id or not clean_connection_id:
        raise ValueError("user_id, profile_id, and connection_id are required to create a relay ticket.")

    validated_cb = validate_relay_callback_target(loopback_callback_url)
    key_bytes = _normalize_secret_key(secret_key)

    ttl = int(ttl_seconds)
    if ttl <= 0 or ttl > MAX_RELAY_TICKET_TTL_SECONDS:
        raise ValueError(
            f"ttl_seconds must be between 1 and {MAX_RELAY_TICKET_TTL_SECONDS} seconds; got {ttl_seconds}."
        )

    issued_at = int(now_ts) if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    payload = {
        "v": 1,
        "uid": clean_user_id,
        "pid": clean_profile_id,
        "cid": clean_connection_id,
        "cb": validated_cb,
        "nonce": secrets.token_hex(16),
        "iat": issued_at,
        "exp": issued_at + ttl,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(key_bytes, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def resolve_stateless_relay_callback(
    relay_ticket: str,
    authorization_code: str,
    secret_key: Union[bytes, str],
    consumed_nonces: Optional[Set[str]] = None,
    *,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Verifies a stateless relay ticket and constructs the loopback/companion redirect target.

    Never exchanges the authorization code and never stores OAuth tokens or PHI.

    Args:
        relay_ticket: Signed `<base64url_payload>.<hmac_sha256_hex>` ticket.
        authorization_code: Upstream OAuth 2.0 authorization code to bounce.
        secret_key: HMAC-SHA256 signing key.
        consumed_nonces: Optional mutable set of consumed nonces for replay defense.
        now_ts: Optional override timestamp for deterministic testing.

    Returns:
        Dictionary containing `redirect_target`, `connection_id`, `profile_id`,
        `user_id`, `nonce`, `stateless=True`, and `tokens_stored=False`.

    Raises:
        ValueError: If signature is invalid, ticket is expired, nonce is replayed,
            or callback target violates the loopback/companion allowlist.
    """
    clean_ticket = (relay_ticket or "").strip()
    clean_code = (authorization_code or "").strip()
    if not clean_ticket or "." not in clean_ticket:
        raise ValueError("Malformed relay_ticket: expected '<payload>.<signature>'.")
    if not clean_code:
        raise ValueError("authorization_code is required.")

    key_bytes = _normalize_secret_key(secret_key)
    payload_b64, provided_sig = clean_ticket.rsplit(".", 1)
    if not payload_b64 or not provided_sig:
        raise ValueError("Malformed relay_ticket segments.")

    expected_sig = hmac.new(key_bytes, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig.encode("ascii"), provided_sig.encode("ascii")):
        raise ValueError("Invalid relay_ticket HMAC signature.")

    try:
        raw_payload = _b64url_decode(payload_b64)
        payload = json.loads(raw_payload.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Failed to decode relay_ticket payload.") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid relay_ticket payload structure.")

    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(exp, int) or not isinstance(iat, int):
        raise ValueError("Relay ticket missing integer 'iat' or 'exp' claims.")

    if (exp - iat) <= 0 or (exp - iat) > MAX_RELAY_TICKET_TTL_SECONDS:
        raise ValueError(f"Relay ticket TTL exceeds maximum allowed {MAX_RELAY_TICKET_TTL_SECONDS}s window.")

    current_ts = int(now_ts) if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    if current_ts > exp:
        raise ValueError("Relay ticket has expired.")

    nonce = str(payload.get("nonce") or "").strip()
    if not nonce:
        raise ValueError("Relay ticket missing cryptographic nonce.")

    if consumed_nonces is not None:
        if nonce in consumed_nonces:
            raise ValueError("Replay detected: relay ticket nonce has already been consumed.")
        consumed_nonces.add(nonce)

    callback_url = validate_relay_callback_target(str(payload.get("cb") or ""))
    connection_id = str(payload.get("cid") or "").strip()
    profile_id = str(payload.get("pid") or "").strip()
    user_id = str(payload.get("uid") or "").strip()
    if not connection_id or not profile_id or not user_id:
        raise ValueError("Relay ticket missing required identity claims.")

    separator = "&" if "?" in callback_url else "?"
    redirect_target = f"{callback_url}{separator}code={clean_code}&state={clean_ticket}"

    return {
        "redirect_target": redirect_target,
        "connection_id": connection_id,
        "profile_id": profile_id,
        "user_id": user_id,
        "nonce": nonce,
        "stateless": True,
        "tokens_stored": False,
    }
