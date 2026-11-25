variable "project_id" { type = string }
variable "labels" { type = map(string) }

locals {
  secret_names = toset([
    "vektryn-django-secret-key",
    "vektryn-database-url",
    "vektryn-redis-url",
    "vektryn-kafka-bootstrap",
    "vektryn-gemini-api-key",
    "vektryn-ingest-api-key",
    "vektryn-stream-auth-secret",
    "vektryn-sentry-dsn",
  ])
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secret_names
  project   = var.project_id
  secret_id = each.value
  labels    = var.labels

  replication {
    auto {}
  }
}

output "secret_ids" {
  value = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}