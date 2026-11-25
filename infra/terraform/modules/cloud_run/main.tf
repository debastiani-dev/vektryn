variable "project_id" { type = string }
variable "region" { type = string }
variable "labels" { type = map(string) }
variable "control_plane_image" { type = string }
variable "stream_edge_image" { type = string }
variable "frontend_image" { type = string }
variable "control_plane_sa_email" { type = string }
variable "stream_edge_sa_email" { type = string }
variable "frontend_sa_email" { type = string }
variable "scheduler_sa_email" { type = string }
variable "snapshots_bucket_name" { type = string }
variable "resumes_bucket_name" { type = string }
variable "secret_ids" { type = map(string) }
variable "vpc_network_id" { type = string }
variable "vpc_subnetwork_id" { type = string }
variable "domain_name" { type = string }

resource "google_cloud_run_v2_service" "control_plane" {
  name     = "vektryn-control-plane"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = var.labels

  template {
    service_account = var.control_plane_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    vpc_access {
      network_interfaces {
        network    = var.vpc_network_id
        subnetwork = var.vpc_subnetwork_id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.control_plane_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "DJANGO_DEBUG"
        value = "false"
      }

      env {
        name  = "DJANGO_ALLOWED_HOSTS"
        value = ".run.app,${var.domain_name},localhost,127.0.0.1"
      }

      env {
        name  = "CSRF_TRUSTED_ORIGINS"
        value = "https://${var.domain_name}"
      }

      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = "https://${var.domain_name}"
      }

      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }

      env {
        name  = "GCS_RESUMES_BUCKET"
        value = var.resumes_bucket_name
      }

      env {
        name  = "STREAM_EDGE_URL"
        value = google_cloud_run_v2_service.stream_edge.uri
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "GCP_REGION"
        value = var.region
      }

      env {
        name  = "COLLECTOR_JOB_NAME"
        value = google_cloud_run_v2_job.scheduled_workers["collect"].name
      }

      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-django-secret-key"]
            version = "latest"
          }
        }
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-database-url"]
            version = "latest"
          }
        }
      }

      env {
        name = "REDIS_URL"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-redis-url"]
            version = "latest"
          }
        }
      }

      env {
        name = "KAFKA_BOOTSTRAP_SERVERS"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-kafka-bootstrap"]
            version = "latest"
          }
        }
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-gemini-api-key"]
            version = "latest"
          }
        }
      }

      env {
        name = "INGEST_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-ingest-api-key"]
            version = "latest"
          }
        }
      }

      env {
        name = "STREAM_AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-stream-auth-secret"]
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health/"
          port = 8000
          http_headers {
            name  = "Host"
            value = var.domain_name
          }
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 5
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service" "stream_edge" {
  name     = "vektryn-stream-edge"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = var.labels

  template {
    service_account = var.stream_edge_sa_email
    timeout         = "3600s" # Supports long-lived SSE alert streams

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    vpc_access {
      network_interfaces {
        network    = var.vpc_network_id
        subnetwork = var.vpc_subnetwork_id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.stream_edge_image

      ports {
        container_port = 8001
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "STORAGE_BACKEND"
        value = "gcs"
      }

      env {
        name  = "GCS_SNAPSHOTS_BUCKET"
        value = var.snapshots_bucket_name
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-database-url"]
            version = "latest"
          }
        }
      }

      env {
        name = "REDIS_URL"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-redis-url"]
            version = "latest"
          }
        }
      }

      env {
        name = "KAFKA_BOOTSTRAP_SERVERS"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-kafka-bootstrap"]
            version = "latest"
          }
        }
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-gemini-api-key"]
            version = "latest"
          }
        }
      }

      env {
        name = "INGEST_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-ingest-api-key"]
            version = "latest"
          }
        }
      }

      env {
        name = "STREAM_AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["vektryn-stream-auth-secret"]
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8001
        }
        initial_delay_seconds = 3
        period_seconds        = 10
        failure_threshold     = 5
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service" "frontend" {
  name     = "vektryn-frontend"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = var.labels

  template {
    service_account = var.frontend_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.frontend_image

      ports {
        container_port = 80
      }

      env {
        name  = "CONTROL_PLANE_URL"
        value = google_cloud_run_v2_service.control_plane.uri
      }

      env {
        name  = "STREAM_EDGE_URL"
        value = google_cloud_run_v2_service.stream_edge.uri
      }

      env {
        name  = "NGINX_RESOLVER"
        value = "8.8.8.8"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

# Allow public unauthenticated traffic to Cloud Run services
resource "google_cloud_run_v2_service_iam_member" "public_invokers" {
  for_each = {
    control_plane = google_cloud_run_v2_service.control_plane.name
    stream_edge   = google_cloud_run_v2_service.stream_edge.name
    frontend      = google_cloud_run_v2_service.frontend.name
  }

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Custom domain mapping for vektryn.debastiani.dev
resource "google_cloud_run_domain_mapping" "frontend_domain" {
  location = var.region
  name     = var.domain_name
  project  = var.project_id

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.frontend.name
  }
}

# Scheduled Cloud Run Jobs (collectors, daily stack rollup, upstream lifecycle check)
locals {
  scheduled_jobs = {
    collect = {
      name     = "vektryn-collect"
      command  = ["python", "-m", "stream_edge.collectors.run"]
      schedule = "0 */4 * * *"
      timeout  = "900s"
    }
    rollup = {
      name     = "vektryn-rollup"
      command  = ["python", "-m", "stream_edge.workers.rollup"]
      schedule = "0 1 * * *"
      timeout  = "300s"
    }
    lifecycle = {
      name     = "vektryn-lifecycle"
      command  = ["python", "-m", "stream_edge.workers.lifecycle"]
      schedule = "0 3 * * *"
      timeout  = "600s"
    }
  }
}

resource "google_cloud_run_v2_job" "scheduled_workers" {
  for_each = local.scheduled_jobs

  name     = each.value.name
  location = var.region
  project  = var.project_id
  labels   = var.labels

  template {
    template {
      service_account = var.stream_edge_sa_email
      timeout         = each.value.timeout
      max_retries     = 1

      vpc_access {
        network_interfaces {
          network    = var.vpc_network_id
          subnetwork = var.vpc_subnetwork_id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = var.stream_edge_image
        command = each.value.command

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "STREAM_EDGE_URL"
          value = google_cloud_run_v2_service.stream_edge.uri
        }

        env {
          name = "INGEST_API_KEY"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["vektryn-ingest-api-key"]
              version = "latest"
            }
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["vektryn-database-url"]
              version = "latest"
            }
          }
        }

        env {
          name = "REDIS_URL"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["vektryn-redis-url"]
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invokers" {
  for_each = google_cloud_run_v2_job.scheduled_workers

  project  = var.project_id
  location = var.region
  name     = each.value.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_sa_email}"
}

resource "google_cloud_run_v2_job_iam_member" "control_plane_collect_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scheduled_workers["collect"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.control_plane_sa_email}"
}

resource "google_cloud_scheduler_job" "scheduled_worker_triggers" {
  for_each = local.scheduled_jobs

  name        = "${each.value.name}-schedule"
  description = "Triggers Cloud Run Job ${each.value.name}"
  region      = var.region
  project     = var.project_id
  schedule    = each.value.schedule
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scheduled_workers[each.key].name}:run"

    oauth_token {
      service_account_email = var.scheduler_sa_email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_invokers]
}

