resource "kubernetes_persistent_volume_claim" "apollo_data" {
  metadata {
    name      = "apollo-data"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class
    resources {
      requests = { storage = "5Gi" } # data lake + logs
    }
  }
}

resource "kubernetes_deployment" "scraper" {
  metadata {
    name      = "scraper"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    replicas = 1 # keep at 1 — Playwright scrapes aren't designed to run concurrently across replicas
    selector {
      match_labels = { app = "scraper" }
    }
    template {
      metadata {
        labels = { app = "scraper" }
      }
      spec {
        container {
          name  = "scraper"
          image = var.scraper_image

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

          port {
            container_port = 8000
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

          readiness_probe {
            http_get {
              path = "/health"
              port = 8000
            }
            initial_delay_seconds = 5
            period_seconds        = 10
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

resource "kubernetes_service" "scraper" {
  metadata {
    name      = "scraper"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    selector = { app = "scraper" }
    port {
      port        = 8000
      target_port = 8000
      node_port   = var.expose_scraper_via == "nodeport" ? 30800 : null
    }
    type = var.expose_scraper_via == "nodeport" ? "NodePort" : "ClusterIP"
  }
}
