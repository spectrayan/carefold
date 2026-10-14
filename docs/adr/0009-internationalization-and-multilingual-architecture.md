# ADR-0009: Multi-Layer Internationalization (i18n), Unicode UAX #15 NFC Storage, and Multilingual Clinical Safety Architecture

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
| **Consulted** | Technical Lead & TSC Chair, Clinical Safety Working Group |
| **Informed** | Carefold Open-Source Community |
| **Related** | ADR-0001 (Orchestrator-Driven Agent Architecture), ADR-0002 (Hexagonal Memory & Catalog Ports), ADR-0007 (Content-Addressed Storage & Hybrid Search) |

---

## Context & Problem Statement

Carefold serves multigenerational households where an account steward may manage care profiles across multiple languages and writing scripts—for example, a bilingual adult child managing a Spanish-speaking parent's cardiology visits (`es-ES`), a Hindi-speaking elder (`hi-IN`), or an Arabic-speaking family member requiring right-to-left (`rtl`) layout (`ar-SA`), while using English (`en-US`) or French (`fr-FR`) for their own profile.

Healthcare internationalization carries significantly stricter invariants than general consumer software:
1. **Unicode Representation & Full-Text Search Integrity**: macOS/iOS keyboards and PDF extractors frequently emit decomposed Unicode strings (`NFD`, e.g., `"Cafe\u0301"`), whereas Linux/Windows/Web inputs emit composed strings (`NFC`, e.g., `"Caf\u00e9"`). Without canonical composition at the ingestion boundary, content-addressed SHA-256 hashes diverge and SQLite FTS5 lexical indices fail to match identical clinical terms across devices.
2. **Language-Neutral Clinical Terminologies**: Translating clinical codes or mutating canonical medical concepts breaks longitudinal trend tracking, preventive care rules, and FHIR R4 interoperability.
3. **Multilingual Acute Safety & Non-Clinical Disclaimers**: Emergency red-flag detection (chest pain, acute dyspnea, stroke symptoms, suicidal ideation) and mandatory non-clinical disclaimers must operate reliably across all supported locales (`en-US`, `es-ES`, `fr-FR`, `hi-IN`, `ar-SA`).

---

## Decision Drivers

- **Standards Compliance**: Strict adherence to IETF BCP 47 (RFC 5646) language tags, RFC 4647 language range lookup, Unicode Standard Annex #15 (`UAX #15` Canonical Composition `NFC`), ICU MessageFormat plural/interpolation syntax, HL7 FHIR R4 `CodeableConcept` invariants, and W3C CSS Logical Properties.
- **Per-Profile Locale Sovereignty**: Each family `Profile` maintains its own `preferred_locale` independent of the steward `User.preferred_locale` or browser `Accept-Language` header, while every clinical `Note`, `Attachment`, and `HealthResource` records its authoring/source `locale` provenance.
- **Deterministic Offline Safety**: Multilingual red-flag detection, localized non-clinical disclaimers, and localized emergency refusal directives (`911` / `988` / `112`) must execute deterministically in local-first mode with zero external network calls.
- **Bidirectional (`LTR` / `RTL`) Layout Fidelity**: Arabic (`ar-SA`) and future RTL scripts (`he`, `fa`, `ur`) must automatically switch document direction (`dir="rtl"`) and mirror layout chrome via CSS Logical Properties without duplicating component trees.

---

## Considered Options

### Option 1: Client-Only Browser Translation / String Replacement
* **Description**: Store all backend records without locale metadata or Unicode normalization and rely on ad-hoc client string tables or browser auto-translation.
* **Pros**: Minimal backend schema changes.
* **Cons**: Fails Unicode `NFD`/`NFC` FTS5 search matching, provides no per-profile locale persistence across devices, risks mistranslating clinical safety disclaimers, and misses non-English acute emergency red flags at the backend guardrail layer.

### Option 2: Separate Per-Language Databases or Translated Clinical Codes
* **Description**: Partition clinical records by language or store translated medical codes directly in `HealthResource.code`.
* **Pros**: Simple single-language queries.
* **Cons**: Breaks cross-language family care stewardship and violates HL7 FHIR R4 terminology binding (`LOINC`, `SNOMED CT`, `RxNorm`, `CVX`, `ICD-10-CM`).

