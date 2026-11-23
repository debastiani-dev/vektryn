terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.14"
    }
  }

  # Uncomment after creating your GCS state bucket (or pass -backend-config)
  # backend "gcs" {
  #   bucket = "vektryn-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}