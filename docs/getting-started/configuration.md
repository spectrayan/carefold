# Configuration Reference

Carefold is configured using Pydantic Settings via environment variables or a local `.env` file at the repository root. All backend settings use the `CAREFOLD_` environment variable prefix.

---

## Environment Variables

The table below outlines key configuration options, their types, defaults, and descriptions:

| Variable | Type | Default | Description |
|---|---|---|---|
| `CAREFOLD_WORKSPACE_ROOT` | `Path` | Root directory | Absolute path to the repository workspace containing `agents/`, `skills/`, and `attachments/`. |
| `CAREFOLD_HOME_DIR` | `Path` | `~/.carefold` | Per-user runtime directory storing `carefold.db`, partitioned CAS blobs, and logs. |
| `CAREFOLD_BACKEND_PORT` | `int` | `8010` | Default HTTP port for the FastAPI backend server. |
| `CAREFOLD_WEB_PORT` | `int` | `3010` | Default HTTP port for the Next.js web application. |
| `CAREFOLD_OLLAMA_URL` | `str` | `http://127.0.0.1:11434/v1` | Base URL for the local Ollama inference service (OpenAI-compatible v1 endpoint). |
| `CAREFOLD_DEFAULT_MODEL` | `str` | `llama3.2` | Default LLM model identifier for agent execution. |
| `CAREFOLD_MODEL_TIMEOUT_SECONDS`| `float` | `30.0` | Timeout in seconds for LLM model inference requests. |
| `CAREFOLD_LOG_LEVEL` | `str` | `INFO` | Logging verbosity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `CAREFOLD_LOG_JSON` | `bool` | `false` | When `true`, emits structured JSON log entries. |
| `CAREFOLD_AUDIT_LOG_PATH` | `Path` | `logs/audit.jsonl` | Filepath where structured zero-body audit events are written. |
| `CAREFOLD_AUDIT_STORE_BODIES` | `bool` | `false` | When `false` (recommended), redacts prompts and completion bodies in audit logs to protect PII. |
| `CAREFOLD_MEMORY_BACKEND` | `str` | `sqlite` | Cognitive memory backend adapter (`sqlite` or `spector`). |
| `CAREFOLD_SPECTOR_URL` | `str` | `http://localhost:7070` | Endpoint URL for Spector MCP cognitive memory integration. |
| `CAREFOLD_CORS_ORIGINS` | `List[str]` | `["http://localhost:3010", "http://127.0.0.1:3010", "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8010", "http://127.0.0.1:8010"]` | Allowed CORS origins for browser web requests. |

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

