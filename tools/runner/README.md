# @spectrayan/carefold-runner

Core agent and skill runner, safety refusal gate, closed tool sandbox, and audit engine for Carefold.

## Features

- **Declarative Least-Privilege Closed Sandbox**:
  Only Phase 0 tools (`attach-read`, `workspace-note`, `skill-docs`) are permitted.
  Effective tools are strictly computed as:
  $$\text{effective\_tools} = \text{unique}(\text{agent.tools} \cup \text{skill.tools}) \cap \text{Phase0Registry}$$
- **Safety Refusal Gate**:
  Deterministic pattern classifier blocking clinical diagnosis, medication dosing, emergency triage diversion, and medication discontinuation instructions, substituting the canonical Safe Refusal Template and recording `event: "refuse"`.
- **Privacy Audit Logger**:
  Append-only JSONL log writing to `logs/audit.jsonl` with zero-body redaction default (`audit.store_bodies: false`).
- **OpenAI-Compatible Streaming Client**:
  Local-first SSE streaming client targeting Ollama (`http://127.0.0.1:11434/v1`) with fallback model resolution and deterministic offline mock adapter.
- **Manifest Loaders**:
  Full schema validation for `agent.yaml`, `carefold.yaml`, and `SKILL.md` frontmatter with mandatory intended-use statement enforcement.

## Installation

```bash
pnpm add @spectrayan/carefold-runner
```

## Usage

```typescript
import { loadAgent, executeAgentRun } from '@spectrayan/carefold-runner';

// Load agent and resolve declared skills
const { agent, effectiveTools, skills } = await loadAgent('./agents/appointment-prep-coordinator', './skills');

// Execute streaming run
const stream = executeAgentRun({
  agentDir: './agents/appointment-prep-coordinator',
  skillsDir: './skills',
  prompt: 'Help me prepare questions for my therapy appointment.'
});

for await (const chunk of stream) {
  if (chunk.type === 'token') {
    process.stdout.write(chunk.token);
  }
}
```

## License

Apache-2.0