### Option 3: Five-Layer Standards-Driven i18n Architecture (Selected)
* **Description**: Implement an end-to-end architecture spanning:
  1. **IETF BCP 47 & RFC 4647 Locale Negotiation** (`carefold.i18n.locale`)
  2. **UTF-8 + UAX #15 `NFC` Storage & Provenance Columns** (`0010_i18n_and_locale_storage`)
  3. **HL7 FHIR R4 Language-Neutral Clinical Coding Invariant**
  4. **Multilingual Clinical Safety Guardrails & ICU Catalogs** (`carefold.i18n.catalog`)
  5. **Intl-Formatted & CSS Logical Property Bidirectional UI** (`LTR`/`RTL`)
* **Pros**:
  - Guarantees byte-identical UTF-8 `NFC` strings for SHA-256 content addressing and SQLite FTS5 indexing.
  - Preserves language-neutral clinical coding while localizing display labels, disclaimers, and UI chrome.
  - Protects non-English speakers with deterministic multilingual acute red-flag detection.
* **Cons**: Requires synchronized ICU JSON catalogs across backend and frontend workspaces.

---

## Decision Outcome

**Chosen Option**: **Option 3: Five-Layer Standards-Driven i18n Architecture**

### 1. IETF BCP 47 / RFC 5646 Locale Tags & RFC 4647 Lookup Negotiation

Carefold standardizes on canonical IETF BCP 47 (`language-region` or `language-script-region`) tags validated via `validate_bcp47_tag()` and normalized via `canonicalize_locale()`.

First-class supported locales in `SUPPORTED_LOCALES`:
- `en-US`: English (United States) — `English (US)`, `dir="ltr"`, `region="US"`
- `es-ES`: Spanish — `Español`, `dir="ltr"`, `region="ES"`
- `fr-FR`: French — `Français`, `dir="ltr"`, `region="FR"`
- `hi-IN`: Hindi — `हिन्दी`, `dir="ltr"`, `region="IN"`
- `ar-SA`: Arabic — `العربية`, `dir="rtl"`, `region="SA"`

`negotiate_locale()` implements deterministic RFC 4647 lookup across a four-tier hierarchy:

$$\text{EffectiveLocale} = \text{Profile.preferred\_locale} \;\triangleright\; \text{User.preferred\_locale} \;\triangleright\; \text{RFC4647}(\text{Accept-Language}) \;\triangleright\; \text{"en-US"}$$

When evaluating an HTTP `Accept-Language` header (e.g., `fr-CA,fr;q=0.9,en-US;q=0.8`), ranges are sorted descending by quality weight `q` (`0.0 <= q <= 1.0`). Each tag is matched first by exact canonical locale (`fr-FR`), then by primary language subtag prefix (`fr-CA` $\rightarrow$ `fr` $\rightarrow$ `fr-FR`), before falling back to `DEFAULT_LOCALE` (`en-US`).

### 2. Storage Layer: UTF-8, UAX #15 `NFC`, Locale Provenance & UTC Timestamps

1. **Unicode UAX #15 Canonical Composition (`NFC`)**:
   All user-authored text (`Note.title`, `Note.content`) and semantic search chunks (`ClinicalChunker.chunk()`) pass through `normalize_text_nfc()` (`unicodedata.normalize("NFC", text)`) prior to database persistence, SHA-256 idempotency hashing, and SQLite FTS5 indexing. Decomposed sequences such as `"Cafe\u0301"` are canonically composed to `"Caf\u00e9"` (`\u00e9`).
2. **Relational Schema Provenance (`0010_i18n_and_locale_storage`)**:
   - `users.preferred_locale` (`VARCHAR(16)`, default `'en-US'`, non-null)
   - `profiles.preferred_locale` (`VARCHAR(16)`, default `'en-US'`, non-null)
   - `notes.locale` (`VARCHAR(16)`, default `'en-US'`, indexed via `ix_notes_locale`)
   - `attachments.locale` (`VARCHAR(16)`, default `'en-US'`, non-null)
   - `health_resources.locale` (`VARCHAR(16)`, default `'en-US'`, non-null)
3. **Timezone-Aware UTC Timestamps (`TIMESTAMPTZ`)**:
   All relational timestamps (`created_at`, `updated_at`, `scheduled_at`, `expires_at`) are persisted in UTC (`DateTime(timezone=True)`) and paired with IANA timezone identifiers (`Profile.timezone` / `Job.timezone`, e.g., `America/New_York`, `Europe/Madrid`, `Asia/Kolkata`, `Asia/Riyadh`) for local wall-clock rendering.

### 3. Clinical Data Layer (HL7 FHIR R4 Coding Invariant)

