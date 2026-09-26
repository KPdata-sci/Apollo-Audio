resource "kubernetes_persistent_volume_claim" "apollo_data" {
  # See the matching comment on postgres_data in postgres.tf — local-path's
  # WaitForFirstConsumer binding mode means this can never reach "Bound"
  # before the api Deployment (the only thing that mounts it) is created.
  wait_until_bound = false

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

# Standalone API (scraper/) — JSON endpoints only, no static files. Decoupled
# from the front end (see frontend.tf) so each can be scaled/exposed
# independently, e.g. the API reachable over Tailscale while the front end
# sits behind something else, or vice versa.
resource "kubernetes_deployment" "api" {
  metadata {
    name      = "api"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    replicas = 1 # keep at 1 — Playwright scrapes aren't designed to run concurrently across replicas
    selector {
      match_labels = { app = "api" }
    }
    template {
      metadata {
        labels = { app = "api" }
      }
      spec {
        # fs_group makes Kubernetes chown the mounted PVC to this GID the
        # first time it's mounted — the standard k8s-native fix for a
        # non-root container writing to a volume that was created (and thus
        # owned by root) before this container ever ran, without a manual
        # initContainer. Matches the scraper image's own `pwuser` (uid/gid
        # 1000, verified) that the Dockerfile now runs as.
        security_context {
          fs_group = 1000
        }
        container {
          name  = "api"
          image = var.scraper_image
          # These images are hand-imported into containerd (docker save |
          # k3s ctr images import), not pulled from a real registry — the
          # default pull policy for a ":latest"-tagged image is "Always",
          # which would make the kubelet try (and fail) to re-pull
          # "docker.io/library/..." from the real Docker Hub on every restart.
          image_pull_policy = "Never"

          security_context {
            run_as_user  = 1000
            run_as_group = 1000
          }

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
            name = "APOLLO_API_KEY"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.apollo.metadata[0].name
                key  = "API_KEY"
              }
            }
          }
          env {
            name = "APOLLO_JWT_SECRET"
            value_from {
              secret_key_ref {
                name = kubernetes_secret.apollo.metadata[0].name
                key  = "JWT_SECRET"
              }
            }
          }
          env {
            name  = "APOLLO_JWT_EXPIRE_DAYS"
            value = tostring(var.jwt_expire_days)
          }
          env {
            name  = "APOLLO_CORS_ORIGINS"
            value = var.cors_origins
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

          resources {
            # Playwright driving a real Firefox instance per scrape is the
            # heaviest part of this app (same note as docs/PUBLIC_ACCESS_DESIGN.md's
            # VPS sizing) — the limit here is sized for that, not the idle API.
            requests = {
              cpu    = "250m"
              memory = "512Mi"
            }
            limits = {
              cpu    = "2"
              memory = "2Gi"
            }
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8000
            }
            initial_delay_seconds = 5
            period_seconds        = 10
          }
          liveness_probe {
            http_get {
              path = "/health"
              port = 8000
            }
            initial_delay_seconds = 15
            period_seconds        = 20
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

resource "kubernetes_service" "api" {
  metadata {
    name      = "api"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    selector = { app = "api" }
    port {
      port        = 8000
      target_port = 8000
      node_port   = var.expose_via == "nodeport" ? 30800 : null
    }
    type = var.expose_via == "nodeport" ? "NodePort" : (var.expose_via == "loadbalancer" ? "LoadBalancer" : "ClusterIP")
  }
}
