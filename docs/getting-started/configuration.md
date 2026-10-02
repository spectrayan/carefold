# Configuration Reference

Carefold is configured using Pydantic Settings via environment variables or a local `.env` file at the repository root. All settings use the `CAREFOLD_` environment variable prefix.

---

## Environment Variables

The table below outlines all available configuration options, their types, defaults, and descriptions:

| Variable | Type | Default | Description |
|---|---|---|---|
| `CAREFOLD_WORKSPACE_ROOT` | `Path` | Root directory | Absolute path to the repository workspace containing `agents/`, `skills/`, and `attachments/`. |
| `CAREFOLD_OLLAMA_URL` | `str` | `http://127.0.0.1:11434/v1` | Base URL for the local Ollama inference service (OpenAI-compatible v1 endpoint). |
| `CAREFOLD_DEFAULT_MODEL` | `str` | `llama3.2` | Default LLM model identifier for agent execution. |
| `CAREFOLD_MODEL_TIMEOUT_SECONDS`| `float` | `30.0` | Timeout in seconds for LLM model inference requests. |
| `CAREFOLD_LOG_LEVEL` | `str` | `INFO` | Logging verbosity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `CAREFOLD_LOG_JSON` | `bool` | `false` | When `true`, emits structured JSON log entries. |
| `CAREFOLD_AUDIT_LOG_PATH` | `Path` | `logs/audit.jsonl` | Filepath where structured zero-body audit events are written. |
| `CAREFOLD_AUDIT_STORE_BODIES` | `bool` | `false` | When `false` (recommended), redacts prompts and completion bodies in audit logs to protect PII. |
| `CAREFOLD_DB_PATH` | `Path` | `None` | Path to SQLite checkpointer database for session state persistence. |
| `CAREFOLD_MEMORY_BACKEND` | `str` | `sqlite` | Cognitive memory backend adapter. Only `sqlite` is implemented today; `spector` and `postgres` are reserved for planned adapters and currently raise a "not yet implemented" error. |
| `CAREFOLD_SPECTOR_URL` | `str` | `http://localhost:7070` | Endpoint URL for future Spector MCP cognitive memory integration. |
| `CAREFOLD_CATALOG_DB_PATH` | `Path` | `catalog.db` | Custom file path for SQLite catalog and memory storage (defaults to `${CAREFOLD_WORKSPACE_ROOT}/catalog.db`). |
| `CAREFOLD_CORS_ORIGINS` | `List[str]` | `["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "http://127.0.0.1:8000"]` | Allowed CORS origins for browser web requests. |

---

## Sample `.env` Configuration

To override default settings, create a `.env` file in the root of the project:

```bash
# ==============================================================================
# Carefold Local Development Configuration
# ==============================================================================

# Core Engine Settings
CAREFOLD_LOG_LEVEL=INFO
CAREFOLD_LOG_JSON=false
CAREFOLD_AUDIT_STORE_BODIES=false

# Ollama Local Inference
CAREFOLD_OLLAMA_URL=http://127.0.0.1:11434/v1
CAREFOLD_DEFAULT_MODEL=llama3.2
CAREFOLD_MODEL_TIMEOUT_SECONDS=45.0

# Cognitive Memory & Catalog Persistence
CAREFOLD_MEMORY_BACKEND=sqlite
CAREFOLD_CATALOG_DB_PATH=catalog.db

# CORS Allowed Origins
CAREFOLD_CORS_ORIGINS=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "http://127.0.0.1:8000"]
```

---

## Multi-Provider Support

While Carefold defaults to local Ollama inference for maximum patient privacy, the engine supports external LLM providers via standard environment variables:

### 1. Ollama (Default Local)
- No API key required.
- Set `CAREFOLD_OLLAMA_URL` (default: `http://127.0.0.1:11434/v1`).
- Supported models: `llama3.2`, `llama3.1`, `mistral`, `phi3`.

### 2. Google Gemini
To utilize Google's Gemini models:
```bash
export GOOGLE_API_KEY="your-google-api-key"
export CAREFOLD_DEFAULT_MODEL="gemini-2.0-flash"
```

### 3. Anthropic Claude
To utilize Anthropic's Claude models:
```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export CAREFOLD_DEFAULT_MODEL="claude-3-5-sonnet-latest"
```

### 4. OpenAI
To utilize OpenAI models:
```bash
export OPENAI_API_KEY="your-openai-api-key"
export CAREFOLD_DEFAULT_MODEL="gpt-4o"
```

---

## Directory Configuration & Workspace Resolution

Carefold automatically locates workspace directories relative to `CAREFOLD_WORKSPACE_ROOT`:

- **Agents Directory**: `${CAREFOLD_WORKSPACE_ROOT}/agents`
- **Skills Directory**: `${CAREFOLD_WORKSPACE_ROOT}/skills`
- **Attachments Sandbox**: `${CAREFOLD_WORKSPACE_ROOT}/attachments`
- **User Notes Directory**: `${CAREFOLD_WORKSPACE_ROOT}/workspace/notes` (or `${CAREFOLD_WORKSPACE_ROOT}/notes`)
- **Audit Logs**: `${CAREFOLD_WORKSPACE_ROOT}/logs/audit.jsonl`

All file operations inside the sandbox are strictly guarded against path traversal attacks (`../`, null bytes, and symlink escapes).

---

## Web App Environment Variables

The Next.js web app (`apps/web`) reads two environment variables of its own. They are separate from the backend `CAREFOLD_*` settings above.

| Variable | Type | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | `str` | `http://127.0.0.1:8000` | Base URL of the Carefold backend that the web app's server routes call. Set it when the backend runs somewhere other than the default, such as a remote server. The Docker Compose `web` service already sets it to `http://backend:8000`. |
| `CAREFOLD_WORKSPACE` | `Path` | Detected automatically | Location of the repository workspace. By default the app walks up from the current working directory to find the repo. Set it if the app starts from a place where it cannot find the repo on its own. |

For example, to run the web app against a remote backend:

```bash
BACKEND_URL=https://carefold.example.com
```

