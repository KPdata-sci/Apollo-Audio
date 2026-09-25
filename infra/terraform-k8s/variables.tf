variable "kubeconfig_path" {
  description = "Path to the kubeconfig for the target cluster (e.g. a copy of the target PC's /etc/rancher/k3s/k3s.yaml)."
  type        = string
  default     = "~/.kube/config"
}

variable "scraper_image" {
  description = "Image reference for the standalone API (scraper/ — no longer serves the front end, see frontend_image below). On Docker Desktop's own Kubernetes this can be a plain locally-built tag like 'apolloaudio-api:local' with no registry, since Docker Desktop's cluster shares the same image cache as `docker build` — see README. On k3s (a separate machine) it must be pullable by the cluster: push it to a registry or import it directly into the node (see README)."
  type        = string
}

variable "frontend_image" {
  description = "Image reference for the standalone static front end (frontend/Dockerfile). Same locally-built-tag-works-on-Docker-Desktop caveat as scraper_image applies."
  type        = string
}

variable "api_base_url" {
  description = "Explicit override for the API's full address (e.g. \"https://api.example.com\"). Leave empty (the default) unless you have a reason to hardcode one: with it empty, the frontend instead derives the API's address at runtime from whatever host/IP the browser used to load the page, combined with api_port below — which is what lets the SAME deployment work correctly whether a viewer reaches it via a LAN IP, a Tailscale IP, or a NodePort's raw IP, instead of only whichever one address you hardcoded here."
  type        = string
  default     = ""
}

variable "api_port" {
  description = "The api Service's NodePort, used to derive the API's address as described in api_base_url above (a viewer's browser reaches the API on the same host it loaded the frontend from, just this port). Must match the api Service's node_port in api.tf (30800 by default)."
  type        = string
  default     = "30800"
}

variable "api_key" {
  description = "Shared secret required (via the X-API-Key header) to call POST /scrape and POST /api/discover-playlists. Leave empty only while this stays unreachable outside a fully trusted network — set via terraform.tfvars (gitignored) or TF_VAR_api_key, never commit a real value. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
  type        = string
  sensitive   = true
  default     = ""
}

variable "cors_origins" {
  description = "Comma-separated list of origins allowed to call the API cross-origin (needed because the frontend now runs as a separate Service/origin from the API). Default \"*\" is fine for read endpoints; tighten it to the frontend's actual URL once that's stable."
  type        = string
  default     = "*"
}

variable "ingest_urls" {
  description = "Comma-separated soundcloud.com playlist/profile URLs the scheduled ingest CronJob scrapes automatically (scraper/app/ingest.py). Empty (default) means the CronJob runs and does nothing — pick URLs from the scraper/app/playlists.py catalog or add your own."
  type        = string
  default     = ""
}

variable "ingest_schedule" {
  description = "Standard cron expression for how often the ingest CronJob runs. Default is once a day at 03:00 — SoundCloud scraping is DOM-based (no public API), so keep this infrequent rather than treating it like a real-time feed."
  type        = string
  default     = "0 3 * * *"
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
  description = "k3s ships a default 'local-path' StorageClass out of the box. Docker Desktop's own Kubernetes instead ships one called 'hostpath' — set this to \"hostpath\" in terraform.tfvars when targeting Docker Desktop, or run `kubectl get storageclass` to check what your cluster actually calls its default."
  type        = string
  default     = "local-path"
}

variable "expose_via" {
  description = "How the api and frontend Services are reachable from outside the cluster: \"nodeport\" (fixed ports 30800/30880, works anywhere with no extra setup), \"loadbalancer\" (Docker Desktop auto-assigns 'localhost' as the external IP for LoadBalancer Services — simplest on Docker Desktop specifically), or \"ingress\" (needs an ingress controller installed separately — k3s ships Traefik built in, Docker Desktop does not ship one)."
  type        = string
  default     = "nodeport"
}
