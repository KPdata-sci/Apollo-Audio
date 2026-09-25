# Scheduled ingestion — runs the same fetch/parse/lake/warehouse pipeline as
# POST /scrape (see scraper/app/pipeline.py), against the fixed URL list in
# var.ingest_urls, on a timer instead of on demand. Uses the same image as
# the api Deployment with a different container command, so there's nothing
# new to build or push.
resource "kubernetes_cron_job_v1" "ingest" {
  metadata {
    name      = "ingest"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    schedule = var.ingest_schedule
    # A slow run (a stuck/slow page) must finish before the next fires —
    # same one-Playwright-at-a-time reasoning as api.tf's replicas=1.
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 3
    failed_jobs_history_limit     = 3

    job_template {
      metadata {}
      spec {
        backoff_limit = 0 # ingest.py already retries per-URL fetches and skips failures — a whole-Job retry would just re-run every URL again
        template {
          metadata {
            labels = { app = "ingest" }
          }
          spec {
            restart_policy = "Never"

            container {
              name  = "ingest"
              image = var.scraper_image
              # Hand-imported into containerd, not pulled from a registry —
              # same reasoning as the api/frontend Deployments in api.tf/frontend.tf.
              image_pull_policy = "Never"
              command           = ["python", "-m", "app.ingest"]

              env {
                name  = "APOLLO_LAKE_PATH"
                value = "/data/lake"
              }
              env {
                name  = "APOLLO_LOG_DIR"
                value = "/data/logs"
              }
              env {
                name = "APOLLO_WAREHOUSE_DSN"
                value_from {
                  secret_key_ref {
                    name = kubernetes_secret.apollo.metadata[0].name
                    key  = "WAREHOUSE_DSN"
                  }
                }
              }
              env {
                name  = "APOLLO_INGEST_URLS"
                value = var.ingest_urls
              }

              volume_mount {
                name       = "data"
                mount_path = "/data/lake"
                sub_path   = "lake"
              }
              volume_mount {
                name       = "data"
                mount_path = "/data/logs"
                sub_path   = "logs"
              }

              resources {
                # Sized the same as the api Deployment — this also drives a
                # full Playwright/Firefox session per URL.
                requests = {
                  cpu    = "250m"
                  memory = "512Mi"
                }
                limits = {
                  cpu    = "2"
                  memory = "2Gi"
                }
              }
            }

            volume {
              name = "data"
              persistent_volume_claim {
                # Same PVC the api Deployment writes to (RWO, but this is a
                # single-node cluster, so both pods mounting it is fine —
                # RWO restricts to one *node*, not one pod, for a hostPath-
                # backed local-path volume like this one) — so scheduled and
                # on-demand scrapes land in the same lake/warehouse.
                claim_name = kubernetes_persistent_volume_claim.apollo_data.metadata[0].name
              }
            }
          }
        }
      }
    }
  }
}
