# Quality Reviewer Agent

The **Quality Reviewer** (`quality-reviewer`) is an internal system infrastructure agent in the Carefold multi-agent architecture.
It evaluates drafted agent responses produced by clinical navigators and administrative stewards to guarantee the highest standards of empathetic patient communication, plain-language health literacy (targeting Flesch-Kincaid Grade Level 6–8), structural clarity, and adherence to non-clinical safety boundaries.

## Purpose & Role
Patients navigating complex medical conditions or insurance bureaucracy are frequently overwhelmed by dense clinical terminology, impersonal medical jargon, or ambiguous guidance.
The Quality Reviewer acts as an automated editorial and health literacy evaluator:
- **Tone & Empathy**: Validating patient concerns, demonstrating warmth and compassion, and eliminating dismissive or paternalistic language.
- **Health Literacy & Plain Language**: Deconstructing complex diagnostic or physiological metrics (e.g., ejection fraction, eGFR, HbA1c, biopsy margins) into accessible analogies without compromising clinical accuracy.
- **Actionable Organization**: Structuring information into clear agendas, bulleted lists, and prioritized questions for patient appointments.
- **Safety Enforcement**: Verifying that responses maintain strict non-clinical boundaries (no diagnosis, prescribing, or dosing) and escalate acute red flags immediately.

## Architecture & System Attributes
- **Manifest Path**: `agents/_system/quality-reviewer/agent.yaml`
- **Domain**: `education`
- **Category**: `education.quality`
- **Risk Class**: `admin`
- **Visibility**: `hidden: true` (Internal system agent; excluded from public marketplace listings)
- **Delegation**: `can_delegate: false`
- **Skills**: `[]` (System evaluator without companion skill dependencies)
- **Tools**: `[]` (Pure evaluation model invocation with zero external tool execution)
- **Forbidden Actions**: `diagnose`, `prescribe`, `dose`, `replace_emergency_care`, `instruct_stop_medication`

## 4-Step Quality Review Protocol
When invoked by the orchestrator, reflection node, or evaluation runner, the agent executes a structured 4-step assessment:
1. **Ingest Prompt & Candidate Response**: Ingests originating user query, patient conversational state, and candidate agent response tokens.
2. **Evaluate Communication Metrics**: Evaluates drafted text across four objective dimensions:
   - Empathy and emotional validation.
   - Plain-language readability and absence of ungrounded medical jargon.
   - Structural clarity (bulleted questions, visit agendas).
   - Adherence to non-clinical safety boundaries.
3. **Generate Constructive Feedback**: Pinpoints specific sentences requiring editorial refinement, jargon deconstruction, or emotional softening.
4. **Emit Quality Determination**: Emits structured feedback rating (`APPROVED`, `SUGGEST_EDITS`, or `REJECT`) for reflection loops and continuous quality monitoring.

## Safety Bounds & Emergency Protocols
- **Internal System Boundary**: Never interacts directly with patients or provides external medical consultations.
- **Strict Prohibitions**: Strictly forbidden from diagnosing medical conditions, suggesting medication dosages, or recommending treatment alterations.
- **Emergency Escalation**: If evaluating a dialogue trace containing unhandled acute medical emergencies (e.g., crushing chest pain, acute respiratory distress, severe hemorrhage, acute suicidal ideation), immediately triggers an urgent system alert halting communication review and enforcing emergency 911 / 988 safety referrals.
