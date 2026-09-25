variable "kubeconfig_path" {
  description = "Path to the kubeconfig for the target cluster (e.g. a copy of the target PC's /etc/rancher/k3s/k3s.yaml)."
  type        = string
  default     = "~/.kube/config"
}

variable "scraper_image" {
  description = "Image reference the cluster can actually pull. A locally-built 'project_apollo-scraper:latest' image (what docker-compose builds) is NOT reachable by the cluster by default — push it to a registry (Docker Hub, GHCR, etc.) or import it directly into the node (see README) and set this to that reference."
  type        = string
}

variable "postgres_user" {
  type    = string
  default = "apollo"
}

variable "postgres_password" {
  description = "Set via terraform.tfvars (gitignored) or TF_VAR_postgres_password — never commit this."
  type        = string
  sensitive   = true
}

variable "postgres_db" {
  type    = string
  default = "apollo"
}

variable "storage_class" {
  description = "k3s ships a default 'local-path' StorageClass out of the box — this works unmodified on a single-node k3s install. Change it if your cluster uses something else."
  type        = string
  default     = "local-path"
}

variable "expose_scraper_via" {
  description = "\"nodeport\" (simplest — reachable at <node-ip>:<nodePort> with no extra setup) or \"ingress\" (uses k3s's built-in Traefik, needs a hostname)."
  type        = string
  default     = "nodeport"
}
