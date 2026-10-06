# Quickstart Guide

This tutorial guides you through starting the Carefold services and executing your first patient navigation consultation in under five minutes.

---

## Architecture Overview of Local Services

Running Carefold locally spins up two coordinated processes:
1. **FastAPI Backend (`backend/`)**: Serves REST APIs and Server-Sent Events (SSE) streaming on `http://localhost:8000`.
2. **Next.js Web UI (`apps/web/`)**: Provides the marketplace catalog and consultation chat UI on `http://localhost:3000`.

---

## Step 1: Start the Backend Service

Activate your Python virtual environment and start the FastAPI server with Uvicorn:

```bash
# From the repository root
source backend/.venv/bin/activate

# Start backend server
uvicorn carefold.main:app --host 0.0.0.0 --port 8000 --reload
```

You can verify the backend is running by querying the health check endpoint:

```bash
curl http://localhost:8000/api/health
```

Expected JSON response (abbreviated; see the [API Reference](../api/reference.md) for the full schema):
```json
{
  "status": "ok",
  "version": "0.1.0",
  "modelReachable": true,
  "workspace": {
    "root": "/path/to/carefold",
    "agentsCount": 22,
    "skillsCount": 24
  }
}
```

`status` reports `degraded` until a model provider (for example a local Ollama server) is reachable. `agentsCount` and `skillsCount` report active specialist agents (22) and modular skill packs (24) in the workspace, excluding internal system helpers and starter templates.

---

## Step 2: Start the Next.js Frontend

In a separate terminal window, launch the development frontend:

```bash
# From the repository root
pnpm --filter web dev
```

The Next.js application will compile and become available at `http://localhost:3000`.

---

## Step 3: Browse the Agent Marketplace

1. Open your browser and navigate to `http://localhost:3000`.
2. You will see the **Carefold Agent Marketplace**, displaying the 20 specialist agents categorized into:
   - **Organ-Specific Clinical Navigators** (e.g., Cardiology Guide, Nephrology Guide, Oncology Navigator).
   - **Administrative Stewards & Companions** (e.g., Prior Auth Navigator, Claims Appeals Guide, Formulary Guide).
3. Click on **Cardiology Guide** to inspect its manifest, clinical care stages, declared skills (`cardiology-prep`), and sandboxed tool permissions.

---

## Step 4: Initiate a Consultation Session

Click **"Try in Chat"** on the Cardiology Guide card to launch the consultation interface.

### Example Prompt:
> *"I've been noticing high blood pressure readings in the morning (around 145/95). My doctor wants me to track it for 2 weeks. How should I prepare for my upcoming appointment?"*

### What Happens Behind the Scenes:
1. **Context Load**: The orchestrator checks for attached medical records or previous user notes.
2. **Validation & Gating**: The input is checked against emergency red-flag patterns (no acute chest pain or radiation detected).
3. **Plan & Provision**: The orchestrator matches the query to `cardiology-guide`, inspects its declared skill `cardiology-prep`, and provisions `hypertension_log_template.md` and `cardiology_visit_agenda.md` directly into the agent prompt.
4. **Execution Dispatch**: The `cardiology-guide` specialist generates empathetic guidance and structures a two-week blood pressure logging agenda.
5. **Synthesis & Guardrails**: Robotic preambles and duplicate disclaimers are removed, and the single canonical disclaimer footer is appended.
6. **Streaming Delivery**: The response streams in real time via SSE to the web chat interface.

---

## Step 5: Verify the Audit Log

Carefold logs every consultation event to an append-only JSONL log with zero-body PII redaction by default.

Inspect the latest audit entry:

```bash
tail -n 1 logs/audit.jsonl | jq .
```

Sample audit entry:
```json
{
  "timestamp": "2026-10-02T04:15:32.184Z",
  "event": "synthesis",
  "agent_id": "cardiology-guide",
  "allowed": true,
  "target_agents": ["cardiology-guide"]
}
```

Notice that patient health prompts and completion bodies are omitted. Zero-body audit logging is designed to support privacy reviews by keeping health content out of the audit trail; on its own it does not make a deployment HIPAA compliant, and Carefold does not claim any compliance certification.

Next, explore the [Architecture Overview](../architecture/overview.md) to learn how Carefold orchestrates multi-agent consultations.
