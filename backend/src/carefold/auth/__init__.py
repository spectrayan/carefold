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

"""Authentication subsystem providing hexagonal AuthPort and swappable adapters."""

from carefold.auth.adapters.disabled_adapter import (
    DEFAULT_STEWARD_USER,
    DisabledAuthAdapter,
)
from carefold.auth.adapters.oidc_adapter import OidcAuthAdapter
from carefold.auth.adapters.sql_adapter import SqlAuthAdapter
from carefold.auth.factory import (
    create_auth_port,
    get_auth_port,
    reset_auth_port,
    reset_auth_ports,
    set_auth_port,
)
from carefold.auth.ports import (
    AuthPort,
    AuthSession,
    PaginatedUsers,
    PasswordChangeRequest,
    PasswordResetRequest,
    RegisterUserRequest,
    SessionRecord,
    SessionToken,
    UserProfile,
    UserRecord,
    UserUpdate,
    ValidatedSession,
)

__all__ = [
    "AuthPort",
    "AuthSession",
    "DEFAULT_STEWARD_USER",
    "DisabledAuthAdapter",
    "OidcAuthAdapter",
    "PaginatedUsers",
    "PasswordChangeRequest",
    "PasswordResetRequest",
    "RegisterUserRequest",
    "SessionRecord",
    "SessionToken",
    "SqlAuthAdapter",
    "UserProfile",
    "UserRecord",
    "UserUpdate",
    "ValidatedSession",
    "create_auth_port",
    "get_auth_port",
    "reset_auth_port",
    "reset_auth_ports",
    "set_auth_port",
]