Clinical entities (`HealthResource`, `PreventiveRecord`, `VitalReading`) strictly separate machine-readable clinical codes from localized human display labels:
- **Canonical Code Invariant**: `system` and `code` columns always store language-neutral standard terminologies:
  - Laboratory & Vital Observations: `LOINC` (e.g., `8480-6` Systolic blood pressure, `4548-4` HbA1c)
  - Conditions & Allergies: `SNOMED CT` / `ICD-10-CM`
  - Medications: `RxNorm`
  - Immunizations: `CVX`
- **Localized Display & Provenance**: Human-readable strings remain in `display` / `title` alongside `HealthResource.locale`, enabling multilingual dossier extraction without corrupting clinical rule evaluation.

### 4. Safety & Runtime Layer: Multilingual Red-Flag Guardrails & Disclaimers

1. **Localized Non-Clinical Disclaimers (`get_localized_disclaimer`)**:
   Every supported locale provides a verified translation of Carefold's non-clinical intended-use boundary (`safety.disclaimer_banner` and `safety.non_clinical_notice`).
2. **Localized Emergency Directives (`get_localized_emergency_directive`)**:
   Acute refusals return localized emergency contact directives (`911` / `988` in North America, `112` in Europe, and local emergency department guidance) via `safety.emergency_directive`.
3. **Multilingual Acute Red-Flag Detection (`detect_multilingual_red_flag`)**:
   `detect_multilingual_red_flag()` normalizes input text to `NFC` and evaluates deterministic acute emergency patterns across all five supported languages:
   - **English (`en-US`)**: `chest pain`, `crushing chest`, `shortness of breath`, `difficulty breathing`, `suicide`, `kill myself`
   - **Spanish (`es-ES`)**: `dolor en el pecho`, `dificultad para respirar`, `falta de aire`, `suicidio`, `quitarme la vida`
   - **French (`fr-FR`)**: `douleur thoracique`, `douleur dans la poitrine`, `difficulté à respirer`, `essoufflement aigu`, `suicide`
   - **Hindi (`hi-IN`)**: `सीने में दर्द`, `सांस लेने में तकलीफ`, `आत्महत्या`
   - **Arabic (`ar-SA`)**: `ألم في الصدر`, `ضيق في التنفس`, `انتحار`

### 5. UI Layer: ICU MessageFormat, `Intl` Formatters & W3C CSS Logical Properties

1. **ICU MessageFormat Catalogs (`backend/src/carefold/resources/locales/*.json`)**:
   Translation catalogs share a uniform schema (`safety`, `navigation`, `common`, `preventive`, `errors`) supporting `{variable}` interpolation and ICU plural blocks (`{count, plural, zero {...} one {...} other {...}}` with `#` count substitution).
2. **Standards-Based Client Formatting**:
   Dates, numbers, units, and relative timestamps are formatted via native ECMAScript Internationalization APIs (`Intl.DateTimeFormat`, `Intl.NumberFormat`, `Intl.RelativeTimeFormat`, `Intl.PluralRules`).
3. **Bidirectional (`LTR` / `RTL`) Layout**:
   `get_text_direction(locale)` resolves `"rtl"` for Arabic (`ar-SA`) and `"ltr"` for Latin/Devanagari locales. The web shell binds `lang={locale}` and `dir={direction}` on the document root and uses W3C CSS Logical Properties (`margin-inline-start`, `padding-inline-end`, `border-inline-start`, `inset-inline-end`, `text-align: start`) so navigation rails, drawers, and clinical cards mirror automatically in RTL mode.

---

## Verification & Compliance Matrix

| Invariant | Verification Gate |
|---|---|
| BCP 47 Validation & Canonicalization | `test_i18n_storage_data_and_api.py` (`validate_bcp47_tag`, `canonicalize_locale`, `get_text_direction`) |
| RFC 4647 Quality-Weighted Lookup | `test_i18n_storage_data_and_api.py` (`negotiate_locale` priority & `q`-factor ordering) |
| UAX #15 `NFC` Composition | `test_i18n_storage_data_and_api.py` (`normalize_text_nfc` on notes & `ClinicalChunker`) |
| ICU MessageFormat Pluralization | `test_i18n_storage_data_and_api.py` (`format_icu_message` & `translate` across all 5 locales) |
| Multilingual Emergency Red Flags | `test_i18n_storage_data_and_api.py` (`detect_multilingual_red_flag` in `en`, `es`, `fr`, `hi`, `ar`) |
| FastAPI `/i18n/*`, Profile & Note Locale APIs | `test_i18n_storage_data_and_api.py` (`GET /i18n/locales`, `GET /i18n/catalog/{locale}`, Profile & Note persistence) |
