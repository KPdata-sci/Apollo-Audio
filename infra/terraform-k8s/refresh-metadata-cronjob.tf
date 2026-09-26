# Cheap, metadata-only refresh — updates playback_count/likes_count/
# artwork_url for existing tracks without a full rescrape (see
# scraper/app/refresh_metadata.py and docs/SCALING.md's "Popularity data
# goes stale between scrapes"). Same image as the api Deployment and the
# ingest CronJob with a different container command — nothing new to build
# or push.
resource "kubernetes_cron_job_v1" "refresh_metadata" {
  metadata {
    name      = "refresh-metadata"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    schedule                      = var.refresh_metadata_schedule
    concurrency_policy            = "Forbid"
    successful_jobs_history_limit = 3
    failed_jobs_history_limit     = 3

    job_template {
      metadata {}
      spec {
        backoff_limit = 0 # refresh_metadata.py already skips/logs a single bad track — a whole-Job retry would just redo the same batch
        template {
          metadata {
            labels = { app = "refresh-metadata" }
          }
          spec {
            restart_policy = "Never"
            # Matches api.tf's Deployment and ingest-cronjob.tf: this Job's
            # pod writes to the same shared PVC.
            security_context {
              fs_group = 1000
            }

            container {
              name              = "refresh-metadata"
              image             = var.scraper_image
              image_pull_policy = "Never"
              command           = ["python", "-m", "app.refresh_metadata"]

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
                name  = "APOLLO_METADATA_REFRESH_BATCH"
                value = tostring(var.metadata_refresh_batch)
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
                # Same sizing as ingest — a single Playwright/Firefox page
                # load per track, just a lighter (non-scrolling) page.
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
                claim_name = kubernetes_persistent_volume_claim.apollo_data.metadata[0].name
              }
            }
          }
        }
      }
    }
  }
}
