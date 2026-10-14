# Google OAuth Verification & OWASP ASVS / CASA Tier 2/3 Readiness Pack (`AU-64`)

<!--
  Carefold — Healthcare AI Agent Marketplace & Runtime
  Copyright 2026 Spectrayan

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

**Document Version**: `1.0.0`  
**Owner**: Architecture Working Group (AWG) & Carefold Core Maintainers  
**Status**: `Verified & Enforced (Autonomy Batch 7)`  

---

## 1. Executive Overview

This compliance pack documents Carefold's engineering controls, least-privilege OAuth scope justifications, data retention/deletion architecture (`Titan S2`), and OWASP Application Security Verification Standard (ASVS) / Cloud Application Security Assessment (CASA) Tier 2/3 readiness for Google Workspace (`Gmail` and `Google Calendar`) integrations.

Carefold is an open-source, local-first healthcare AI agent runtime. All patient health records, email drafts, calendar events, and encrypted OAuth credentials reside in the user's self-controlled database and envelope-encrypted vault (`ADR-0005`).

---

## 2. BYO OAuth Credentials vs. Bundled OAuth Client Separation

Carefold strictly separates **Bring-Your-Own (BYO) OAuth Client Mode** from **Verified Bundled Client Mode**:

| Dimension | Mode L: Local BYO Client (Default) | Mode S / Verified Companion Client |
|---|---|---|
| **Client ID & Secret Source** | User supplies their own Google Cloud Console OAuth 2.0 Desktop/Web Client ID in local settings. | Verified OAuth Client registered under CASA Tier 2/3 assessment. |
| **Token Custody** | Stored exclusively in local `credentials` table encrypted under per-profile AES-256-GCM DEK (`ADR-0005`). | Stored exclusively in the instance's `credentials` vault under per-profile AES-256-GCM DEK; zero tokens stored on any relay (`ADR-0008`). |
| **PKCE Enforcement** | Mandatory `S256` (`RFC 7636`) with 64-character high-entropy verifier. | Mandatory `S256` (`RFC 7636`) with stateless HMAC-sealed callback bounce (`<= 120s` TTL). |
| **Tool Pinning (`Titan S7`)** | Remote MCP tools pinned via `McpToolPin` SHA-256 canonical schema digest (`AU-57`). | Remote MCP tools pinned via `McpToolPin`; drift triggers `409 Conflict` (`drift_blocked`). |

---

## 3. Google OAuth 2.0 Scope Justifications (Least-Privilege Matrix)

Carefold requests incremental, feature-scoped permissions via `ConsentGrant` (`AU-53`) only when a user explicitly links a Google connector to a care profile.

| Scope URI | Classification | Carefold Feature & Tool Mapping | Mandatory Runtime Guardrails |
|---|---|---|---|
| `https://www.googleapis.com/auth/calendar.events` | Sensitive | **Google Calendar Connector (`google-calendar`)**: Synchronizes clinical appointments (`Appointment`) and care preparation reminders (`Reminder`) for the consented profile. | Scoped to a dedicated or user-selected calendar; read/write operations logged in tamper-evident `audit_events` hash chain (`AU-78`). |
| `https://www.googleapis.com/auth/gmail.readonly` | Restricted | **Curated Gmail MCP Read Tools (`gmail_search_messages`, `gmail_get_thread`)**: Locates clinical appointment confirmations, lab notification emails, and insurance correspondence for user-initiated queries. | Query strings and message bodies pass through `sanitize_pii` and untrusted content boundary fencing (`<untrusted_external_content>`); never used for background training or third-party analytics. |
| `https://www.googleapis.com/auth/gmail.send` | Restricted | **Curated Gmail MCP Send Tool (`gmail_send_message`, `AU-60`)**: Sends a user-reviewed local `EmailDraft` (e.g., medical records request or school health form cover note). | Classified as **`irreversible` risk tier**. Always halts execution and requires a per-invocation, single-use human `Approval` (`payload_hash` bound to exact recipient, subject, and body) even when profile/connector autonomy is set to `A2`. |

