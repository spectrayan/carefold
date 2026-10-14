# Legal & Regulatory Compliance Pack (`AU-65`)

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
**Owner**: Architecture Working Group (AWG), Clinical AI Reviewers & Core Maintainers  
**Status**: `Active (Autonomy Batch 7)`  

> [!NOTE]
> Carefold is an open-source software runtime for informational healthcare navigation, clinical visit preparation, and personal health record organization. It is **not** a covered healthcare provider or clinical medical device. Deployers operating hosted instances (`Mode S`) should review these templates with qualified legal counsel for their jurisdiction.

---

## 1. Versioned Consent Text Templates (`connector × profile × category × purpose`)

Every external connection in Carefold requires an explicit, versioned `ConsentGrant` (`AU-53`) stored in the `consent_grants` table before any OAuth token exchange, background sync, or remote MCP tool call can execute.

### 1.1 Canonical Consent Template (`terms_version = "1.0.0"`)

```text
CAREFOLD GRANULAR DATA CONNECTION CONSENT (v1.0.0)

Profile: {{profile_name}} ({{profile_id}})
Connector: {{connector_title}} ({{connector_id}} @ v{{connector_version}})
Authorized By: {{actor_username}} ({{actor_user_id}})
Data Categories: {{categories_csv}}
OAuth / API Scopes: {{scopes_csv}}
Allowed Outbound Hosts: {{allowed_hosts_csv}}
Permitted Purpose: {{purpose}}

By granting this consent, you authorize your Carefold runtime to connect to
{{allowed_hosts_csv}} solely for {{purpose}} on profile "{{profile_name}}".
1. Local-First Custody: Retrieved records and encrypted credentials are stored
   within your Carefold vault scoped strictly to profile {{profile_id}}.
2. Human-in-the-Loop Control: Irreversible external actions (such as sending
   an email) always require your explicit per-action approval.
3. Instant Revocation & Deletion: You may revoke this consent at any time in
   Settings -> Data Connections, which immediately deletes stored credentials
   and halts synchronization.
```

### 1.2 Purpose Definitions
- `read_only`: One-way ingestion or interactive lookup of clinical observations, wearable metrics, or calendar feeds (`SchoolIcsFeed`, `SMART-on-FHIR`, `Withings`).
- `sync_and_assist`: Bidirectional synchronization of consented categories plus local agent grounding for visit preparation and preventive care reminders.
- `calendar_write`: Creation or update of care appointments and preparation blocks on a consented external calendar (`google-calendar`, `caldav`).
- `approved_message_send`: User-initiated transmission of a reviewed local `EmailDraft` via `gmail_send_message` (`irreversible` tier; requires per-item `Approval`).

---

## 2. Consumer Health Data Privacy Policy (MHMDA & State Privacy Alignment)

In compliance with the **Washington My Health My Data Act (MHMDA)**, the **Nevada Consumer Health Data Privacy Law**, and similar consumer health privacy frameworks:

### 2.1 Categories of Consumer Health Data Processed
Depending on which features and connectors a user enables, Carefold processes:
- **Clinical & Diagnostic Records**: FHIR R4 `Observation`, `Condition`, `MedicationStatement`, `Immunization`, `AllergyIntolerance`, and uploaded C-CDA / PDF lab summaries.
- **Biometric & Wearable Physiological Measurements**: Blood pressure, heart rate, weight, body temperature, sleep stages, and SpO2 synchronized from user-authorized devices (`Withings`, `Apple Health` import, `iOS Companion`).
- **Care Navigation & Scheduling Metadata**: Clinical appointment dates, provider specialties, preventive screening due dates (`PreventiveRecord`), and school health form drafts (`SchoolForm`).

### 2.2 Sources of Consumer Health Data
- Direct user uploads and notes entered by the profile owner or authorized family caregiver.
- User-authorized external connectors (`epic-smart`, `withings`, `google-calendar`, `caldav`, `gmail-mcp`, `school_ics_feeds`) governed by active `ConsentGrant` records.

### 2.3 Zero Sale & Zero Unauthorized Sharing Invariant
- Carefold **never** sells, rents, or shares Consumer Health Data with third-party data brokers or advertising networks.
- Carefold contains **zero** third-party behavioral advertising SDKs or background telemetry beacons.
- Outbound network transmission occurs strictly when:
  1. Connecting to a user-configured LLM provider (or `127.0.0.1` local Ollama with zero external egress), or
  2. Executing a user-consented connector sync or approved MCP tool call against `ConsentGrant.allowed_hosts`.

---

## 3. Washington MHMDA Right-to-Withdraw & Right-to-Delete Mapping

MHMDA grants consumers the right to withdraw consent and the right to have their consumer health data permanently deleted across all storage layers. Carefold enforces these rights deterministically in code:

