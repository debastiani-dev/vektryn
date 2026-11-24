variable "project_id" { type = string }
variable "snapshots_bucket" { type = string }
variable "resumes_bucket" { type = string }
variable "secret_ids" { type = map(string) }

resource "google_service_account" "control_plane" {
  account_id   = "vektryn-control-plane"
  display_name = "Vektryn Control Plane Service Account"
  project      = var.project_id
}

resource "google_service_account" "stream_edge" {
  account_id   = "vektryn-stream-edge"
  display_name = "Vektryn Stream Edge & Workers Service Account"
  project      = var.project_id
}

resource "google_service_account" "frontend" {
  account_id   = "vektryn-frontend"
  display_name = "Vektryn Frontend Service Account"
  project      = var.project_id
}

resource "google_service_account" "scheduler" {
  account_id   = "vektryn-scheduler"
  display_name = "Vektryn Cloud Scheduler Invoker Service Account"
  project      = var.project_id
}

# GCS Permissions
resource "google_storage_bucket_iam_member" "control_plane_resumes" {
  bucket = var.resumes_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.control_plane.email}"
}

resource "google_storage_bucket_iam_member" "stream_edge_snapshots" {
  bucket = var.snapshots_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.stream_edge.email}"
}

resource "google_storage_bucket_iam_member" "stream_edge_resumes_read" {
  bucket = var.resumes_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.stream_edge.email}"
}

# Secret Manager Permissions
locals {
  control_plane_secrets = [
    "vektryn-django-secret-key",
    "vektryn-database-url",
    "vektryn-redis-url",
    "vektryn-kafka-bootstrap",
    "vektryn-gemini-api-key",
    "vektryn-stream-auth-secret",
  ]
  stream_edge_secrets = [
    "vektryn-database-url",
    "vektryn-redis-url",
    "vektryn-kafka-bootstrap",
    "vektryn-gemini-api-key",
    "vektryn-ingest-api-key",
    "vektryn-stream-auth-secret",
  ]
}

resource "google_secret_manager_secret_iam_member" "control_plane_secrets" {
  for_each  = toset(local.control_plane_secrets)
  project   = var.project_id
  secret_id = var.secret_ids[each.value]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.control_plane.email}"
}

resource "google_secret_manager_secret_iam_member" "stream_edge_secrets" {
  for_each  = toset(local.stream_edge_secrets)
  project   = var.project_id
  secret_id = var.secret_ids[each.value]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.stream_edge.email}"
}

output "control_plane_sa_email" { value = google_service_account.control_plane.email }
output "stream_edge_sa_email" { value = google_service_account.stream_edge.email }
output "frontend_sa_email" { value = google_service_account.frontend.email }
output "scheduler_sa_email" { value = google_service_account.scheduler.email }