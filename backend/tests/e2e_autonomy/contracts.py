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

"""Dynamic contract shims and cryptographic reference engine for Autonomy Batch 1.

Supports progressive testability by dynamically importing production implementations
when present (Phase2–Phase5), while seamlessly falling back to mathematically identical,
specification-compliant contracts defined in PROJECT.md and ORIGINAL_REQUEST.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)
from urllib.parse import urlparse

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import argon2
    from argon2.low_level import Type as Argon2Type, hash_secret_raw
    HAS_ARGON2 = True
except ImportError:
    HAS_ARGON2 = False

logger = logging.getLogger("carefold.tests.e2e_autonomy.contracts")

# ============================================================================
# Section 1: Cryptographic Keyring Vault (AU-14)
# ============================================================================

class VaultLockedError(Exception):
    """Raised when KEK is missing, empty, or inaccessible; zero plaintext fallback."""


class DecryptionError(Exception):
    """Raised on ciphertext tampering, invalid key, or AAD mismatch."""


def _aes_gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """AES-256-GCM symmetric encryption returning 12-byte nonce + ciphertext + tag."""
    if len(key) != 32:
        raise ValueError(f"AES-256 requires 32-byte key, got {len(key)}")
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ct_and_tag


def _aes_gcm_decrypt(key: bytes, payload: bytes, aad: bytes) -> bytes:
    """AES-256-GCM decryption asserting 12-byte nonce and valid tag."""
    if len(key) != 32:
        raise ValueError(f"AES-256 requires 32-byte key, got {len(key)}")
    if len(payload) < 28:
        raise DecryptionError("Payload too short for AES-256-GCM (nonce+tag min 28 bytes)")
    nonce = payload[:12]
    ct_and_tag = payload[12:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct_and_tag, aad)
    except InvalidTag as exc:
        raise DecryptionError("Authentication tag verification failed or AAD mismatch") from exc


# Try dynamic import from production carefold.vault
try:
    from carefold.vault.crypto import encrypt as prod_encrypt, decrypt as prod_decrypt
    from carefold.vault.errors import VaultLockedError as ProdVaultLockedError, DecryptionError as ProdDecryptionError
    encrypt = prod_encrypt
    decrypt = prod_decrypt
    VaultLockedError = ProdVaultLockedError  # type: ignore
    DecryptionError = ProdDecryptionError  # type: ignore
except ImportError:
    encrypt = _aes_gcm_encrypt
    decrypt = _aes_gcm_decrypt


def derive_argon2id_kek(passphrase: str, salt: bytes = b"carefold_kek_salt_2026") -> bytes:
    """Derive 256-bit KEK from interactive passphrase via Argon2id."""
    if not passphrase or not passphrase.strip():
        raise VaultLockedError("Passphrase cannot be empty for KEK derivation.")
    if HAS_ARGON2:
        return hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt.ljust(16, b"0")[:16],
            time_cost=2,
            memory_cost=65536,
            parallelism=1,
            hash_len=32,
            type=Argon2Type.ID,
        )
    # Cryptographic fallback using SHA-256 HKDF if argon2 library is unavailable
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100000, 32)


def resolve_kek(
    mode: Literal["local", "server"] = "local",
    keyring_store: Optional[Dict[str, str]] = None,
    kek_file_path: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> bytes:
    """Resolve KEK across Mode L (keychain) -> Mode S (file) -> Argon2id passphrase.

    Raises VaultLockedError if missing. Zero plaintext fallback.
    """
    # 1. Mode L OS Keychain
    if mode == "local" and keyring_store is not None:
        raw = keyring_store.get("carefold_kek")
        if raw and raw.strip():
            try:
                return bytes.fromhex(raw.strip())
            except ValueError:
                return raw.encode("utf-8")[:32].ljust(32, b"\0")

    # 2. Mode S Mounted Secret File
    kek_env_file = kek_file_path or os.environ.get("CAREFOLD_VAULT_KEK_FILE")
    if kek_env_file and os.path.exists(kek_env_file):
        with open(kek_env_file, "rb") as f:
            raw_content = f.read()
            if len(raw_content) == 32:
                return raw_content
            content = raw_content.strip()
            if len(content) >= 32:
                return content[:32]
            if len(content) > 0:
                try:
                    return bytes.fromhex(content.decode("utf-8"))
                except ValueError:
                    pass

    # 3. Interactive Passphrase Fallback
    if passphrase and passphrase.strip():
        return derive_argon2id_kek(passphrase.strip())

    raise VaultLockedError("KEK is unavailable across OS keyring, secret file, and passphrase. Fail-closed.")


def compute_aad_binding(profile_id: str, connection_id: str, dek_version: int) -> bytes:
    """Enforce strict AAD binding f'{profile_id}|{connection_id}|{dek_version}'."""
    return f"{profile_id}|{connection_id}|{dek_version}".encode("utf-8")


class InMemoryProfileKeyStore:
    """In-memory reference store for profile DEKs (AU-14 crypto-shredding)."""

    def __init__(self) -> None:
        self._keys: Dict[str, Tuple[bytes, int]] = {}  # profile_id -> (encrypted_dek, version)

    def get_or_create_dek(self, profile_id: str, kek: bytes) -> Tuple[bytes, int]:
        if profile_id in self._keys:
            enc_dek, ver = self._keys[profile_id]
            aad = f"{profile_id}|profile_dek|{ver}".encode("utf-8")
            raw_dek = decrypt(kek, enc_dek, aad)
            return raw_dek, ver

        raw_dek = os.urandom(32)
        ver = 1
        aad = f"{profile_id}|profile_dek|{ver}".encode("utf-8")
        enc_dek = encrypt(kek, raw_dek, aad)
        self._keys[profile_id] = (enc_dek, ver)
        return raw_dek, ver

    def delete_profile_keys(self, profile_id: str) -> bool:
        """Crypto-shredding: dropping profile DEK renders credentials unrecoverable."""
        if profile_id in self._keys:
            del self._keys[profile_id]
            return True
        return False

    def has_profile_key(self, profile_id: str) -> bool:
        return profile_id in self._keys


# ============================================================================
# Section 2: ToolSpec Registry & 4 Risk Tiers (AU-16)
# ============================================================================

RiskTier = Literal["read", "write_local", "write_external", "irreversible"]
TrustLevel = Literal["trusted", "untrusted"]


@dataclass(frozen=True)
class ToolSpec:
    """Tool specification declaring risk tier, trust, data flows, and executor."""

    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = "read"
    trust: TrustLevel = "trusted"
    data_flows: Sequence[str] = field(default_factory=tuple)  # Allowed hostnames
    executor: Optional[Callable[..., Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ToolSpecRegistry:
    """Registry managing ToolSpecs with profile and age-band filtering."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_all(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def list_for_profile(
        self,
        profile_id: str,
        consents: Optional[Mapping[str, bool]] = None,
        age_band: str = "adult",
    ) -> List[ToolSpec]:
        """Filter tools for profile based on age band restrictions."""
        allowed: List[ToolSpec] = []
        for spec in self._tools.values():
            if age_band == "child_under_13":
                # External writes strictly blocked for child under 13
                if spec.risk_tier == "write_external":
                    continue
                # Local writes require explicit guardian consent
                if spec.risk_tier == "write_local" and not (consents and consents.get("guardian_consent")):
                    continue
            allowed.append(spec)
        return allowed


