variable "project_id" { type = string }
variable "github_repo" { type = string }
variable "snapshots_bucket" { type = string }
variable "resumes_bucket" { type = string }
variable "db_backups_bucket" { type = string }
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

resource "google_storage_bucket_iam_member" "stream_edge_db_backups" {
  bucket = var.db_backups_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.stream_edge.email}"
}

resource "google_project_iam_member" "stream_edge_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.stream_edge.email}"
}

# Secret Manager Permissions
locals {
  control_plane_secrets = [
    "vektryn-django-secret-key",
    "vektryn-database-url",
    "vektryn-redis-url",
    "vektryn-kafka-bootstrap",
    "vektryn-byok-encryption-key",
    "vektryn-ingest-api-key",
    "vektryn-stream-auth-secret",
    "vektryn-sentry-dsn",
  ]
  stream_edge_secrets = [
    "vektryn-database-url",
    "vektryn-redis-url",
    "vektryn-kafka-bootstrap",
    "vektryn-gemini-api-key",
    "vektryn-byok-encryption-key",
    "vektryn-ingest-api-key",
    "vektryn-stream-auth-secret",
    "vektryn-sentry-dsn",
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

# GitHub Actions Workload Identity Federation (keyless OIDC deploys from main)
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "vektryn-github-pool"
  display_name              = "Vektryn GitHub Actions Pool"
  description               = "OIDC pool for GitHub Actions deployments"
}

resource "google_iam_workload_identity_pool_provider" "github_actions" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC Provider"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  attribute_condition = "assertion.repository == '${var.github_repo}' && assertion.ref == 'refs/heads/main'"
}

resource "google_service_account" "deployer" {
  account_id   = "vektryn-deployer"
  display_name = "Vektryn GitHub Actions Deployer"
  project      = var.project_id
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

locals {
  deployer_roles = toset([
    "roles/viewer",
    "roles/iam.securityReviewer",
    "roles/serviceusage.serviceUsageViewer",
    "roles/run.admin",
    "roles/artifactregistry.repoAdmin",
    "roles/iam.serviceAccountUser",
    "roles/storage.admin",
    "roles/cloudscheduler.admin",
    "roles/secretmanager.viewer",
    "roles/compute.networkAdmin",
    "roles/compute.instanceAdmin.v1",
    "roles/compute.securityAdmin",
  ])
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = local.deployer_roles
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

output "control_plane_sa_email" { value = google_service_account.control_plane.email }
output "stream_edge_sa_email" { value = google_service_account.stream_edge.email }
output "frontend_sa_email" { value = google_service_account.frontend.email }
output "scheduler_sa_email" { value = google_service_account.scheduler.email }
output "wif_provider_name" { value = google_iam_workload_identity_pool_provider.github_actions.name }
output "deployer_sa_email" { value = google_service_account.deployer.email }
