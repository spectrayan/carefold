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

"""Model Egress Destination Security and Anti-SSRF Validation.

Enforces Vault Boundary destination checks ensuring model endpoints comply with
allowed hosts, preventing Server-Side Request Forgery (SSRF) and metadata access.
Satisfies AU-15 / S8 and Requirement R6.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Optional, Set
import urllib.parse

logger = logging.getLogger("carefold.model.egress")


class ModelEgressBlockedError(PermissionError):
    """Raised when an LLM endpoint destination violates egress policy."""
    pass


# Unconditionally blocked IP networks and metadata endpoints
METADATA_IPS: Set[str] = {
    "169.254.169.254",  # AWS, Azure, GCP, OpenStack metadata
    "169.254.170.2",    # AWS ECS task metadata
}

IPV4_LINK_LOCAL_NET = ipaddress.ip_network("169.254.0.0/16")
IPV6_LINK_LOCAL_NET = ipaddress.ip_network("fe80::/10")
IPV4_MULTICAST_NET = ipaddress.ip_network("224.0.0.0/4")
IPV6_MULTICAST_NET = ipaddress.ip_network("ff00::/8")
IPV4_BROADCAST_ADDR = ipaddress.ip_address("255.255.255.255")
IPV4_UNSPECIFIED_ADDR = ipaddress.ip_address("0.0.0.0")
IPV6_UNSPECIFIED_ADDR = ipaddress.ip_address("::")

# Canonical cloud provider endpoints
CANONICAL_CLOUD_HOSTS: dict[str, str] = {
    "google": "generativelanguage.googleapis.com",
    "anthropic": "api.anthropic.com",
    "openai": "api.openai.com",
}

# Permitted Ollama local and container hostnames
DEFAULT_OLLAMA_HOSTS: Set[str] = {
    "127.0.0.1",
    "localhost",
    "::1",
    "ollama",
    "host.docker.internal",
}

# Permitted loopback hostnames for custom provider
LOOPBACK_HOSTS: Set[str] = {
    "127.0.0.1",
    "localhost",
    "::1",
}


def _get_configured_allowed_hosts() -> Set[str]:
    """Retrieves additional allowed hosts configured in environment or settings."""
    allowed: Set[str] = set()

    # Environment variable: CAREFOLD_ALLOWED_MODEL_HOSTS (comma-separated)
    env_hosts = os.getenv("CAREFOLD_ALLOWED_MODEL_HOSTS")
    if env_hosts:
        for host in env_hosts.split(","):
            cleaned = host.strip().lower()
            if cleaned:
                allowed.add(cleaned)

    # Application settings: settings.allowed_model_hosts
    try:
        from carefold.config import settings
        cfg_hosts = getattr(settings, "allowed_model_hosts", None)
        if cfg_hosts:
            if isinstance(cfg_hosts, (list, set, tuple)):
                for h in cfg_hosts:
                    cleaned = str(h).strip().lower()
                    if cleaned:
                        allowed.add(cleaned)
            elif isinstance(cfg_hosts, str):
                for h in cfg_hosts.split(","):
                    cleaned = h.strip().lower()
                    if cleaned:
                        allowed.add(cleaned)
    except Exception:
        pass

    return allowed


def validate_model_endpoint(
    provider: str,
    endpoint_url: str,
    allowed_hosts: Optional[Set[str]] = None,
) -> str:
    """Validates that a resolved model endpoint conforms to allowed hosts and anti-SSRF policy.

    Rules:
    1. Scheme must be 'http' or 'https'.
    2. Cloud metadata and link-local IPs are unconditionally blocked (169.254.169.254, 169.254.170.2,
       169.254.0.0/16, fe80::/10).
    3. Broadcast (255.255.255.255), unspecified (0.0.0.0, ::), and multicast (224.0.0.0/4) addresses
       are unconditionally blocked.
    4. Canonical cloud provider hosts:
       - google: generativelanguage.googleapis.com
       - anthropic: api.anthropic.com
       - openai: api.openai.com
       Mismatched hosts for cloud providers raise ModelEgressBlockedError.
    5. Ollama host rules:
       - Loopback (127.0.0.1, localhost, ::1), Docker container DNS (ollama, host.docker.internal)
         are permitted by default.
       - Non-loopback/remote addresses (e.g. 192.168.x.x, 10.x.x.x) require explicit allowlisting in
         CAREFOLD_ALLOWED_MODEL_HOSTS or settings.allowed_model_hosts.
    6. Custom provider host rules:
       - Permitted only if host is in CAREFOLD_ALLOWED_MODEL_HOSTS or loopback, and never targeting metadata IPs.

    Args:
        provider: Provider identifier ('ollama', 'google', 'anthropic', 'openai', 'custom').
        endpoint_url: Target URL string to validate.
        allowed_hosts: Optional set of explicitly allowed hostnames/IPs overriding default lookup.

    Returns:
        The validated endpoint_url string.

    Raises:
        ModelEgressBlockedError: If destination host violates egress policy or scheme is prohibited.
    """
    prov_lower = (provider or "").strip().lower()

    if not endpoint_url or not str(endpoint_url).strip():
        # If endpoint_url is empty, check if canonical default applies
        if prov_lower in CANONICAL_CLOUD_HOSTS:
            return f"https://{CANONICAL_CLOUD_HOSTS[prov_lower]}"
        raise ModelEgressBlockedError(f"Empty endpoint URL for provider '{provider}'.")

    raw_url = str(endpoint_url).strip()
    parsed = urllib.parse.urlparse(raw_url)

    # 1. Scheme Validation: must be http or https
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ModelEgressBlockedError(
            f"Prohibited URL scheme '{parsed.scheme}'. Only http and https schemes are permitted for model endpoints."
        )

    # Extract hostname
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ModelEgressBlockedError(f"Missing host in endpoint URL: '{raw_url}'.")

    # Aggregate configured allowed hosts
    effective_allowed: Set[str] = set()
    if allowed_hosts is not None:
        effective_allowed.update(h.strip().lower() for h in allowed_hosts if h and str(h).strip())
    effective_allowed.update(_get_configured_allowed_hosts())

    # 2. Check if host is an IP address
    ip_obj: Optional[ipaddress.IPv4Address | ipaddress.IPv6Address] = None
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        ip_str = str(ip_obj)

        # Unconditional metadata check
        if ip_str in METADATA_IPS:
            raise ModelEgressBlockedError(
                f"Access to cloud metadata IP '{ip_str}' is strictly blocked."
            )

        # Unconditional link-local check
        if ip_obj in IPV4_LINK_LOCAL_NET or ip_obj in IPV6_LINK_LOCAL_NET or ip_obj.is_link_local:
            raise ModelEgressBlockedError(
                f"Access to link-local address '{ip_str}' is strictly blocked."
            )

        # Unconditional broadcast, unspecified, and multicast checks
        if (
            ip_obj == IPV4_BROADCAST_ADDR
            or ip_obj == IPV4_UNSPECIFIED_ADDR
            or ip_obj == IPV6_UNSPECIFIED_ADDR
            or ip_obj in IPV4_MULTICAST_NET
            or ip_obj in IPV6_MULTICAST_NET
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise ModelEgressBlockedError(
                f"Access to broadcast, unspecified, or multicast address '{ip_str}' is strictly blocked."
            )

        # Loopback check
        is_loopback = ip_obj.is_loopback
        if is_loopback:
            if prov_lower in CANONICAL_CLOUD_HOSTS:
                raise ModelEgressBlockedError(
                    f"Cloud provider '{provider}' cannot target loopback IP '{ip_str}'. "
                    f"Canonical endpoint host is '{CANONICAL_CLOUD_HOSTS[prov_lower]}'."
                )
            if prov_lower in ("ollama", "custom"):
                return raw_url
            # Other providers
            if ip_str in effective_allowed:
                return raw_url
            raise ModelEgressBlockedError(
                f"Loopback IP '{ip_str}' is not permitted for provider '{provider}'."
            )

        # Non-loopback private IP (RFC 1918 / ULA: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
        if ip_obj.is_private:
            if ip_str not in effective_allowed and host not in effective_allowed:
                raise ModelEgressBlockedError(
                    f"Egress to private network IP '{ip_str}' is blocked by default. "
                    f"To permit, add '{ip_str}' to CAREFOLD_ALLOWED_MODEL_HOSTS."
                )

    # 3. Check for metadata domain aliases
    if host in ("metadata.google.internal", "metadata.internal", "instance-data"):
        raise ModelEgressBlockedError(
            f"Access to cloud metadata host '{host}' is strictly blocked."
        )

    # 4. Canonical Cloud Provider Rules
    if prov_lower in CANONICAL_CLOUD_HOSTS:
        canonical_host = CANONICAL_CLOUD_HOSTS[prov_lower]
        if host != canonical_host:
            raise ModelEgressBlockedError(
                f"Provider '{provider}' endpoint host '{host}' does not match canonical host '{canonical_host}'."
            )
        return raw_url

    # 5. Ollama Host Rules
    if prov_lower == "ollama":
        if host in DEFAULT_OLLAMA_HOSTS:
            return raw_url
        if ip_obj is not None and ip_obj.is_loopback:
            return raw_url
        if host in effective_allowed or (ip_obj is not None and str(ip_obj) in effective_allowed):
            return raw_url
        raise ModelEgressBlockedError(
            f"Ollama endpoint host '{host}' is not permitted. Only loopback (127.0.0.1, localhost, ::1) "
            f"and container hosts (ollama, host.docker.internal) are permitted by default. "
            f"Add '{host}' to CAREFOLD_ALLOWED_MODEL_HOSTS to allow."
        )

    # 6. Custom Provider Host Rules
    if prov_lower == "custom":
        if host in LOOPBACK_HOSTS or (ip_obj is not None and ip_obj.is_loopback):
            return raw_url
        if host in effective_allowed or (ip_obj is not None and str(ip_obj) in effective_allowed):
            return raw_url
        if ip_obj is None:
            # Check for blocked internal or cloud metadata suffixes
            if host.endswith(".internal") or host.endswith(".local") or host == "instance-data":
                raise ModelEgressBlockedError(
                    f"Custom provider host '{host}' is an internal domain and not in CAREFOLD_ALLOWED_MODEL_HOSTS."
                )
            return raw_url
        raise ModelEgressBlockedError(
            f"Custom provider host '{host}' is not permitted. Only loopback is allowed by default for IP targets. "
            f"Add '{host}' to CAREFOLD_ALLOWED_MODEL_HOSTS to allow."
        )

    # Any other provider: must be explicitly allowlisted if non-loopback
    if host in LOOPBACK_HOSTS or (ip_obj is not None and ip_obj.is_loopback) or host in effective_allowed:
        return raw_url

    raise ModelEgressBlockedError(
        f"Model endpoint host '{host}' for provider '{provider}' is not permitted."
    )


__all__ = [
    "ModelEgressBlockedError",
    "validate_model_endpoint",
    "CANONICAL_CLOUD_HOSTS",
    "DEFAULT_OLLAMA_HOSTS",
    "METADATA_IPS",
]
