terraform {
  required_version = ">= 1.5"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
  }
}

# Points at whatever cluster your current kubectl context points at. On the
# target PC (after installing k3s) that's usually /etc/rancher/k3s/k3s.yaml —
# copy it to your own machine and set KUBECONFIG, or run terraform directly on
# the PC itself. See infra/terraform-k8s/README.md for the full setup.
provider "kubernetes" {
  config_path = var.kubeconfig_path
}

resource "kubernetes_namespace" "apollo" {
  metadata {
    name = "apollo"
  }
}
