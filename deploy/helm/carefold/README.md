# carefold Helm chart

Installs the Carefold runtime on a cluster you already operate.

Chats are saved encrypted, so the chart needs a vault key (KEK) in a
Kubernetes Secret you create once. Back the key up: if it is lost or replaced,
saved chats can no longer be read.

```bash
kubectl create namespace carefold
kubectl -n carefold create secret generic carefold-vault-kek \
  --from-literal=kek="$(openssl rand -hex 32)"

helm install carefold ./helm/carefold -n carefold \
  --set vault.existingSecret=carefold-vault-kek \
  --set model.baseUrl=http://ollama.ollama.svc:11434/v1
```

Without `vault.existingSecret` the chart refuses to render and prints the
commands above. The Secret is mounted read-only as a file
(`CAREFOLD_VAULT_KEK_FILE`), never as an environment variable, and the pod runs
with `CAREFOLD_MODE=server`, so it stops at startup if the key cannot be read.
Use `vault.secretKey` if the key inside the Secret is not `kek`; External
Secrets, Sealed Secrets or a CSI secret store can create the Secret instead.

The chart deliberately does not generate the key: a generated Secret can be
silently replaced by `helm template`, a GitOps render or an uninstall, and every
saved chat would become unreadable. `--set checkpoints.encryption=false` stores
chats unencrypted instead (explicit opt-out; no Secret needed).

The Terraform module in `deploy/terraform/modules/carefold` creates the Secret
for you (key kept in Terraform state) unless you pass `vault_kek_secret_name`.

## Ports, data and model

- The container listens on 8000, the API port of both published images, and
  the probes call `/api/health` there. The Service exposes it as `http` on
  `service.port` (8080). With the all-in-one image, add
  `--set container.webPort=3000` to expose the web UI as `web` on
  `service.webPort`.
- `CAREFOLD_HOME=/data` puts everything Carefold stores (`carefold.db`, saved
  chats, uploads, notes, logs) on the persistent volume.
- `model.baseUrl` and `model.name` become `CAREFOLD_OLLAMA_URL` and
  `CAREFOLD_DEFAULT_MODEL`.

Ingress is off. Do not put this on the public internet with health data
unless you are prepared to be the operator of record.

Pin production images with `image.digest` once releases exist.
