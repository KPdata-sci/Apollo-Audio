resource "kubernetes_persistent_volume_claim" "postgres_data" {
  # local-path (both k3s's and this cluster's default) uses WaitForFirstConsumer
  # binding mode — the PV is only actually provisioned once a pod that mounts
  # this PVC gets scheduled. Terraform's default wait_until_bound=true would
  # otherwise block forever waiting for "Bound" before creating the deployment
  # that's the only thing that can ever cause that binding to happen.
  wait_until_bound = false

  metadata {
    name      = "postgres-data"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class
    resources {
      requests = { storage = "5Gi" }
    }
  }
}

resource "kubernetes_deployment" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "postgres" }
    }
    template {
      metadata {
        labels = { app = "postgres" }
      }
      spec {
        container {
          name  = "postgres"
          image = "postgres:16-alpine"

          env_from {
            secret_ref { name = kubernetes_secret.apollo.metadata[0].name }
          }

          port {
            container_port = 5432
          }

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/postgresql/data"
          }
          volume_mount {
            name       = "init"
            mount_path = "/docker-entrypoint-initdb.d"
          }

          resources {
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "1"
              memory = "1Gi"
            }
          }

          readiness_probe {
            exec {
              command = ["pg_isready", "-U", var.postgres_user]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
          }
        }

        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.postgres_data.metadata[0].name
          }
        }
        volume {
          name = "init"
          config_map {
            name = kubernetes_config_map.postgres_init.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    selector = { app = "postgres" }
    port {
      port        = 5432
      target_port = 5432
    }
    # ClusterIP (the default) — deliberately not exposed outside the cluster,
    # same "never expose Postgres publicly" rule as the docker-compose setup.
    type = "ClusterIP"
  }
}
