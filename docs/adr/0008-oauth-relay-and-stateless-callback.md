# ADR-0008: Stateless OAuth 2.0 PKCE Callback Bounce Relay & Zero-Token Handoff

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

## Metadata

| Property | Value |
|---|---|
| **Status** | `Accepted (Implemented)` |
| **Date** | 2026-10-14 |
| **Authors** | Architecture Working Group (`architecture@spectrayan.com`) |
| **Deciders** | Carefold Core Maintainers, Clinical AI Reviewers |
| **Consulted** | Technical Lead & TSC Chair, Security Engineering Team |
| **Informed** | Carefold Open-Source Community |
| **Upstream Core ADR** | [Yarvelle Core ADR-0010](https://yarvelle.github.io/yarvelle-core/adr/0010-oauth-relay-and-stateless-callback/) — [Core ADR-0002 (Dynamic MCP DB Toolbox)](https://yarvelle.github.io/yarvelle-core/adr/0002-dynamic-mcp-db-toolbox/) |
| **Related** | ADR-0005 (Vault Threat Model), ADR-0006 (Deployment Modes & Requirement Tiers), AU-51 (OAuth 2.0 PKCE Broker), AU-70 (Stateless PKCE OAuth Relay) |

---

## Context & Problem Statement

Carefold supports both local-first desktop/workstation deployments (`Mode L`, bound to `127.0.0.1`) and self-hosted server deployments (`Mode S`), alongside paired iOS companion devices (`AU-62`). Many healthcare, wearable, and productivity OAuth 2.0 providers (including Withings Health Cloud, Garmin Health, Oura Cloud, and certain SMART-on-FHIR EHR sandboxes) enforce strict HTTPS redirect URI allowlists and reject arbitrary dynamic loopback ports or custom URI schemes during authorization registration.

At the same time, Carefold's core privacy invariant requires that **no third-party or cloud relay service ever possess, exchange, inspect, or persist patient OAuth access tokens, refresh tokens, or Protected Health Information (PHI)**.

We need an OAuth 2.0 callback mechanism (`AU-70`) that:
1. Satisfies upstream OAuth 2.0 providers requiring a fixed, registered redirect endpoint.
2. Preserves end-to-end RFC 7636 Proof Key for Code Exchange (`PKCE` `S256`) where the `code_verifier` never leaves the user's local Carefold runtime.
3. Operates **100% statelessly** with respect to credentials and PHI—never exchanging the authorization code and never writing tokens or patient identifiers to relay disk or database storage.
4. Prevents open-redirect abuse, authorization code interception, CSRF state fixation, and replay attacks.

---

## Decision Drivers

- **Zero Token & Zero PHI Custody on Relay**: The relay acts strictly as an HTTP 302 bounce endpoint for the opaque OAuth `code` and signed `state` ticket. Token exchange (`POST /oauth/token` with `code_verifier`) happens exclusively inside the user's local Carefold instance.
- **Cryptographic State Authenticity**: The relay ticket must be sealed with `HMAC-SHA256` and verified in constant time (`hmac.compare_digest`) before any redirect target is constructed.
- **Strict Loopback & Companion Scheme Allowlisting**: Redirect targets inside a relay ticket must be restricted to RFC 8252 loopback (`http://127.0.0.1:<port>/...`) or the Carefold companion deep-link scheme (`carefold://...`). Arbitrary external domains (`https://evil.example/...`) must be rejected at both ticket issuance and callback resolution.
- **Short-Lived Replay Window (`<= 120s` TTL)**: Relay tickets must expire within 120 seconds (`MAX_RELAY_TICKET_TTL_SECONDS = 120`) and include a single-use cryptographic `nonce` to block replay attacks.

---

## Considered Options

### Option 1: Stateful Cloud Token Broker Proxy
* **Description**: The cloud relay exchanges the authorization `code` for access/refresh tokens using a shared client secret and transmits the tokens back to the local Carefold client over a polling channel.
* **Pros**: Hides client secrets for confidential OAuth clients.
* **Cons**: Violates Carefold's local-first zero-custody privacy boundary. A compromise of the cloud broker would expose user OAuth tokens and enable unauthorized access to health records.

### Option 2: Manual Copy-Paste Out-of-Band (OOB) Authorization Code Flow
* **Description**: Users copy an authorization code from the browser and paste it into the Carefold UI.
* **Pros**: Zero redirect infrastructure needed.
* **Cons**: Deprecated and blocked by Google OAuth 2.0 (`urn:ietf:wg:oauth:2.0:oob` sunset) and modern SMART-on-FHIR providers due to phishing risks.

### Option 3: Stateless PKCE OAuth Callback Bounce Relay with HMAC-Signed Short-TTL Tickets (Selected)
* **Description**: The local Carefold runtime generates the PKCE `(code_verifier, code_challenge)` pair, stores `code_verifier` locally, and seals a short-lived (`<= 120s`) HMAC-SHA256 relay ticket binding `(user_id, profile_id, connection_id, loopback_callback_url, nonce, iat, exp)`. When the OAuth provider redirects to the relay with `?code=...&state=<relay_ticket>`, the stateless relay validates the HMAC signature, TTL, nonce, and loopback/companion target scheme, and immediately returns an HTTP 302 redirect (`{loopback_callback_url}?code={authorization_code}&state={relay_ticket}`) to the user's browser without ever touching the token endpoint.
* **Pros**:
  - Zero token or PHI storage on the relay (`stateless: True`, `tokens_stored: False`).
  - Even if an adversary observes the authorization `code` in transit at the bounce layer, it is useless without the `code_verifier` held exclusively inside the local Carefold runtime.
  - Constant-time HMAC verification and strict target scheme allowlisting prevent open-redirect vulnerabilities.
* **Cons**: Requires the user's browser to reach the local loopback listener (`http://127.0.0.1:<port>`) or companion app (`carefold://`) upon receiving the 302 redirect.

---

## Decision Outcome

**Chosen Option**: **Option 3: Stateless PKCE OAuth Callback Bounce Relay with HMAC-Signed Short-TTL Tickets**

### 1. Relay Ticket Format & Cryptographic Binding

`create_relay_ticket()` in `backend/src/carefold/connectors/relay.py` constructs a compact, URL-safe signed ticket:

$$\text{RelayTicket} = \text{Base64URL}(\text{CanonicalJSON}(\text{Payload})) \mathbin{\Vert} \text{"."} \mathbin{\Vert} \text{Hex}(\text{HMAC-SHA256}(K, \text{Base64URL}(\text{Payload})))$$

Where the canonical JSON payload binds:
- `v`: Protocol version (`1`)
- `uid`: Initiating `user_id`
- `pid`: Scoped `profile_id`
- `cid`: Bound `connection_id`
- `cb`: Validated `loopback_callback_url` (`http://127.0.0.1:<port>/...` or `carefold://...`)
- `nonce`: 128-bit cryptographic random hex nonce (`secrets.token_hex(16)`)
- `iat`: Issuance UNIX timestamp (seconds)
- `exp`: Expiration UNIX timestamp (`iat + ttl_seconds`, where `1 <= ttl_seconds <= 120`)

### 2. Callback Verification & Bounce Resolution

`resolve_stateless_relay_callback()` enforces six sequential fail-closed checks:
1. **Non-Empty Code & Ticket**: Rejects missing or whitespace `relay_ticket` or `authorization_code`.
2. **Constant-Time HMAC Verification**: Recomputes HMAC-SHA256 over the base64url payload segment and verifies via `hmac.compare_digest()`.
3. **Strict TTL & Expiry Check**: Rejects tickets where `exp < now` or `(exp - iat) > 120`.
4. **Single-Use Nonce Replay Protection**: Checks `nonce` against the caller-supplied `consumed_nonces` set and records it upon verification.
5. **Redirect Target Allowlist Re-validation**: Confirms `cb` is strictly `http://127.0.0.1(:port)/...` or `carefold://...` with no userinfo or open-redirect tricks.
6. **Zero-Storage Bounce Construction**: Returns:
   ```json
   {
     "redirect_target": "http://127.0.0.1:8000/api/v1/oauth/callback?code=<authorization_code>&state=<relay_ticket>",
     "connection_id": "<cid>",
     "profile_id": "<pid>",
     "user_id": "<uid>",
     "nonce": "<nonce>",
     "stateless": true,
     "tokens_stored": false
   }
   ```

---

## Threat Model

| Threat | Mitigation |
|---|---|
| **Open Redirect Phishing via Relay** | `loopback_callback_url` is validated both at ticket creation and callback resolution to allow only `http://127.0.0.1` loopback or `carefold://` companion URIs, sealed under `HMAC-SHA256`. |
| **Authorization Code Interception** | Every flow uses RFC 7636 PKCE (`S256`). The `code_verifier` remains in the local runtime and is never included in the relay ticket. |
| **Relay Ticket Replay Attack** | Tickets enforce `ttl_seconds <= 120` and carry a 128-bit `nonce` tracked in `consumed_nonces`. |
| **Timing Side-Channel on Signature** | Signature comparison uses `hmac.compare_digest()` over ASCII bytes. |
| **Subpoena or Compromise of Relay Host** | Relay holds zero database state, zero PKCE verifiers, zero OAuth tokens, and zero PHI. |
