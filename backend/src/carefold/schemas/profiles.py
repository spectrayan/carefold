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

"""Pydantic request and response schemas for Family Profiles, Access Governance, and Viewer Invitations."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

ProfileRole = Literal["self", "guardian", "viewer"]
AccessLevel = Literal["manage", "view_clinical", "view_paperwork"]


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Profile full name")
    short_name: Optional[str] = Field(default=None, max_length=64, description="Optional nickname or short name")
    relationship: str = Field(default="self", description="Relationship: self, child, parent, partner, spouse, other")
    role: ProfileRole = Field(default="self", description="Profile role: self, guardian, viewer")
    date_of_birth: Optional[str] = Field(default=None, description="Date of birth YYYY-MM-DD")
    avatar_color: str = Field(default="1", description="Color slot 1-5 or auto")
    avatar_url: Optional[str] = Field(default=None, max_length=512, description="Avatar image URL or path")


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    short_name: Optional[str] = Field(default=None, max_length=64)
    relationship: Optional[str] = None
    role: Optional[ProfileRole] = None
    date_of_birth: Optional[str] = None
    avatar_color: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, max_length=512)


class ProfileConsentResponse(BaseModel):
    id: str
    profile_id: str
    allow_clinical: bool
    terms_version: str
    consented_at: Optional[str] = None
    teen_handover_notified: bool = False


class ProfileConsentUpdate(BaseModel):
    allow_clinical: bool
    terms_version: Optional[str] = "v1.0"


class ProfileAccessResponse(BaseModel):
    id: str
    profile_id: str
    user_id: str
    granted_by: Optional[str] = None
    access_level: AccessLevel
    granted_at: str


class ProfileAccessGrant(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    access_level: AccessLevel = Field(default="view_clinical")


class ProfileSummaryResponse(BaseModel):
    id: str
    user_id: str
    name: str
    short_name: Optional[str] = None
    relationship: str
    role: str
    date_of_birth: Optional[str] = None
    avatar_color: str
    avatar_url: Optional[str] = None
    is_primary: bool
    access_level: AccessLevel
    created_at: str
    updated_at: str


class ProfileDetailResponse(BaseModel):
    id: str
    user_id: str
    name: str
    short_name: Optional[str] = None
    relationship: str
    role: str
    date_of_birth: Optional[str] = None
    avatar_color: str
    avatar_url: Optional[str] = None
    is_primary: bool
    access_level: AccessLevel
    consent: Optional[ProfileConsentResponse] = None
    access_grants: List[ProfileAccessResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str


# Backward-compatible alias
ProfileResponse = ProfileDetailResponse


# ==============================================================================
# VIEWER INVITATION SCHEMAS
# ==============================================================================

class ViewerInviteCreate(BaseModel):
    invitee_name: str = Field(..., min_length=1, max_length=255, description="Name or label of the invited viewer")
    role: ProfileRole = Field(default="viewer", description="Role granted upon acceptance")
    view_clinical: bool = Field(default=True, description="Whether viewer can see clinical visits, prep, and notes")
    view_paperwork: bool = Field(default=False, description="Whether viewer can see paperwork, bills, and insurance")


class ViewerInviteResponse(BaseModel):
    id: str = Field(..., description="Unique invite identifier (UUID)")
    invite_code: str = Field(..., description="Cryptographically secure invite code")
    profile_id: str = Field(..., description="Target profile ID")
    invited_by: Optional[str] = Field(default=None, description="User ID who issued the invitation")
    invitee_name: str = Field(..., description="Name of invited viewer")
    role: str = Field(default="viewer")
    view_clinical: bool = Field(default=True)
    view_paperwork: bool = Field(default=False)
    expires_at: str = Field(..., description="ISO UTC expiration timestamp (7 days)")
    accepted_at: Optional[str] = Field(default=None)
    accepted_by: Optional[str] = Field(default=None)
    created_at: str = Field(...)


class ViewerInviteAcceptRequest(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=128, description="Cryptographic invitation code")


class ViewerInviteAcceptResponse(BaseModel):
    success: bool = True
    message: str = "Invitation accepted successfully"
    profile_id: str
    profile_name: str
    role: str
    access_level: str
    access_id: str


__all__ = [
    "ProfileRole",
    "AccessLevel",
    "ProfileCreate",
    "ProfileUpdate",
    "ProfileConsentResponse",
    "ProfileConsentUpdate",
    "ProfileAccessResponse",
    "ProfileAccessGrant",
    "ProfileSummaryResponse",
    "ProfileDetailResponse",
    "ProfileResponse",
    "ViewerInviteCreate",
    "ViewerInviteResponse",
    "ViewerInviteAcceptRequest",
    "ViewerInviteAcceptResponse",
]
