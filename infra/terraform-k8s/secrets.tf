resource "kubernetes_secret" "apollo" {
  metadata {
    name      = "apollo-secrets"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }

  data = {
    POSTGRES_USER     = var.postgres_user
    POSTGRES_PASSWORD = var.postgres_password
    POSTGRES_DB       = var.postgres_db
    WAREHOUSE_DSN     = "postgresql://${var.postgres_user}:${var.postgres_password}@postgres:5432/${var.postgres_db}"
    API_KEY           = var.api_key
    JWT_SECRET        = var.jwt_secret
  }
}

# warehouse/init.sql, mounted into Postgres the same way docker-compose bind-
# mounts it to /docker-entrypoint-initdb.d/init.sql — same file, same effect.
resource "kubernetes_config_map" "postgres_init" {
  metadata {
    name      = "postgres-init"
    namespace = kubernetes_namespace.apollo.metadata[0].name
  }

  data = {
    "init.sql" = file("${path.module}/../../warehouse/init.sql")
  }
}
