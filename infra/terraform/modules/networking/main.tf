variable "project_id" { type = string }
variable "region" { type = string }
variable "domain_name" { type = string }
variable "labels" { type = map(string) }

resource "google_compute_network" "vektryn_vpc" {
  name                    = "vektryn-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "cloud_run_subnet" {
  name                     = "vektryn-cloudrun-subnet"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.vektryn_vpc.id
  ip_cidr_range            = "10.8.0.0/24"
  private_ip_google_access = true
}

output "vpc_network_id" { value = google_compute_network.vektryn_vpc.id }
output "vpc_subnetwork_id" { value = google_compute_subnetwork.cloud_run_subnet.id }