# CORS Allowed Origins
CAREFOLD_CORS_ORIGINS=["http://localhost:3010", "http://127.0.0.1:3010", "http://localhost:8010", "http://127.0.0.1:8010"]
```

---

## Conversation Checkpoint Encryption

Chat threads are saved as checkpoints in `checkpoints.db`. Carefold encrypts new
checkpoints at rest by default (AES-256-GCM, key derived from the vault key).
This is separate from audit logging (`CAREFOLD_AUDIT_STORE_BODIES`) and from
long-term memory settings; changing one does not change the others.

| Variable | Default | Description |
|---|---|---|
| `CAREFOLD_CHECKPOINT_ENCRYPTION` | `true` | Encrypt checkpoints at rest. Set `false` to opt out explicitly. |
| `CAREFOLD_CHECKPOINT_PLAINTEXT_READS` | `true` | Keep reading checkpoints written before encryption. Turn off after migrating. |
| `CAREFOLD_CHECKPOINT_KEY_VERSION` | `1` | Active checkpoint key version (raise it to rotate keys). |

The checkpoint key comes from the vault key (KEK). Carefold looks for it in this
order: the OS keychain entry, `CAREFOLD_VAULT_KEK_FILE`, then
`CAREFOLD_VAULT_PASSPHRASE` (with `CAREFOLD_VAULT_SALT`). With encryption on and
no vault key, a chat turn fails with an error instead of saving plaintext.

### Containers (Docker Compose, Helm)

Containers run with `CAREFOLD_MODE=server`: the vault key is read only from the
file in `CAREFOLD_VAULT_KEK_FILE` (64 hex characters or 32 raw bytes), and with
encryption on the backend refuses to start without it, with a message naming
these settings. Generate the key once with `openssl rand -hex 32` and back it up;
if it is lost or replaced, saved chats can no longer be read.

- **Docker Compose:** put `CAREFOLD_VAULT_KEK=<64 hex characters>` in
  `deploy/docker/.env` (start from `deploy/docker/.env.example`). Compose mounts
  it as the secret file `/run/secrets/carefold_vault_kek`, so it never appears in
  the container environment. Without it, `docker compose up` stops with
  `environment variable "CAREFOLD_VAULT_KEK" required by secret ... is not set`.
- **Helm:** create a Secret once and pass its name; the chart refuses to render
  without it (see `deploy/helm/carefold/README.md`):

  ```bash
  kubectl -n carefold create secret generic carefold-vault-kek \
    --from-literal=kek="$(openssl rand -hex 32)"
  helm install carefold deploy/helm/carefold -n carefold \
    --set vault.existingSecret=carefold-vault-kek
  ```

- **Single container (`docker run`):** mount a key file and point at it:
  `-v "$PWD/carefold-vault.kek:/run/secrets/carefold_vault_kek:ro"
  -e CAREFOLD_MODE=server -e CAREFOLD_VAULT_KEK_FILE=/run/secrets/carefold_vault_kek`.

To store chats unencrypted instead, set `CAREFOLD_CHECKPOINT_ENCRYPTION=false`
(Helm: `--set checkpoints.encryption=false`). Nothing turns encryption off for you.

### Migrating existing chats

To encrypt threads saved before encryption was on, back up `checkpoints.db`, then run:

```bash
python -m carefold.checkpoints status    # count plaintext and encrypted rows
python -m carefold.checkpoints encrypt   # writes checkpoints.db.bak-<time> first
python -m carefold.checkpoints verify    # every thread loads; same messages
```

`encrypt` checks that every thread has the same messages before and after. When
that check passes and no plaintext rows are left, it deletes the plaintext
`.bak-<time>` copy it wrote and reports `backup_deleted: true`. If the check
fails, the command exits with an error and keeps the copy so you can restore it.
Pass `--keep-backup` to keep the copy anyway, and delete it yourself later: it
holds your chats unencrypted. `decrypt` reverses the migration. Pass `--db <path>` for a non-default
database and `--json` for a machine-readable report. Checkpoint metadata is not
encrypted.

---

## Multi-Provider Support

While Carefold defaults to local Ollama inference for maximum patient privacy, the engine supports external LLM providers via standard environment variables or the in-app **Settings → Model & Provider** panel (`/settings/model`):

### 1. Ollama (Default Local)
- No API key required.
- Set `CAREFOLD_OLLAMA_URL` (default: `http://127.0.0.1:11434/v1`).
- Supported models: `llama3.2`, `llama3.1`, `mistral`, `deepseek-r1`, `phi3`.

### 2. Google Gemini
```bash
export GOOGLE_API_KEY="your-google-api-key"
export CAREFOLD_DEFAULT_MODEL="gemini-2.0-flash"
```

### 3. Anthropic Claude
```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export CAREFOLD_DEFAULT_MODEL="claude-3-5-sonnet-latest"
```

### 4. OpenAI
```bash
export OPENAI_API_KEY="your-openai-api-key"
export CAREFOLD_DEFAULT_MODEL="gpt-4o"
```

---

## Web App Environment Variables (`frontend/`)

The Next.js web application (`frontend/`) reads the following environment variables:

| Variable | Type | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | `str` | `http://127.0.0.1:8010` | Base URL of the Carefold FastAPI backend that the web app's server routes proxy to. |
| `CAREFOLD_WORKSPACE` | `Path` | Detected automatically | Location of the repository workspace. |
