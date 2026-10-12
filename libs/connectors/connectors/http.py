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

"""Sandboxed ScopedHttp client enforcing host allowlists and anti-SSRF boundaries."""

from __future__ import annotations

import ipaddress
from typing import Any, Mapping, Optional, Sequence, Set, Union
import httpx

from connectors.errors import EgressBlockedError

METADATA_IPS: Set[str] = {
    "169.254.169.254",  # AWS/GCP/Azure/OpenStack instance metadata
    "169.254.170.2",    # AWS ECS task metadata
}

METADATA_HOSTS: Set[str] = {
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}


class ScopedHttp:
    """Sandboxed HTTP client that strictly validates outbound URLs against an allowed host list.

    Enforces:
    - Outbound hostnames must be explicitly declared in `allowed_hosts`.
    - Prohibits non-HTTP/HTTPS schemes (e.g. file://, ftp://, gopher://).
    - Enforces allowed schemes and port boundaries when configured via DataFlowSpec.
    - Intercepts and validates all outgoing requests and redirect targets via request hooks.
    - Unconditionally blocks cloud metadata and IPv4/IPv6 link-local addresses.
    - Full async context manager support wrapping httpx.AsyncClient.
    """

    def __init__(
        self,
        allowed_hosts: Sequence[str],
        allowed_schemes: Optional[Sequence[str]] = None,
        allowed_ports: Optional[Sequence[int]] = None,
        timeout: float = 30.0,
        headers: Optional[Mapping[str, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        **kwargs: Any,
    ) -> None:
        self.allowed_hosts: Set[str] = {
            h.strip().lower() for h in allowed_hosts if h and h.strip()
        }
        self.allowed_schemes: Optional[Set[str]] = (
            {s.strip().lower() for s in allowed_schemes if s and s.strip()}
            if allowed_schemes is not None
            else None
        )
        self.allowed_ports: Optional[Set[int]] = (
            {int(p) for p in allowed_ports} if allowed_ports is not None else None
        )
        self._timeout = timeout
        self._headers = dict(headers or {})
        if client is not None:
            self._client = client
            self._owns_client = False
            req_hooks = self._client.event_hooks.setdefault("request", [])
            if self._on_request not in req_hooks:
                req_hooks.append(self._on_request)
        else:
            event_hooks = dict(kwargs.pop("event_hooks", {}))
            req_hooks = list(event_hooks.get("request", []))
            if self._on_request not in req_hooks:
                req_hooks.append(self._on_request)
            event_hooks["request"] = req_hooks

            self._client = httpx.AsyncClient(
                timeout=timeout,
                headers=self._headers,
                transport=transport,
                event_hooks=event_hooks,
                **kwargs,
            )
            self._owns_client = True

    @classmethod
    def from_data_flow(
        cls,
        data_flow: Any,
        **kwargs: Any,
    ) -> ScopedHttp:
        """Constructs a ScopedHttp instance adhering to a manifest DataFlowSpec."""
        return cls(
            allowed_hosts=data_flow.allowed_hosts,
            allowed_schemes=getattr(data_flow, "allowed_schemes", None),
            allowed_ports=getattr(data_flow, "allowed_ports", None),
            **kwargs,
        )

    async def _on_request(self, request: httpx.Request) -> None:
        """Validates all outgoing requests including redirected URLs prior to network transit."""
        self.validate_url(request.url)

    async def __aenter__(self) -> ScopedHttp:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._owns_client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    def validate_url(self, url: Union[str, httpx.URL]) -> httpx.URL:
        """Validates target URL against allowlist and anti-SSRF invariants."""
        try:
            parsed = httpx.URL(url)
        except Exception as err:
            raise EgressBlockedError(f"Malformed destination URL '{url}': {err}") from err

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("https", "http"):
            raise EgressBlockedError(
                f"Scheme '{scheme}' is prohibited. Only https and http are permitted for connector egress."
            )
        if self.allowed_schemes is not None and scheme not in self.allowed_schemes:
            raise EgressBlockedError(
                f"Scheme '{scheme}' is prohibited by manifest policy. "
                f"Allowed schemes: {sorted(self.allowed_schemes)}"
            )

        host = (parsed.host or "").strip().lower()
        if not host:
            raise EgressBlockedError("Target URL does not specify a valid hostname.")

        # Anti-SSRF: unconditionally block cloud metadata and link-local addresses
        if host in METADATA_IPS or host in METADATA_HOSTS or any(host.endswith("." + mh) for mh in METADATA_HOSTS):
            raise EgressBlockedError(
                f"Destination '{host}' is a cloud metadata address and is strictly blocked.",
                host=host,
            )

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_link_local or str(ip) in METADATA_IPS:
                raise EgressBlockedError(
                    f"Destination IP '{ip}' is a link-local or metadata address and is strictly blocked.",
                    host=host,
                )
        except ValueError:
            # Host is a domain name, not a numeric IP
            pass

        # Check against allowed host list
        if host not in self.allowed_hosts:
            raise EgressBlockedError(
                f"Egress to host '{host}' is blocked by manifest policy. "
                f"Allowed hosts: {sorted(self.allowed_hosts)}",
                host=host,
            )

        effective_port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        if self.allowed_ports is not None and effective_port not in self.allowed_ports:
            raise EgressBlockedError(
                f"Port '{effective_port}' is prohibited by manifest policy. "
                f"Allowed ports: {sorted(self.allowed_ports)}",
                host=host,
            )

        return parsed

    async def get(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.get(url, **kwargs)

    async def post(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.post(url, **kwargs)

    async def put(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.put(url, **kwargs)

    async def delete(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.delete(url, **kwargs)

    async def patch(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.patch(url, **kwargs)

    async def head(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.head(url, **kwargs)

    async def options(self, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.options(url, **kwargs)

    async def request(self, method: str, url: Union[str, httpx.URL], **kwargs: Any) -> httpx.Response:
        self.validate_url(url)
        return await self._client.request(method, url, **kwargs)

    async def aclose(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._owns_client:
            await self._client.aclose()


__all__ = [
    "EgressBlockedError",
    "METADATA_HOSTS",
    "METADATA_IPS",
    "ScopedHttp",
]