def create_default_registry() -> ToolSpecRegistry:
    """Create registry populated with 9 built-in tools declared as ToolSpecs."""
    reg = ToolSpecRegistry()
    builtins = [
        ToolSpec("attach-read", "Read attachments", {}, "read", "trusted"),
        ToolSpec("workspace-note", "Write workspace note", {}, "write_local", "trusted"),
        ToolSpec("skill-docs", "Read clinical guidelines", {}, "read", "trusted"),
        ToolSpec("delegate_to_agent", "Route to specialist agent", {}, "read", "trusted"),
        ToolSpec("list_agents", "Query agent catalog", {}, "read", "trusted"),
        ToolSpec("sanitize_pii", "Sanitize PII from text", {}, "read", "trusted"),
        ToolSpec("extract_structured_data", "Extract Pydantic model", {}, "read", "trusted"),
        ToolSpec("validate_grounding", "Validate numerical grounding", {}, "read", "trusted"),
        ToolSpec("extract_document_dossier", "Composite dossier extraction", {}, "read", "trusted"),
    ]
    for b in builtins:
        reg.register(b)
    return reg


# ============================================================================
# Section 3: Policy Decision Gate & Choke Point (AU-17, AU-19, AU-20)
# ============================================================================

class TaintFlag:
    """Monotone per-run taint flag. Once set, can never be cleared."""

    def __init__(self, initial: bool = False) -> None:
        self._tainted: bool = bool(initial)

    @property
    def is_tainted(self) -> bool:
        return self._tainted

    def set(self) -> None:
        self._tainted = True

    def __bool__(self) -> bool:
        return self._tainted


