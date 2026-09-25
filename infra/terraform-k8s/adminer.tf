resource "kubernetes_deployment" "adminer" {
  metadata {
    name      = "adminer"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "adminer" }
    }
    template {
      metadata {
        labels = { app = "adminer" }
      }
      spec {
        container {
          name  = "adminer"
          image = "adminer:latest"
          port {
            container_port = 8080
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "adminer" {
  metadata {
    name      = "adminer"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    selector = { app = "adminer" }
    port {
      port        = 8080
      target_port = 8080
    }
    # ClusterIP only, same as Postgres — a raw DB admin UI with no auth of its
    # own has no business being reachable outside the cluster. Reach it with
    # `kubectl port-forward -n apollo svc/adminer 8081:8080` when you need it.
    type = "ClusterIP"
  }
}
