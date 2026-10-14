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

# Authoring Carefold Connectors

Carefold connectors integrate external patient devices, calendars, and health record portals into the local-first runtime while preserving strict egress isolation, clinical provenance, and prompt-injection taint boundaries.

---

## 1. Architecture Overview

Every connector in `libs/connectors/` consists of two parts:

1. **Metadata-Only Declarative Manifest (`*.yaml`)**: Validated by `ConnectorManifest` (`connectors.manifest`). Declares allowed outbound hosts, schemes, ports, authentication mechanism (`oauth2` with PKCE or `basic`), tool risk classifications, and data provenance trust level (`trusted` vs `untrusted`).
2. **Protocol Implementation (`Connector`)**: A Python class implementing `manifest`, `streams()`, `fetch(ctx, stream, cursor, http)`, `map(page)`, and `tools()`.

---

## 2. Declarative Manifest (`connector.yaml`)

Manifests are strictly declarative and never contain executable code or credentials:

```yaml
id: withings
version: 0.1.0
name: Withings Health Mate
description: Ingests smart scale weight, blood pressure, heart rate, and SpO2 readings.
categories:
  - vitals
entrypoint: connectors.starters.withings:WithingsConnector
data_flows:
  allowed_hosts:
    - wbsapi.withings.net
    - account.withings.com
  allowed_schemes:
    - https
  allowed_ports:
    - 443
  egress_direction: egress_only
  pii_types_transferred:
    - vitals
auth:
  type: oauth2
  pkce: true
  client_source: byo
  token_rotation: true
  rotating_refresh: true
  scopes:
    - user.metrics
trust:
  publisher: Spectrayan
  verified: true
  sandbox_level: strict
  trust_level: trusted
terms:
  license: Apache-2.0
  ai_use_allowed: true
```

### Authentication Modes
- **OAuth 2.0 with PKCE (`type: oauth2`)**: Uses `pkce: true` (S256 verification), `client_source: byo` (user-supplied client credentials stored encrypted at rest), and optional `token_rotation: true` for providers like Withings that rotate refresh tokens on every exchange.
- **Basic / App-Specific Password (`type: basic`)**: Used for standards-based protocols such as CalDAV (`caldav.icloud.com`, `caldav.fastmail.com`, or self-hosted `localhost`).

---

## 3. Implementing the `Connector` Protocol

A connector class must satisfy the `@runtime_checkable` `Connector` protocol in `connectors.base`:

```python
class Connector(Protocol):
    @property
    def manifest(self) -> ConnectorManifest: ...
    def streams(self) -> List[StreamSpec]: ...
    async def fetch(self, ctx: ToolContext, stream: str, cursor: Optional[str], http: ScopedHttp) -> Page: ...
    def map(self, page: Page) -> List[NormalisedRecord]: ...
    def tools(self) -> List[ToolSpec]: ...
```

### Sandboxed Network Egress (`ScopedHttp`)
Connectors never instantiate raw `httpx` or `urllib` clients directly. Instead, `fetch(...)` receives a pre-configured `ScopedHttp` instance constructed via `ScopedHttp.from_data_flow(manifest.data_flows)`. Any request or redirect targeting a hostname outside `data_flows.allowed_hosts` (or a cloud metadata/link-local IP) immediately raises `EgressBlockedError`.

---

## 4. Open-Source FHIR R4 Validation (`fhir.resources`)

Connectors that emit clinical records (`WithingsConnector`, `EpicSmartConnector`) validate and normalize all resources using `fhir.resources.R4B` Pydantic v2 models before emitting `NormalisedRecord` items:

- **Withings (`AU-54`)**: Maps device measure groups into LOINC-coded FHIR R4 `Observation` resources (`29463-7` Body weight, `8302-2` Body height, `85354-9` Blood pressure panel with `8480-6` Systolic and `8462-4` Diastolic components, `8867-4` Heart rate, and `2708-6` SpO2).
- **Epic SMART on FHIR (`AU-56`)**: Validates USCDI R4 resources (`Condition`, `MedicationRequest`, `AllergyIntolerance`, `Immunization`, `Observation`, `Encounter`, `DocumentReference`) against their respective `fhir.resources.R4B` models.

---

## 5. Provenance & Taint Rules (`trusted` vs `untrusted`)

Carefold enforces strict provenance and taint tracking across all connectors:

| Connector Type | `trust_level` | Rationale |
|---|---|---|
| Structured device telemetry (`withings`) | `trusted` | Numeric sensor measurements mapped deterministically to LOINC codes. |
| Structured calendar availability (`google-calendar`, `caldav`) | `trusted` | Busy windows and PHI-stripped appointment slots (`sanitize_calendar_event_title`). |
| External EHR clinical narratives (`epic-smart`) | `untrusted` | Free-text clinical notes and external narratives carry prompt-injection risk and require `From Epic SMART, <YYYY-MM-DD>` provenance attribution (`E10.7`). |

External write tools (such as `calendar_create_event`) must declare `risk_tier="write_external"` so the policy engine gates execution behind explicit human approval in `A0`/`A1` autonomy modes.
