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

"""OpenID Connect (OIDC) and OAuth2 identity provider authentication adapter skeleton."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union
import urllib.parse

from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.ports import (
    AuthPort,
    PaginatedUsers,
    RegisterUserRequest,
    SessionToken,
    UserProfile,
    UserUpdate,
    ValidatedSession,
)

logger = logging.getLogger(__name__)

SUPPORTED_OIDC_PROVIDERS = frozenset({"google", "github", "keycloak"})


class OidcAuthAdapter(AuthPort):
    """Hexagonal adapter skeleton for OpenID Connect and OAuth2 identity providers."""

    def __init__(
        self,
        sql_adapter: Optional[SqlAuthAdapter] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        issuer_url: Optional[str] = None,
        allowed_providers: Optional[List[str]] = None,
    ) -> None:
        self.sql_adapter = sql_adapter or SqlAuthAdapter()
        self.client_id = client_id or "carefold-client-id"
        self.client_secret = client_secret
        self.issuer_url = issuer_url or "https://auth.carefold.local"
        self.allowed_providers = set(allowed_providers or ["google", "github", "keycloak"])

    def get_authorization_url(self, provider: str, redirect_uri: str, state: str) -> str:
        """Generates standard OAuth2 / OIDC authorization redirect URL for identity provider."""
        prov = provider.lower().strip()
        if prov not in self.allowed_providers:
            raise ValueError(
                f"Unsupported OIDC provider: '{provider}'. Allowed: {sorted(self.allowed_providers)}"
            )

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }

        if prov == "google":
            params["response_type"] = "code"
            params["scope"] = "openid email profile"
            return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

        elif prov == "github":
            params["scope"] = "read:user user:email"
            return f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"

        elif prov == "keycloak":
            params["response_type"] = "code"
            params["scope"] = "openid email profile"
            base = self.issuer_url.rstrip("/")
            return f"{base}/protocol/openid-connect/auth?{urllib.parse.urlencode(params)}"

        raise ValueError(f"Unknown provider '{provider}'")

    async def exchange_code(self, provider: str, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchanges authorization code for identity tokens (skeleton implementation)."""
        prov = provider.lower().strip()
        if prov not in self.allowed_providers:
            raise ValueError(f"Unsupported provider: '{provider}'")

        logger.info("oidc_code_exchange_initiated", provider=prov, redirect_uri=redirect_uri)
        # Skeleton return for upstream OIDC token exchange
        return {
            "provider": prov,
            "code": code,
            "token_type": "Bearer",
            "scope": "openid email profile",
        }

    async def register_user(
        self,
        req_or_email: Optional[Union[RegisterUserRequest, str]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        full_name: Optional[str] = None,
        role: str = "member",
        auth_provider: str = "oidc",
        *,
        email: Optional[str] = None,
        req: Optional[RegisterUserRequest] = None,
    ) -> UserProfile:
        return await self.sql_adapter.register_user(
            req_or_email=req_or_email,
            username=username,
            password=password,
            full_name=full_name,
            role=role,
            auth_provider=auth_provider,
            email=email,
            req=req,
        )

    async def authenticate(
        self,
        username_or_email: str,
        password: str,
    ) -> Optional[UserProfile]:
        raise NotImplementedError(
            "Direct password authentication is not supported under OIDC mode. "
            "Please authenticate through your Single Sign-On (SSO) provider."
        )

    async def create_session(
        self,
        user_id: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_seconds: int = 86400 * 7,
    ) -> SessionToken:
        return await self.sql_adapter.create_session(
            user_id=user_id,
            client_ip=client_ip,
            user_agent=user_agent,
            duration_seconds=duration_seconds,
        )

    async def validate_session(
        self,
        raw_token: str,
    ) -> Optional[ValidatedSession]:
        return await self.sql_adapter.validate_session(raw_token)

    async def revoke_session(
        self,
        raw_token: str,
    ) -> bool:
        return await self.sql_adapter.revoke_session(raw_token)

    async def revoke_all_sessions(
        self,
        user_id: str,
    ) -> int:
        return await self.sql_adapter.revoke_all_sessions(user_id)

    async def create_password_reset_token(
        self,
        email: str,
        expiry_minutes: int = 60,
    ) -> Optional[str]:
        # Password reset is managed upstream by SSO provider
        return None

    async def reset_password(
        self,
        raw_token: str,
        new_password: str,
    ) -> bool:
        return False

    async def change_password(
        self,
        user_id: str,
        old_password: Optional[str] = None,
        new_password: str = "",
        current_password: Optional[str] = None,
    ) -> bool:
        return False

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        query: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PaginatedUsers:
        return await self.sql_adapter.list_users(
            page=page,
            page_size=page_size,
            search=search,
            query=query,
            role=role,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def update_user(
        self,
        user_id: str,
        updates: Optional[Union[UserUpdate, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Optional[UserProfile]:
        return await self.sql_adapter.update_user(user_id=user_id, updates=updates, **kwargs)

    async def has_admin_user(self) -> bool:
        return await self.sql_adapter.has_admin_user()

