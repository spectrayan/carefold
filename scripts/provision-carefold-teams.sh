#!/usr/bin/env bash
#
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
#

set -euo pipefail

ORG="spectrayan"
REPO="carefold"

echo "=== Carefold Governance Teams Provisioning ==="
echo "Target Organization: $ORG"
echo "Target Repository:   $REPO"
echo ""

# Ensure gh CLI is available and authenticated
if ! command -v gh &>/dev/null; then
  echo "Error: gh CLI is required but not installed." >&2
  exit 1
fi

CURRENT_USER=$(gh api user --jq '.login' 2>/dev/null || true)
if [ -z "$CURRENT_USER" ]; then
  echo "Error: gh is not authenticated. Run 'gh auth login' first." >&2
  exit 1
fi

echo "Authenticated as: $CURRENT_USER"

# Function to get or create a team
get_or_create_team() {
  local name="$1"
  local description="$2"
  local parent_team_id="${3:-}"

  local existing_id=""
  if existing_id=$(gh api "orgs/$ORG/teams/$name" --jq '.id' 2>/dev/null) && [ -n "$existing_id" ] && [ "$existing_id" != "null" ]; then
    echo "  ✓ Team '$name' already exists (ID: $existing_id)" >&2
    echo "$existing_id"
    return 0
  fi

  echo "  Creating team '$name'..." >&2
  local parent_arg=""
  if [ -n "$parent_team_id" ]; then
    parent_arg="\"parent_team_id\": $parent_team_id,"
  fi

  local team_json
  team_json=$(gh api -X POST "orgs/$ORG/teams" --input - <<EOF
{
  "name": "$name",
  "description": "$description",
  "privacy": "closed",
  $parent_arg
  "notification_setting": "notifications_enabled"
}
EOF
)
  local new_id
  new_id=$(echo "$team_json" | jq -r '.id')
  echo "  ✓ Team '$name' created successfully (ID: $new_id)" >&2
  echo "$new_id"
}

# Function to add a member to a team
add_team_member() {
  local team_slug="$1"
  local username="$2"
  local role="${3:-member}"

  echo "    Adding $username to $team_slug (role: $role)..."
  gh api -X PUT "orgs/$ORG/teams/$team_slug/memberships/$username" -f role="$role" >/dev/null 2>&1 || true
}

# Function to link a team to the carefold repository
link_team_to_repo() {
  local team_slug="$1"
  local permission="${2:-maintain}"

  echo "    Granting $permission permission on $ORG/$REPO to team $team_slug..."
  gh api -X PUT "orgs/$ORG/teams/$team_slug/repos/$ORG/$REPO" -f permission="$permission" >/dev/null 2>&1 || true
}

echo ""
echo "1. Provisioning Root Project Team..."
CAREFOLD_ROOT_ID=$(get_or_create_team "carefold" "Carefold Project — Privacy-preserving clinical AI agent marketplace & runtime")
link_team_to_repo "carefold" "pull"

# Add core team members to root
for u in sbharatjoshi jarvispectrayan titanspectrayan forgespectrayan novaspectrayan nexuspectrayan atlasspectrayan; do
  add_team_member "carefold" "$u"
done

echo ""
echo "2. Provisioning Core Maintainers Team..."
MAINTAINERS_ID=$(get_or_create_team "carefold-maintainers" "Carefold Core Maintainers — Subsystem stewardship, merge rights to main, releases" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-maintainers" "maintain"
for u in sbharatjoshi jarvispectrayan titanspectrayan forgespectrayan nexuspectrayan; do
  add_team_member "carefold-maintainers" "$u" "maintainer"
done

echo ""
echo "3. Provisioning Subsystem Teams..."

# Backend Maintainers
BACKEND_ID=$(get_or_create_team "carefold-maintainers-backend" "Carefold Backend Maintainers — FastAPI runtime, LangGraph nodes, memory ports" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-maintainers-backend" "maintain"
for u in sbharatjoshi jarvispectrayan forgespectrayan titanspectrayan; do
  add_team_member "carefold-maintainers-backend" "$u"
done

# Frontend Maintainers
FRONTEND_ID=$(get_or_create_team "carefold-maintainers-frontend" "Carefold Frontend Maintainers — Next.js marketplace UI, components, Tailwind" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-maintainers-frontend" "maintain"
for u in sbharatjoshi forgespectrayan jarvispectrayan; do
  add_team_member "carefold-maintainers-frontend" "$u"
done

# Packages Maintainers
PACKAGES_ID=$(get_or_create_team "carefold-maintainers-packages" "Carefold Packages Maintainers — CLI and runner sandboxed packages" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-maintainers-packages" "maintain"
for u in sbharatjoshi forgespectrayan nexuspectrayan jarvispectrayan; do
  add_team_member "carefold-maintainers-packages" "$u"
done

# Clinical AI Reviewers
CLINICAL_ID=$(get_or_create_team "carefold-clinical-ai" "Carefold Clinical AI Reviewers — Agent manifests, clinical skill packs, and safety boundaries" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-clinical-ai" "triage"
for u in sbharatjoshi jarvispectrayan titanspectrayan novaspectrayan; do
  add_team_member "carefold-clinical-ai" "$u"
done

# Infrastructure & CI/CD Team
INFRA_ID=$(get_or_create_team "carefold-infra" "Carefold Infrastructure & CI/CD — Docker, GitHub Actions, release pipelines" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-infra" "maintain"
for u in sbharatjoshi nexuspectrayan jarvispectrayan; do
  add_team_member "carefold-infra" "$u"
done

# Documentation Team
DOCS_ID=$(get_or_create_team "carefold-docs" "Carefold Documentation & Living Architecture Decision Records (ADRs)" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-docs" "maintain"
for u in sbharatjoshi jarvispectrayan novaspectrayan atlasspectrayan; do
  add_team_member "carefold-docs" "$u"
done

# Security Team
SECURITY_ID=$(get_or_create_team "carefold-security" "Carefold Security & Vulnerability Response" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-security" "maintain"
for u in sbharatjoshi jarvispectrayan titanspectrayan; do
  add_team_member "carefold-security" "$u"
done

# Committers / Reviewers Team
COMMITTERS_ID=$(get_or_create_team "carefold-committers" "Carefold Committers & Reviewers — Code review authority and issue triage" "$CAREFOLD_ROOT_ID")
link_team_to_repo "carefold-committers" "triage"
for u in sbharatjoshi jarvispectrayan forgespectrayan titanspectrayan novaspectrayan nexuspectrayan atlasspectrayan; do
  add_team_member "carefold-committers" "$u"
done

echo ""
echo "=== All Carefold governance teams successfully provisioned! ==="