> [!IMPORTANT]
> Carefold **never** requests broad `https://mail.google.com/` full-mailbox access or `gmail.modify` deletion scopes. Local email drafting (`draft_care_email`) operates offline against the `email_drafts` table with zero Google scopes required.

---

## 4. Data Retention, Revocation & Crypto-Shredding Cascade (`Titan S2`)

In accordance with Google API Services User Data Policy ("Limited Use" requirements) and `Titan S2`:

1. **Connector Revocation (`POST /api/v1/connections/{id}/revoke`)**:
   - Immediately transitions `Connection.status` to `revoked`.
   - Deletes all associated `Credential` rows (`access_token`, `refresh_token`) from the vault.
   - Marks all associated `ConsentGrant` records `revoked` with `revoked_at` UTC timestamp.
   - Revokes any active standing `Routine` (`AU-58`) and `McpToolPin` (`AU-57`) bound to the connection.
2. **Profile Deletion & Crypto-Shredding (`DELETE /api/v1/profiles/{id}`)**:
   - Destroys all `ProfileKey` AES-256-GCM Data Encryption Keys (DEKs), rendering any historical ciphertext permanently unrecoverable (`ADR-0005`).
   - Cascades deletion across `connections`, `credentials`, `consent_grants`, `sync_runs`, `health_resources`, `appointments`, `reminders`, `email_drafts`, `school_ics_feeds`, `companion_devices`, and partitioned CAS files (`<carefold_home>/data/files/<user_id>/<profile_id>/`).
   - Purges the profile's hybrid `SearchIndex` chunks (`SearchIndex.purge_profile()`).

---

## 5. OWASP ASVS v4.0.3 / CASA Tier 2 & Tier 3 Control Mapping

| ASVS / CASA Control Area | Requirement Summary | Carefold Implementation & Verification Evidence |
|---|---|---|
| **V2: Authentication** | Argon2id password hashing, constant-time token verification, session expiration. | `User.hashed_password` uses Argon2id; sessions store SHA-256 digest in `sessions` table; companion tokens use SHA-256 digest + pinned TLS fingerprint (`AU-62`). |
| **V3: Session Management** | High-entropy tokens, CSRF protection, short-lived OAuth state/relay tickets. | `create_oauth_state` (`AU-51`) and `create_relay_ticket` (`AU-70`, `<= 120s` TTL + single-use `nonce`) signed with `HMAC-SHA256` and verified via `hmac.compare_digest`. |
| **V4: Access Control** | Fail-closed tenant/profile isolation (`owner`, `caregiver`, `viewer`). | Every API route and tool enforces profile RBAC (`ADR-0007`); Under-13 profiles enforce guardian-only external connector guard (`E11.6`). |
| **V6: Stored Cryptography** | Envelope encryption with authenticated AAD binding and key rotation. | `carefold.vault` (`ADR-0005`) encrypts credentials with AES-256-GCM using `aad_binding = carefold:p:{profile_id}:c:{connection_id}` and `dek_version` rotation. |
| **V7: Error Handling & Auditing** | Tamper-evident audit logging with zero-body PHI redaction by default. | `carefold.audit.hash_chain` (`AU-78`) links each `AuditEventRecord` via `prev_hash` and `entry_hash` (`SHA-256` chain from `GENESIS`) with automated chain verification. |
| **V8: Data Protection** | Zero-mock local-first privacy, PII sanitization, CAS partition isolation. | `sanitize_pii` redacts SSN/MRN/phone/address; CAS files isolated per `(user_id, profile_id)` (`ADR-0007`). |
| **V10: Malicious Code & Supply Chain** | Remote MCP tool schema pinning (`Titan S7`) and CodeQL static analysis. | `McpToolPin` computes SHA-256 over canonical `(name, description, inputSchema)` and blocks tool execution on upstream schema drift (`drift_blocked`). |
| **V13: API & Web Service** | SSRF defense, DNS pinning, and strict outbound host allowlisting. | Connector and ICS clients validate HTTPS schemes, block RFC 1918 / loopback / link-local IPs on external fetches, and enforce `ConsentGrant.allowed_hosts`. |
