terraform {
  required_version = ">= 1.6.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.29.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.13.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5.0"
    }
  }
}

resource "kubernetes_namespace_v1" "this" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/name" = "carefold"
    }
  }
}

# Vault key (KEK) for encrypted chats. Unless vault_kek_secret_name names a
# Secret you manage, the module generates one key and keeps it stable in the
# Terraform state (mark the state as sensitive). Replacing or destroying it
# makes saved chats unreadable.
locals {
  create_vault_kek = var.checkpoint_encryption && var.vault_kek_secret_name == ""
  vault_kek_secret = local.create_vault_kek ? kubernetes_secret_v1.vault_kek[0].metadata[0].name : var.vault_kek_secret_name
}

resource "random_id" "vault_kek" {
  count       = local.create_vault_kek ? 1 : 0
  byte_length = 32
}

resource "kubernetes_secret_v1" "vault_kek" {
  count = local.create_vault_kek ? 1 : 0
  metadata {
    name      = "${var.release_name}-vault-kek"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  data = {
    kek = random_id.vault_kek[0].hex
  }
}

resource "helm_release" "carefold" {
  name       = var.release_name
  namespace  = kubernetes_namespace_v1.this.metadata[0].name
  chart      = var.chart_path
  version    = var.chart_version

  values = [
    yamlencode({
      image = {
        repository = var.image_repository
        tag        = var.image_tag
        digest     = var.image_digest
      }
      replicaCount = var.replica_count
      persistence = {
        enabled = true
        size    = var.pvc_size
      }
      model = {
        baseUrl = var.model_base_url
        name    = var.model_name
      }
      ingress = {
        enabled = var.ingress_enabled
        host    = var.ingress_host
      }
      checkpoints = {
        encryption = var.checkpoint_encryption
      }
      vault = {
        existingSecret = var.checkpoint_encryption ? local.vault_kek_secret : ""
        secretKey      = var.checkpoint_encryption && var.vault_kek_secret_name != "" ? var.vault_kek_secret_key : "kek"
      }
      config = {
        allowClinical     = false
        auditStoreBodies  = false
        telemetry         = false
      }
    })
  ]
}