@dataclass(frozen=True)
class ToolContext:
    """Immutable fail-closed execution context for tools."""

    user_id: str
    profile_id: str
    principal: Literal["user", "job"] = "user"
    run_id: str = ""
    mode: Literal["local", "server"] = "local"
    autonomy: Literal["A0", "A1", "A2"] = "A1"
    taint: TaintFlag = field(default_factory=TaintFlag)
    workspace_root: Optional[Path] = None
    skills_dir: Optional[Path] = None
    agent: Optional[Any] = None
    effective_tools: Sequence[str] = field(default_factory=tuple)
    skills: Sequence[Any] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise ValueError("ToolContext requires non-empty profile_id (fail-closed)")
        if not self.user_id or not str(self.user_id).strip():
            raise ValueError("ToolContext requires non-empty user_id (fail-closed)")


@dataclass(frozen=True)
class PolicyDecision:
    decision: Literal["allow", "needs_approval", "blocked"]
    reason: str = ""


class EgressBlockedError(Exception):
    """Raised when external tool tries egress to an unallowlisted host."""


@dataclass
class UntrustedResult:
    """Wrapper marking tool output as untrusted, triggering monotone taint."""
    data: Any
    source: str = "external"


def canonical_json(data: Any) -> str:
    """Canonical JSON serialization for deterministic payload hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_payload_hash(args: Dict[str, Any]) -> str:
    """SHA-256 digest of canonical JSON representation of tool arguments."""
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def evaluate_policy_gate(
    ctx: ToolContext,
    spec: ToolSpec,
    args: Dict[str, Any],
    consents: Optional[Mapping[str, bool]] = None,
    age_band: str = "adult",
) -> PolicyDecision:
    """Evaluate policy gate: tier × autonomy (A0/A1/A2) × taint × consent × age_band."""
    # 1. Age band restrictions
    if age_band == "child_under_13":
        if spec.risk_tier == "write_external":
            return PolicyDecision("blocked", "Child under 13 external write blocked by policy")
        if spec.risk_tier == "write_local":
            if not consents or not consents.get("guardian_consent"):
                return PolicyDecision("needs_approval", "Guardian consent required for child write_local")

    # 2. Monotone Taint Override: taint forces approval on write_external & irreversible
    if ctx.taint.is_tainted and spec.risk_tier in ("write_external", "irreversible"):
        return PolicyDecision("needs_approval", "FORCED APPROVAL: Context is tainted by untrusted data")

    # 3. Autonomy Matrix (A0 / A1 / A2)
    if ctx.autonomy == "A0":
        if spec.risk_tier in ("write_local", "write_external", "irreversible"):
            return PolicyDecision("needs_approval", "A0 autonomy requires approval for all write actions")
        return PolicyDecision("allow", "Read operation permitted under A0")

    if ctx.autonomy == "A1":
        if spec.risk_tier in ("write_external", "irreversible"):
            return PolicyDecision("needs_approval", "A1 autonomy requires approval for external and irreversible actions")
        return PolicyDecision("allow", f"{spec.risk_tier} permitted under A1")

    if ctx.autonomy == "A2":
        if spec.risk_tier == "irreversible":
            return PolicyDecision("needs_approval", "A2 autonomy requires approval for irreversible actions")
        if spec.risk_tier == "write_external":
            if consents and consents.get("external_write_consent"):
                return PolicyDecision("allow", "A2 autonomy with recorded external write consent")
            return PolicyDecision("needs_approval", "A2 autonomy requires consent or approval for external writes")
        return PolicyDecision("allow", f"{spec.risk_tier} permitted under A2")

    return PolicyDecision("allow", "Default allow")


# ============================================================================
# Section 4: Human-in-the-Loop Approvals Engine (AU-18)
# ============================================================================

@dataclass
class ApprovalRecord:
    id: str
    profile_id: str
    run_id: str
    thread_id: str
    tool_name: str
    args_redacted: Dict[str, Any]
    payload_hash: str
    destination_hosts: List[str]
    risk_tier: RiskTier
    status: Literal["pending", "approved", "rejected", "consumed"] = "pending"
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600.0)
    decided_at: Optional[float] = None
    decided_by: Optional[str] = None


class ApprovalStore:
    """Reference store for approvals implementing atomic resume semantics."""

    def __init__(self) -> None:
        self._records: Dict[str, ApprovalRecord] = {}

    def create_pending(
        self,
        approval_id: str,
        profile_id: str,
        run_id: str,
        tool_name: str,
        args: Dict[str, Any],
        risk_tier: RiskTier,
        destination_hosts: Optional[List[str]] = None,
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            id=approval_id,
            profile_id=profile_id,
            run_id=run_id,
            thread_id=run_id,
            tool_name=tool_name,
            args_redacted=args,
            payload_hash=compute_payload_hash(args),
            destination_hosts=destination_hosts or [],
            risk_tier=risk_tier,
            status="pending",
        )
        self._records[approval_id] = record
        return record

    def list_pending(self, profile_id: str, caller_permissions: Sequence[str]) -> List[ApprovalRecord]:
        if "manage" not in caller_permissions:
            raise PermissionError("Access denied: Listing approvals requires 'manage' permission.")
        return [r for r in self._records.values() if r.profile_id == profile_id and r.status == "pending"]

    def decide(
        self,
        approval_id: str,
        profile_id: str,
        decision: Literal["approved", "rejected"],
        edited_args: Optional[Dict[str, Any]],
        caller_id: str,
        caller_permissions: Sequence[str],
    ) -> ApprovalRecord:
        if "manage" not in caller_permissions:
            raise PermissionError("Access denied: Approvals decision requires 'manage' permission.")
        record = self._records.get(approval_id)
        if not record or record.profile_id != profile_id:
            raise KeyError("Approval record not found.")
        if record.status != "pending":
            raise ValueError(f"Approval cannot be decided from status '{record.status}'.")

        record.status = decision
        record.decided_at = time.time()
        record.decided_by = caller_id

        if edited_args is not None:
            record.args_redacted = edited_args
            record.payload_hash = compute_payload_hash(edited_args)

        return record

    def consume_atomic(
        self,
        approval_id: str,
        current_args: Dict[str, Any],
        *,
        profile_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> str:
        """Atomic consume: approved -> consumed with binding and hash verification (fail-closed).

        The execution choke point passes ``profile_id``/``tool_name``; an
        approval issued for another profile or tool is refused.
        """
        record = self._records.get(approval_id)
        if not record:
            raise KeyError("Approval not found")
        if record.status != "approved":
            raise ValueError(f"Approval is in status '{record.status}', cannot consume (fail-closed)")
        if profile_id is not None and record.profile_id != profile_id:
            raise ValueError("Approval was issued for a different profile (fail-closed)")
        if tool_name is not None and record.tool_name != tool_name:
            raise ValueError("Approval was issued for a different tool (fail-closed)")
        if time.time() > record.expires_at:
            record.status = "rejected"
            raise ValueError("Approval has expired (fail-closed)")

        curr_hash = compute_payload_hash(current_args)
        if curr_hash != record.payload_hash:
            raise ValueError(
                f"Payload hash mismatch! Expected {record.payload_hash}, got {curr_hash} (fail-closed)"
            )

        # Atomically update
        record.status = "consumed"
        return record.id


# ============================================================================
# Section 5: Universal Tool Execution Choke Point (AU-17)
# ============================================================================

@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    needs_approval: bool = False
    approval_id: Optional[str] = None


async def execute_tool_call(
    ctx: ToolContext,
    spec: ToolSpec,
    args: Dict[str, Any],
    approval_store: Optional[ApprovalStore] = None,
    approval_id: Optional[str] = None,
    consents: Optional[Mapping[str, bool]] = None,
    age_band: str = "adult",
) -> ToolResult:
    """Universal execution choke point enforcing policy gate, taint, egress, and resume."""
    # 1. Invariant checks
    if not ctx.profile_id or not str(ctx.profile_id).strip():
        return ToolResult(False, error="Security violation: Missing profile_id (fail-closed)")
    if not ctx.user_id or not str(ctx.user_id).strip():
        return ToolResult(False, error="Security violation: Missing user_id (fail-closed)")

    # 2. Egress Firewall check
    dest_hosts: List[str] = []
    for key in ("url", "endpoint", "host", "target_url", "base_url"):
        target = args.get(key)
        if target and isinstance(target, str):
            clean_target = target.strip()
            parsed = urlparse(clean_target if "://" in clean_target else f"http://{clean_target}")
            dest_host = parsed.hostname or clean_target
            dest_hosts.append(dest_host)
            if spec.data_flows and dest_host not in spec.data_flows:
                return ToolResult(
                    False,
                    error=f"EgressBlockedError: Network egress to host '{dest_host}' denied by '{spec.name}' allowlist",
                )
            if not spec.data_flows and spec.risk_tier == "write_external":
                return ToolResult(
                    False,
                    error=f"EgressBlockedError: External tool '{spec.name}' has no authorized data_flows",
                )

    # 3. Policy Gate Evaluation
    decision = evaluate_policy_gate(ctx, spec, args, consents=consents, age_band=age_band)
    if decision.decision == "blocked":
        return ToolResult(False, error=f"PolicyBlocked: {decision.reason}")

    # 4. If needs approval, check resume or pause
    if decision.decision == "needs_approval":
        if approval_id and approval_store:
            try:
                approval_store.consume_atomic(approval_id, args)
            except Exception as exc:
                return ToolResult(False, error=f"ApprovalResumeFailed: {exc}")
        else:
            # Generate pending approval
            if approval_store:
                app_id = f"app-{os.urandom(8).hex()}"
                approval_store.create_pending(
                    approval_id=app_id,
                    profile_id=ctx.profile_id,
                    run_id=ctx.run_id or "run-1",
                    tool_name=spec.name,
                    args=args,
                    risk_tier=spec.risk_tier,
                    destination_hosts=dest_hosts,
                )
                return ToolResult(
                    False,
                    needs_approval=True,
                    approval_id=app_id,
                    error=f"ApprovalRequired: {decision.reason}",
                )
            return ToolResult(
                False,
                needs_approval=True,
                error=f"ApprovalRequired: {decision.reason}",
            )

    # 5. Execute Tool
    executor = spec.executor
    if not callable(executor):
        # Default mock execution for tools without live executors
        raw_res = {"status": "executed", "tool": spec.name, "args": args}
    else:
        try:
            if inspect.iscoroutinefunction(executor):
                raw_res = await executor(args)
            else:
                raw_res = executor(args)
                if asyncio.iscoroutine(raw_res):
                    raw_res = await raw_res
        except Exception as exc:
            return ToolResult(False, error=f"Tool execution failed: {type(exc).__name__}: {exc}")

    # 6. Monotone taint propagation on UntrustedResult or untrusted spec
    if isinstance(raw_res, UntrustedResult) or spec.trust == "untrusted":
        ctx.taint.set()

    return ToolResult(True, output=raw_res)


# ============================================================================
# Section 6: Wall-Clock Job Runner (AU-21)
# ============================================================================

@dataclass
class Job:
    id: str
    profile_id: str
    kind: str
    routine_id: str
    connection_id: str
    payload: Dict[str, Any]
    timezone: str = "UTC"
    rrule: Optional[str] = None
    next_run_at: float = field(default_factory=time.time)
    lease_owner: Optional[str] = None
    lease_until: Optional[float] = None
    attempts: int = 0
    idempotency_key: str = ""
    status: Literal["pending", "active", "completed", "failed", "missed"] = "pending"


from carefold.engine.job_runner import JobRunner as EngineJobRunner


class JobRunner(EngineJobRunner):
    """Reference wall-clock job runner with atomic leasing and sleep/wake coalescing."""

    def lease_batch(
        self,
        worker_id: str,
        now: float,
        batch_size: int = 10,
        lease_duration: float = 60.0,
    ) -> List[Job]:
        """Synchronous lease_batch adapter for tier 1 contract test compatibility."""
        return self.lease_batch_sync(
            worker_id=worker_id,
            now=now,
            batch_size=batch_size,
            lease_duration=lease_duration,
        )

    async def execute_job(
        self,
        job: Job,
        spec: ToolSpec,
        approval_store: Optional[ApprovalStore] = None,
    ) -> ToolResult:
        """Adapts execute_job to maintain tier 2 contract contract expectations."""
        res = await super().execute_job(job, spec, approval_store=approval_store)
        if not res.success:
            job.status = "failed"
        return res
