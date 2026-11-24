variable "project_id" {
  description = "GCP Project ID hosting Vektryn"
  type        = string
}

variable "region" {
  description = "Primary GCP region (us-central1 or southamerica-east1)"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment label"
  type        = string
  default     = "prod"
}

variable "domain_name" {
  description = "Primary custom domain for Vektryn frontend/API"
  type        = string
  default     = "vektryn.debastiani.dev"
}

variable "github_repo" {
  description = "GitHub repository (owner/repo) allowed to deploy via Workload Identity Federation"
  type        = string
  default     = "debastiani-dev/vektryn"
}

variable "control_plane_image" {
  description = "Artifact Registry image URI for control-plane"
  type        = string
}

variable "stream_edge_image" {
  description = "Artifact Registry image URI for stream-edge"
  type        = string
}

variable "frontend_image" {
  description = "Artifact Registry image URI for frontend Nginx container"
  type        = string
}