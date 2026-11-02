# Benefits Guide

Demystify health insurance jargon, plan summaries, copays, deductibles, and Explanation of Benefits (EOB) statements with clear, plain-language guidance.

## Overview

Health insurance policies and medical bills are notoriously difficult to decipher. Benefits Guide assists users in understanding how their cost-sharing mechanisms operate throughout the plan year. Whether you want to understand the difference between copays and coinsurance, understand an Explanation of Benefits statement, or review an attached Summary of Benefits document, Benefits Guide translates fine print into straightforward language.

## Key Capabilities

- **Insurance Terminology Demystification**: Clear explanations of deductibles, copayments, coinsurance, out-of-pocket maximums (OOPM), and formulary tiers.
- **Plan Summary & EOB Review**: Inspect uploaded plan summaries or billing statements in `attachments/` via `attach-read` to explain patient responsibility calculations.
- **Glossary Lookups**: Query the official health insurance glossary reference using `skill-docs`.
- **Member Inquiries**: Formulate precise, informed questions to ask insurance customer service representatives or employer benefits administrators.

## Declared Skills & Tools

- **Skills**: `benefits-explainer`
- **Effective Tools**: `attach-read`, `skill-docs`
- **Risk Class**: `admin`

## Important Safety & Administrative Disclosures

Benefits Guide is an educational and administrative resource. It does not provide medical diagnoses, clinical advice, or legally binding coverage determinations. Only your health insurance plan can confirm coverage for a specific provider or procedure. Always verify benefits with your insurer prior to scheduled non-emergency treatments.

## Example Terminal Usage

```bash
carefold run --agent benefits-coordinator "What is the difference between my deductible and my out-of-pocket maximum?"
```
