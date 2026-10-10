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

"""Carefold relational database layer with multi-dialect support (SQLite & PostgreSQL)."""

from carefold.db.base import Base
from carefold.db.models import (
    Agent,
    Attachment,
    ChatThread,
    KnowledgeBase,
    Note,
    PasswordReset,
    Profile,
    ProfileAccess,
    ProfileConsent,
    Session,
    Skill,
    SystemSetting,
    User,
    ViewerInvite,
)
from carefold.db.session import (
    close_db,
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    normalize_database_url,
    reset_engine,
    resolve_database_url,
    sanitize_db_url,
)

__all__ = [
    "Base",
    "User",
    "Session",
    "PasswordReset",
    "SystemSetting",
    "Agent",
    "Skill",
    "KnowledgeBase",
    "Note",
    "Attachment",
    "ChatThread",
    "Profile",
    "ProfileAccess",
    "ProfileConsent",
    "ViewerInvite",
    "create_db_engine",
    "get_engine",
    "get_session_factory",
    "get_db",
    "init_db",
    "close_db",
    "reset_engine",
    "normalize_database_url",
    "sanitize_db_url",
    "resolve_database_url",
]