# One-shot Cloud Run Job for Django database migrations (executed by deploy-gcp.yml)
resource "google_cloud_run_v2_job" "migrate" {
  name     = "vektryn-migrate"
  location = var.region
  project  = var.project_id
  labels   = var.labels

  template {
    template {
      service_account = var.control_plane_sa_email
      timeout         = "300s"
      max_retries     = 1

      vpc_access {
        network_interfaces {
          network    = var.vpc_network_id
          subnetwork = var.vpc_subnetwork_id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = var.control_plane_image
        command = ["python", "manage.py", "migrate", "--noinput"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "DJANGO_DEBUG"
          value = "false"
        }

        env {
          name = "SECRET_KEY"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["vektryn-django-secret-key"]
              version = "latest"
            }
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["vektryn-database-url"]
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

output "control_plane_url" { value = google_cloud_run_v2_service.control_plane.uri }
output "stream_edge_url" { value = google_cloud_run_v2_service.stream_edge.uri }
output "frontend_url" { value = google_cloud_run_v2_service.frontend.uri }
output "domain_mapping_records" { value = google_cloud_run_domain_mapping.frontend_domain.status[0].resource_records }
output "migrate_job_name" { value = google_cloud_run_v2_job.migrate.name }
output "scheduled_job_names" { value = { for k, v in google_cloud_run_v2_job.scheduled_workers : k => v.name } }
