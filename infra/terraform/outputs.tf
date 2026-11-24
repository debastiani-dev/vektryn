output "artifact_registry_repo" {
  description = "Docker image repository URI"
  value       = module.storage.artifact_registry_uri
}

output "control_plane_url" {
  description = "Cloud Run URL for Django Control Plane"
  value       = module.cloud_run.control_plane_url
}

output "stream_edge_url" {
  description = "Cloud Run URL for FastAPI Stream Edge"
  value       = module.cloud_run.stream_edge_url
}

output "frontend_url" {
  description = "Cloud Run URL for Vektryn Frontend"
  value       = module.cloud_run.frontend_url
}

output "domain_mapping_dns_records" {
  description = "DNS records to configure on debastiani.dev for vektryn.debastiani.dev"
  value       = module.cloud_run.domain_mapping_records
}

output "wif_provider_name" {
  description = "Workload Identity Federation provider resource name for GitHub Actions"
  value       = module.iam.wif_provider_name
}

output "deployer_sa_email" {
  description = "Service account email impersonated by GitHub Actions deploy-gcp.yml"
  value       = module.iam.deployer_sa_email
}

output "migrate_job_name" {
  description = "Cloud Run Job name for Django database migrations"
  value       = module.cloud_run.migrate_job_name
}

output "scheduled_job_names" {
  description = "Cloud Run Job names triggered by Cloud Scheduler"
  value       = module.cloud_run.scheduled_job_names
}

output "wif_provider_name" {
  description = "Workload Identity Federation provider resource name for GitHub Actions"
  value       = module.iam.wif_provider_name
}

output "deployer_sa_email" {
  description = "Service account email impersonated by GitHub Actions deploy-gcp.yml"
  value       = module.iam.deployer_sa_email
}

output "migrate_job_name" {
  description = "Cloud Run Job name for Django database migrations"
  value       = module.cloud_run.migrate_job_name
}

output "scheduled_job_names" {
  description = "Cloud Run Job names triggered by Cloud Scheduler"
  value       = module.cloud_run.scheduled_job_names
}
