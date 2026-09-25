# Standalone static front end (frontend/Dockerfile — nginx + the same
# scraper/app/static/index.html, talking to the api Service over the network
# instead of relying on same-origin relative fetches).
resource "kubernetes_deployment" "frontend" {
  metadata {
    name      = "frontend"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "frontend" }
    }
    template {
      metadata {
        labels = { app = "frontend" }
      }
      spec {
        container {
          name  = "frontend"
          image = var.frontend_image
          # See the matching comment on the api container in api.tf — this
          # image is hand-imported into containerd, not pulled from a registry.
          image_pull_policy = "Never"

          env {
            name  = "API_BASE_URL"
            value = var.api_base_url
          }

          port {
            container_port = 80
          }

          resources {
            requests = {
              cpu    = "25m"
              memory = "32Mi"
            }
            limits = {
              cpu    = "250m"
              memory = "128Mi"
            }
          }

          readiness_probe {
            http_get {
              path = "/"
              port = 80
            }
            initial_delay_seconds = 2
            period_seconds        = 10
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "frontend" {
  metadata {
    name      = "frontend"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }
  spec {
    selector = { app = "frontend" }
    port {
      port        = 80
      target_port = 80
      node_port   = var.expose_via == "nodeport" ? 30880 : null
    }
    type = var.expose_via == "nodeport" ? "NodePort" : (var.expose_via == "loadbalancer" ? "LoadBalancer" : "ClusterIP")
  }
}
