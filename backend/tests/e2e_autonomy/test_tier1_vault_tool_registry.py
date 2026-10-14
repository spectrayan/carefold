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

"""Tier 1: Feature Coverage in Isolation — Keyring Vault & ToolSpec Registry.

Covers Feature 1 (Keyring Vault AU-14) and Feature 2 (ToolSpec Registry AU-16)
with >=5 comprehensive isolated tests per feature.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict
import pytest

from tests.e2e_autonomy.contracts import (
    DecryptionError,
    InMemoryProfileKeyStore,
    ToolSpec,
    ToolSpecRegistry,
    VaultLockedError,
    compute_aad_binding,
    create_default_registry,
    decrypt,
    derive_argon2id_kek,
    encrypt,
    resolve_kek,
)


# ============================================================================
# Feature 1: Cryptographic Keyring Vault (AU-14)
# ============================================================================

def test_t1_f1_aes_256_gcm_encryption_roundtrip(sample_kek: bytes):
    """F1.1: Verify AES-256-GCM encryption round-trip with 12-byte nonce and tag."""
    secret_token = b"oauth_refresh_token_epic_sandbox_secret_998877"
    aad = b"prof-101|conn-epic|1"

    ciphertext = encrypt(sample_kek, secret_token, aad)

    # Invariant: ciphertext length must include 12-byte nonce + payload + 16-byte tag
    assert len(ciphertext) >= 12 + len(secret_token) + 16
    assert ciphertext != secret_token

    decrypted = decrypt(sample_kek, ciphertext, aad)
    assert decrypted == secret_token


def test_t1_f1_kek_hierarchy_mode_l_keychain(mock_keyring: Dict[str, str]):
    """F1.2: Mode L resolves KEK from OS keychain credential store."""
    kek = resolve_kek(mode="local", keyring_store=mock_keyring)
    assert isinstance(kek, bytes)
    assert len(kek) == 32
    assert kek == bytes.fromhex(mock_keyring["carefold_kek"])


def test_t1_f1_kek_hierarchy_mode_s_secret_file(tmp_path: Path):
    """F1.3: Mode S resolves KEK from mounted secret file (CAREFOLD_VAULT_KEK_FILE)."""
    raw_key = os.urandom(32)
    secret_file = tmp_path / "carefold_kek.secret"
    secret_file.write_bytes(raw_key)

    kek = resolve_kek(mode="server", kek_file_path=str(secret_file))
    assert kek == raw_key
    assert len(kek) == 32


def test_t1_f1_kek_hierarchy_argon2id_passphrase_fallback():
    """F1.4: Resolves 256-bit KEK via Argon2id passphrase when keychain/file absent."""
    passphrase = "Correct-Horse-Battery-Staple-Carefold-2026!"
    kek_1 = resolve_kek(mode="local", passphrase=passphrase)
    kek_2 = resolve_kek(mode="server", passphrase=passphrase)

    assert isinstance(kek_1, bytes)
    assert len(kek_1) == 32
    # Deterministic derivation from identical passphrase and salt
    assert kek_1 == kek_2


def test_t1_f1_kek_hierarchy_fails_closed_when_all_absent():
    """F1.5: Missing KEK raises VaultLockedError; zero plaintext fallback allowed."""
    with pytest.raises(VaultLockedError, match="KEK is unavailable"):
        resolve_kek(mode="local", keyring_store={}, kek_file_path=None, passphrase=None)


def test_t1_f1_dek_per_profile_generation_and_storage(
    profile_key_store: InMemoryProfileKeyStore,
    sample_kek: bytes,
    sample_profile_id: str,
):
    """F1.6: Unique 256-bit DEK generated per profile, encrypted under KEK."""
    dek_1, ver_1 = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    assert len(dek_1) == 32
    assert ver_1 == 1

    # Second fetch returns identical DEK without regeneration
    dek_2, ver_2 = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    assert dek_1 == dek_2
    assert ver_1 == ver_2

    # Different profile gets distinct DEK
    dek_other, _ = profile_key_store.get_or_create_dek("prof-other-7766", sample_kek)
    assert dek_other != dek_1


def test_t1_f1_aad_binding_profile_connection_version(
    sample_kek: bytes,
    sample_profile_id: str,
    sample_connection_id: str,
):
    """F1.7: Strict AAD binding f'{profile_id}|{connection_id}|{dek_version}'."""
    aad = compute_aad_binding(sample_profile_id, sample_connection_id, dek_version=1)
    assert aad == f"{sample_profile_id}|{sample_connection_id}|1".encode("utf-8")

    token = b"secure_portal_refresh_token_xyz"
    encrypted = encrypt(sample_kek, token, aad)

    # Decryption succeeds with matching AAD
    assert decrypt(sample_kek, encrypted, aad) == token


def test_t1_f1_crypto_shredding_on_profile_delete(
    profile_key_store: InMemoryProfileKeyStore,
    sample_kek: bytes,
    sample_profile_id: str,
    sample_connection_id: str,
):
    """F1.8: Crypto-shredding: deleting profile drops DEK, rendering tokens unrecoverable."""
    dek, ver = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    aad = compute_aad_binding(sample_profile_id, sample_connection_id, ver)
    secret_bytes = b"phi_patient_summary_record"
    encrypted_payload = encrypt(dek, secret_bytes, aad)

    # Delete profile keys (cascade simulation)
    deleted = profile_key_store.delete_profile_keys(sample_profile_id)
    assert deleted is True
    assert not profile_key_store.has_profile_key(sample_profile_id)

    # Next get_or_create_dek generates a NEW key; old payload can never be decrypted
    new_dek, new_ver = profile_key_store.get_or_create_dek(sample_profile_id, sample_kek)
    assert new_dek != dek

    with pytest.raises(DecryptionError):
        decrypt(new_dek, encrypted_payload, aad)


# ============================================================================
# Feature 2: ToolSpec Registry & 4 Risk Tiers (AU-16)
# ============================================================================

def test_t1_f2_toolspec_registry_all_four_risk_tiers():
    """F2.1: Registry declares and distinguishes all 4 explicit risk tiers."""
    reg = ToolSpecRegistry()
    t_read = ToolSpec("lab_query", "Read lab results", {}, risk_tier="read")
    t_wlocal = ToolSpec("save_note", "Write local notes", {}, risk_tier="write_local")
    t_wext = ToolSpec("sync_cal", "Sync Google Cal", {}, risk_tier="write_external", data_flows=("calendar.google.com",))
    t_irrev = ToolSpec("cancel_insurance", "Cancel policy", {}, risk_tier="irreversible")

    for t in (t_read, t_wlocal, t_wext, t_irrev):
        reg.register(t)

    assert reg.get("lab_query").risk_tier == "read"
    assert reg.get("save_note").risk_tier == "write_local"
    assert reg.get("sync_cal").risk_tier == "write_external"
    assert reg.get("cancel_insurance").risk_tier == "irreversible"


def test_t1_f2_builtin_tools_redeclaration(tool_registry: ToolSpecRegistry):
    """F2.2: Re-declare 9 built-in tools as typed ToolSpecs with valid tiers."""
    expected_builtins = {
        "attach-read": "read",
        "workspace-note": "write_local",
        "skill-docs": "read",
        "delegate_to_agent": "read",
        "list_agents": "read",
        "sanitize_pii": "read",
        "extract_structured_data": "read",
        "validate_grounding": "read",
        "extract_document_dossier": "read",
    }
    for name, expected_tier in expected_builtins.items():
        spec = tool_registry.get(name)
        assert spec is not None, f"Built-in tool '{name}' not found in registry"
        assert spec.risk_tier == expected_tier
        assert spec.trust == "trusted"


def test_t1_f2_profile_tool_filtering_adult(tool_registry: ToolSpecRegistry, sample_profile_id: str):
    """F2.3: Adult profile without restrictions retains all registered tools."""
    tools = tool_registry.list_for_profile(sample_profile_id, age_band="adult")
    names = {t.name for t in tools}
    assert "attach-read" in names
    assert "workspace-note" in names
    assert len(tools) == len(tool_registry.list_all())


def test_t1_f2_profile_tool_filtering_child_under_13_blocks_external():
    """F2.4: Profile filtering for child_under_13 strictly excludes write_external tools."""
    reg = ToolSpecRegistry()
    reg.register(ToolSpec("local_vital", "Save vitals", {}, risk_tier="write_local"))
    reg.register(ToolSpec("remote_sync", "Cloud sync", {}, risk_tier="write_external", data_flows=("sync.cloud.com",)))
    reg.register(ToolSpec("read_allergies", "Read allergies", {}, risk_tier="read"))

    filtered = reg.list_for_profile("prof-kid-01", consents={"guardian_consent": True}, age_band="child_under_13")
    names = {t.name for t in filtered}

    assert "read_allergies" in names
    assert "local_vital" in names
    assert "remote_sync" not in names


def test_t1_f2_profile_tool_filtering_child_under_13_guardian_consent():
    """F2.5: Child under 13 requires guardian_consent for write_local tools."""
    reg = ToolSpecRegistry()
    reg.register(ToolSpec("save_symptom", "Save symptom", {}, risk_tier="write_local"))
    reg.register(ToolSpec("read_guidelines", "Read guide", {}, risk_tier="read"))

    # Without guardian consent: write_local filtered out
    no_consent = reg.list_for_profile("prof-kid-02", consents={"guardian_consent": False}, age_band="child_under_13")
    assert {t.name for t in no_consent} == {"read_guidelines"}

    # With guardian consent: write_local permitted
    with_consent = reg.list_for_profile("prof-kid-02", consents={"guardian_consent": True}, age_band="child_under_13")
    assert {t.name for t in with_consent} == {"read_guidelines", "save_symptom"}


def test_t1_f2_custom_toolspec_registration_and_retrieval():
    """F2.6: Registration, parameters mapping, and retrieval of custom connector tools."""
    reg = ToolSpecRegistry()
    spec = ToolSpec(
        name="epic_ehr_fhir_query",
        description="Query FHIR observations",
        parameters={"patient_id": {"type": "string"}},
        risk_tier="read",
        trust="untrusted",  # External EHR considered untrusted input
        data_flows=("fhir.epic.com",),
    )
    reg.register(spec)

    retrieved = reg.get("epic_ehr_fhir_query")
    assert retrieved is not None
    assert retrieved.name == "epic_ehr_fhir_query"
    assert retrieved.trust == "untrusted"
    assert retrieved.data_flows == ("fhir.epic.com",)


def test_t1_f2_toolspec_data_flows_egress_metadata():
    """F2.7: Verifies data_flows allowed_hosts tuple configuration on external tools."""
    spec = ToolSpec(
        name="quest_diagnostics_sync",
        description="Sync lab orders",
        risk_tier="write_external",
        data_flows=("api.questdiagnostics.com", "auth.questdiagnostics.com"),
    )
    assert len(spec.data_flows) == 2
    assert "api.questdiagnostics.com" in spec.data_flows
    assert "auth.questdiagnostics.com" in spec.data_flows
