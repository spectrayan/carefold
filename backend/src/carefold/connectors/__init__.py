# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Carefold Connectors Runtime Package (OAuth Broker, Lifecycle, Consent & Sync Engine)."""

from carefold.connectors.lifecycle import (
    check_scope_and_terms_compatibility,
    check_under_13_connection_guard,
    get_connector_manifest,
    get_profile_data_flows,
    grant_connector_consent,
    list_connector_manifests,
    record_sync_failure,
    revoke_connection,
    serialize_connector_manifest,
)
from carefold.connectors.oauth import (
    build_authorization_url,
    create_oauth_state,
    generate_pkce_pair,
    load_connection_tokens,
    refresh_connection_token,
    resolve_redirect_uri,
    store_connection_tokens,
    verify_oauth_state,
    verify_pkce_challenge,
)
from carefold.connectors.sync import run_connection_sync

__all__ = [
    "build_authorization_url",
    "check_scope_and_terms_compatibility",
    "check_under_13_connection_guard",
    "create_oauth_state",
    "generate_pkce_pair",
    "get_connector_manifest",
    "get_profile_data_flows",
    "grant_connector_consent",
    "list_connector_manifests",
    "load_connection_tokens",
    "record_sync_failure",
    "refresh_connection_token",
    "resolve_redirect_uri",
    "revoke_connection",
    "run_connection_sync",
    "serialize_connector_manifest",
    "store_connection_tokens",
    "verify_oauth_state",
    "verify_pkce_challenge",
]
