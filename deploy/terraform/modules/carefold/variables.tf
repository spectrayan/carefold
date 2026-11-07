variable "namespace" {
  type        = string
  default     = "carefold"
  description = "Kubernetes namespace created by this module."
}

variable "release_name" {
  type    = string
  default = "carefold"
}

variable "chart_path" {
  type        = string
  description = "Path to the carefold Helm chart on disk."
}

variable "chart_version" {
  type    = string
  default = "0.1.0"
}

variable "image_repository" {
  type    = string
  default = "carefold"
}

variable "image_tag" {
  type    = string
  default = "dev"
}

variable "image_digest" {
  type    = string
  default = ""
}

variable "replica_count" {
  type    = number
  default = 1
}

variable "pvc_size" {
  type    = string
  default = "10Gi"
}

variable "model_base_url" {
  type        = string
  default     = "http://127.0.0.1:11434/v1"
  description = "OpenAI-compatible base URL. Default is local Ollama."
}

variable "model_name" {
  type    = string
  default = "llama3.2"
}

variable "ingress_enabled" {
  type    = bool
  default = false
}

variable "ingress_host" {
  type    = string
  default = ""
}

variable "checkpoint_encryption" {
  type        = bool
  default     = true
  description = "Encrypt saved chats at rest. false stores them unencrypted (explicit opt-out)."
}

variable "vault_kek_secret_name" {
  type        = string
  default     = ""
  description = "Existing Secret in the namespace holding the vault key (64 hex chars). Empty: the module generates one and keeps it in Terraform state."
}

variable "vault_kek_secret_key" {
  type        = string
  default     = "kek"
  description = "Key inside vault_kek_secret_name that holds the vault key."
}