| Consumer Right | API Endpoint / UI Action | Deterministic Technical Enforcement (`Titan S2`) |
|---|---|---|
| **Right to Know / Inspect Data Flows** | `GET /api/v1/profiles/{profile_id}/data-flows` | Returns the complete per-profile provenance map: active `ConsentGrant` rows, outbound `allowed_hosts`, `SyncRun` history, and record counts per source. |
| **Right to Withdraw Consent** | `POST /api/v1/connections/{connection_id}/revoke` | Sets `ConsentGrant.status = "revoked"`, deletes vault `Credential` rows, disables standing `Routine` schedules, and records a chained `AuditEventRecord`. |
| **Right to Delete Consumer Health Data** | `DELETE /api/v1/profiles/{profile_id}` | Destroys per-profile AES-256-GCM keys (`ProfileKey` crypto-shredding), cascades SQL deletion across all profile-scoped tables, deletes partitioned CAS files on disk, and purges hybrid `SearchIndex` vectors/FTS rows. |

---

## 4. FTC Health Breach Notification Rule (HBNR) Incident Response Runbook

Because Carefold functions as a Personal Health Record (PHR) application and PHR-related runtime when deployed in hosted `Mode S` environments, operators must adhere to the **FTC Health Breach Notification Rule (16 CFR Part 318)** (as updated in 2024 to cover unauthorized disclosures of unsecured PHR identifiable health information).

### 4.1 Severity & Trigger Conditions
An HBNR-reportable breach occurs when **unsecured PHR identifiable health information** is acquired by an unauthorized person without the individual's authorization, or disclosed to an unauthorized third-party host outside `ConsentGrant.allowed_hosts`.
- *Safe Harbor Note*: Data encrypted at rest using Carefold's AES-256-GCM vault (`ADR-0005`) where the Master Key (KEK) and per-profile DEKs were not compromised qualifies as **secured** under NIST SP 800-111 / HHS guidance.

### 4.2 5-Phase Incident Response Protocol
1. **Triage & Containment (0–4 Hours)**:
   - Rotate `CAREFOLD_MASTER_KEY` and revoke active sessions (`DELETE FROM sessions`) and companion device tokens (`UPDATE companion_devices SET status = 'revoked'`).
   - Suspend external connector jobs (`UPDATE connections SET status = 'revoked'`).
2. **Forensic Chain Verification (4–24 Hours)**:
   - Execute `verify_profile_audit_chain(session, profile_id)` (`AU-78`) across all profiles to verify the integrity of the SHA-256 `audit_events` hash chain and identify any tampered records or unauthorized tool executions.
   - Inspect `SyncRun` and `AuditEventRecord` `external_ref` / `payload_hash` logs.
3. **Impact Assessment (24–72 Hours)**:
   - Determine affected `user_id` and `profile_id` partitions and whether plaintext PHI or unencrypted credentials were exposed.
4. **Mandatory Notifications (Within Statutory Deadlines)**:
   - **Affected Individuals**: Notify without unreasonable delay and **no later than 60 calendar days** after discovery of the breach via email/first-class mail.
   - **Federal Trade Commission (FTC)**:
     - If `>= 500` individuals are affected: Notify the FTC contemporaneously with individual notices (and no later than 60 calendar days after discovery).
     - If `< 500` individuals are affected: Log in the annual FTC breach summary submitted within 60 calendar days of the end of the calendar year.
   - **Media Notice**: If `>= 500` residents of a single state or jurisdiction are affected, notify prominent media outlets serving that jurisdiction.
5. **Post-Incident Hardening**:
   - Publish a security advisory (`SECURITY.md`) and regression test in `backend/tests/penetration_suite.py`.

---

## 5. COPPA & Pediatric Under-13 Verifiable Parental Consent Safeguards (`E11.6`)

Carefold supports family caregiving profiles, including pediatric profiles (`relationship == "child"`). To comply with the **Children's Online Privacy Protection Act (COPPA, 15 U.S.C. §§ 6501–6506)** and Carefold safety requirement `E11.6`:

1. **Age & Relationship Classification**:
   - Pediatric profiles (`date_of_birth` indicating age `< 13` years) are strictly managed under an authenticated adult parent/guardian account (`Profile.role == "owner"`).
2. **Guardian-Only External Connector Guard (`check_under_13_connection_guard`)**:
   - Enforced in `backend/src/carefold/connectors/lifecycle.py`:
     - Only the verified adult profile `owner` (parent/legal guardian) can create external `Connection` links, grant `ConsentGrant` permissions, or pair an `iOS CompanionDevice` for an under-13 profile.
     - Secondary `caregiver` or `viewer` delegates are blocked (`PermissionError` / `403 Forbidden`) from attaching external cloud connectors or authorizing third-party data flows on an under-13 profile.
3. **Read-Only School Calendar Feeds (`AU-61`)**:
   - Pediatric school calendar integration (`SchoolIcsFeed`) is strictly one-way (`read-only` `.ics` ingestion) and never transmits child identity or health data back to the school server.
4. **Parental Inspection & Deletion Rights**:
   - Parents/guardians can review all child profile data, revoke any connector consent immediately, or delete the child profile with full cryptographic erasure at any time.
