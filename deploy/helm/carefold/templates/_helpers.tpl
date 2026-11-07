{{- define "carefold.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "carefold.fullname" -}}
{{- printf "%s" (include "carefold.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "carefold.labels" -}}
app.kubernetes.io/name: {{ include "carefold.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{/*
Name of the Secret holding the vault key. Required while checkpoint
encryption is on; the chart never generates it.
*/}}
{{- define "carefold.vaultSecretName" -}}
{{- required "vault.existingSecret is required: chats are saved encrypted and need a vault key. Create it once with: kubectl -n <namespace> create secret generic carefold-vault-kek --from-literal=kek=\"$(openssl rand -hex 32)\" and set vault.existingSecret=carefold-vault-kek (or set checkpoints.encryption=false to store chats unencrypted)" .Values.vault.existingSecret -}}
{{- end }}
