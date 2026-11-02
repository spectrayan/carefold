# Visit Steward

Prepare organized question lists, symptom timelines, and discussion agendas for your upcoming medical, specialist, and therapy appointments.

## Overview

Visit Steward is your pre-appointment wellness companion. Clinicians often have limited time during visits, making it difficult for patients to communicate everything clearly. Visit Steward helps you clarify your thoughts before your appointment, extract important questions from prior clinic summaries or lab notes, and prepare a concise, high-impact agenda.

## Key Capabilities

- **Appointment Agenda Formulation**: Identify and prioritize the top 2–3 questions you want to discuss with your provider.
- **Symptom Timeline Organization**: Structure when your symptoms began, their frequency, triggers, and impact on daily activities.
- **Attachment Analysis**: Read patient summaries or previous visit notes from `attachments/` via `attach-read` to highlight follow-up questions.
- **Reference Checklists**: Consult pre-appointment preparation guides and question banks using `skill-docs`.
- **Note Saving**: Save your final visit agenda directly into your local workspace notes using `workspace-note`.

## Declared Skills & Tools

- **Skills**: `visit-prep`
- **Effective Tools**: `attach-read`, `workspace-note`, `skill-docs`
- **Risk Class**: `wellness`

## Important Safety Information

Visit Steward is an administrative and wellness preparation tool, not a doctor or diagnostic system. It cannot diagnose illnesses, interpret medical imaging, recommend prescription drug doses, or provide emergency triage. If you are experiencing a medical emergency, call 911 or visit your nearest emergency room immediately.

## Example Terminal Usage

```bash
carefold run --agent appointment-prep-coordinator "Help me organize questions for my annual physical next Monday."
```
