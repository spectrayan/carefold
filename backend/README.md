# Carefold FastAPI Backend

Python 3.12+ FastAPI backend powering all AI, agentic runtime, closed tools sandbox, deterministic safety refusal gates, privacy audit logging, and REST/SSE streaming endpoints for Carefold.

## Architecture

```
backend/
├── pyproject.toml              # Build metadata, dependencies, and pytest configuration
├── requirements.txt            # Production runtime dependencies
├── requirements-dev.txt        # Development and testing dependencies
├── src/
│   └── carefold/
│       ├── __init__.py         # Package export
│       ├── config.py           # Pydantic Settings
│       ├── main.py             # FastAPI entrypoint, lifespan, CORS, error handling
│       ├── schemas/            # Manifests, audit, chat, health, tool schemas
│       ├── loaders/            # Manifest parsers, intended-use checks, permission union engine
│       ├── tools/              # Closed Phase 0 sandbox (attach-read, workspace-note, skill-docs)
│       ├── safety/             # Deterministic refusal classifier & safe refusal template
│       ├── audit/              # Concurrency-safe append-only JSONL logger with Zero-Body redaction
│       ├── model/              # OpenAI SSE client & offline MockModelClient
│       ├── engine/             # Agent runtime coordinating prompts, model calls, tools, safety
│       └── api/                # FastAPI routers (/health, /agents, /skills, /audit, /chat)
└── tests/                      # Unit, boundary, privacy, and integration test suite
```

## Setup & Running

### 1. Create Virtual Environment and Install Dependencies

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/pip install -e backend/
```

### 2. Run the Development Server

```bash
backend/.venv/bin/python3 -m uvicorn carefold.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will be accessible at `http://localhost:8000`.

### 3. Run the Test Suite

```bash
backend/.venv/bin/pytest backend/tests/ -v
```

## API Endpoints

- `GET /api/health`: Health status, uptime, Ollama reachability, and installed catalog statistics.
- `GET /api/agents`: Enumerate installed agents with risk classes, tools, and skills.
- `GET /api/agents/{id}`: Detailed agent manifest, persona, resolved skills, and effective tools.
- `GET /api/skills`: Enumerate installed skills with verification status and declared tools.
- `GET /api/skills/{id}`: Skill details, reference documents, and instructions.
- `GET /api/audit`: Query recent append-only audit events (newest first).
- `POST /api/chat`: Server-Sent Events (SSE) streaming chat endpoint emitting token deltas, tool traces, and safety refusal gates.
