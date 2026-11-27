variable "project_id" { type = string }
variable "region" { type = string }
variable "labels" { type = map(string) }

resource "google_storage_bucket" "snapshots" {
  name                        = "${var.project_id}-raw-snapshots"
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = var.labels

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "resumes" {
  name                        = "${var.project_id}-resumes"
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false
  labels                      = var.labels
}

resource "google_storage_bucket" "db_backups" {
  name                        = "${var.project_id}-db-backups"
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.labels

  versioning {
    enabled = false
  }

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  lifecycle_rule {
    condition {
      age = 14
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_artifact_registry_repository" "vektryn" {
  location      = var.region
  project       = var.project_id
  repository_id = "vektryn"
  description   = "Container images for Vektryn services"
  format        = "DOCKER"
  labels        = var.labels

  cleanup_policies {
    id     = "keep-recent-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }
}

output "snapshots_bucket_name" { value = google_storage_bucket.snapshots.name }
output "resumes_bucket_name" { value = google_storage_bucket.resumes.name }
output "db_backups_bucket_name" { value = google_storage_bucket.db_backups.name }
output "artifact_registry_uri" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.vektryn.repository_id}" }