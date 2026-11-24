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

variable "data_vm_machine_type" {
  description = "GCE machine type for private Postgres/Redis/Kafka/Workers VM (e2-micro is Always Free in us-central1)"
  type        = string
  default     = "e2-micro"
}

variable "data_vm_zone" {
  description = "GCE zone for private data/worker VM"
  type        = string
  default     = "us-central1-a"
}

variable "data_vm_internal_ip" {
  description = "Static internal VPC IP for private Postgres/Redis/Kafka VM inside 10.8.0.0/24"
  type        = string
  default     = "10.8.0.10"
}
