# Security Policy & Clinical Safety Disclosure

Carefold treats user privacy, sandbox security, and clinical safety with the highest level of rigor. This document outlines our Coordinated Vulnerability Disclosure (CVD) process and our non-clinical safety incident reporting protocol.

---

## 1. Supported Versions

Security and clinical safety patches are actively backported to the following release branches:

| Version | Supported | Maintenance Status |
|---|---|---|
| `0.3.x` | :white_check_mark: | Current active release branch |
| `0.2.x` | :white_check_mark: | Critical security and safety fixes only |
| `< 0.2.0` | :x: | End of life (please upgrade) |

---

## 2. Reporting a Vulnerability

If you discover a security vulnerability or sandbox escape in Carefold, please disclose it responsibly via private channels. **Do not create public GitHub issues for unresolved vulnerabilities.**

### Contact Information
- **Email**: [security@spectrayan.com](mailto:security@spectrayan.com)
- **PGP Encryption**: For sensitive disclosures, please request our security PGP public key or encrypt using our published security key on standard key servers.

### Information to Include
To help us triage and remediate the issue rapidly, please provide:
1. **Description**: Clear explanation of the vulnerability or clinical safety failure.
2. **Impact**: Potential consequences (e.g., local file system read, PII extraction, bypass of emergency red-flag refusal).
3. **Reproduction Steps**: Minimal reproducible example, test input, or proof-of-concept (POC) script.
4. **Environment**: Carefold version, operating system, LLM provider/model, and Python/Node versions.

---

## 3. Scope of Security & Safety Review

### In-Scope Vulnerabilities
- **Tool Sandbox Escapes**: Path traversal attacks (`../`), symlink escapes, or arbitrary file system reads outside `attachments/` and `workspace/notes/`.
- **PII Leakage**: Failures in the sanitization pipeline that cause unmasked Social Security Numbers, Medical Record Numbers, or patient addresses to enter logs or LLM context.
- **Safety Boundary Bypasses**: Boundary prompt injections that induce the runtime to diagnose acute illnesses, prescribe medications, or bypass emergency red-flag refusals.
- **Grounding Failures**: Numerical hallucination bugs where ungrounded financial or clinical tokens bypass the validator node.
- **Injection Attacks**: SQLite injection in FTS5 adapters or remote code execution via unsafe deserialization.

### Out of Scope
- Theoretical vulnerabilities without a functional proof-of-concept.
- Volumetric Denial of Service (DoS) attacks against local endpoints.
- Vulnerabilities requiring root/physical access to the user's host machine.
- Flaws in third-party LLM providers (e.g., Anthropic, OpenAI, Google) unrelated to Carefold's runtime or guardrail nodes.

---

## 4. Response & Remediation Service Level Agreements (SLAs)

We commit to the following response timeline for security and safety reports:

| Milestone | SLA Window | Description |
|---|---|---|
| **Initial Acknowledgment** | **< 24 Hours** | Confirmation of receipt by a member of the security team. |
| **Triage & Severity Assessment** | **< 72 Hours** | Initial severity ranking (CVSS score) and replication verification. |
| **Status Updates** | **Every 5 Business Days** | Regular progress updates until a patch is deployed. |
| **Remediation & Patch Release** | **14–30 Days** | Public release of fix with credit to the reporter (unless zero-day requiring expedited hotfix). |

---

## 5. Non-Clinical Safety Incident Reporting

Because Carefold operates in the healthcare domain, behavioral anomalies that do not constitute traditional cybersecurity vulnerabilities must also be reported.

### What is a Clinical Safety Incident?
- An agent providing explicit medication dosage or treatment recommendations.
- Failure of an agent to halt and issue an emergency directive when a patient reports acute chest pain, stroke symptoms, or suicidal ideation.
- Hallucinated insurance copayments or coverage denial logic presented as factual advice.

### Safety Reporting Channel
Report clinical safety incidents directly to [conduct@carefold.org](mailto:conduct@carefold.org) and [security@spectrayan.com](mailto:security@spectrayan.com) with the subject tag `[Clinical Safety Incident]`. Our Clinical AI Reviewers will review the conversation trace, evaluate golden dataset coverage, and introduce regression guardrails.
