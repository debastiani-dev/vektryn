variable "project_id" { type = string }
variable "region" { type = string }
variable "zone" { type = string }
variable "machine_type" { type = string }
variable "internal_ip" { type = string }
variable "labels" { type = map(string) }
variable "vpc_network_id" { type = string }
variable "vpc_subnetwork_id" { type = string }
variable "stream_edge_sa_email" { type = string }
variable "deployer_sa_email" { type = string }
variable "stream_edge_latest_image" { type = string }
variable "snapshots_bucket_name" { type = string }

resource "google_compute_address" "data_node_internal" {
  name         = "vektryn-data-node-ip"
  project      = var.project_id
  region       = var.region
  subnetwork   = var.vpc_subnetwork_id
  address_type = "INTERNAL"
  address      = var.internal_ip
}

resource "google_compute_firewall" "allow_internal_data" {
  name    = "vektryn-allow-internal-data"
  project = var.project_id
  network = var.vpc_network_id

  allow {
    protocol = "tcp"
    ports    = ["5432", "6379", "9092"]
  }

  source_ranges = ["10.8.0.0/24"]
  target_tags   = ["vektryn-data-node"]
}

resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "vektryn-allow-iap-ssh"
  project = var.project_id
  network = var.vpc_network_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # GCP Identity-Aware Proxy (IAP) TCP forwarding range only — zero public SSH
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["vektryn-data-node"]
}

resource "google_compute_instance" "data_node" {
  name                      = "vektryn-data-node"
  project                   = var.project_id
  zone                      = var.zone
  machine_type              = var.machine_type
  tags                      = ["vektryn-data-node"]
  labels                    = var.labels
  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = var.vpc_subnetwork_id
    network_ip = google_compute_address.data_node_internal.address

    # Ephemeral external IP for outbound image pulls & Gemini API (zero Cloud NAT cost; ingress blocked by firewall)
    access_config {}
  }

  service_account {
    email  = var.stream_edge_sa_email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = templatefile("${path.module}/startup.sh.tftpl", {
      project_id               = var.project_id
      region                   = var.region
      internal_ip              = var.internal_ip
      stream_edge_latest_image = var.stream_edge_latest_image
      snapshots_bucket_name    = var.snapshots_bucket_name
    })
  }

  lifecycle {
    ignore_changes = [boot_disk[0].initialize_params[0].image]
  }
}

resource "google_iap_tunnel_instance_iam_member" "deployer_iap_tunnel" {
  project  = var.project_id
  zone     = var.zone
  instance = google_compute_instance.data_node.name
  role     = "roles/iap.tunnelResourceAccessor"
  member   = "serviceAccount:${var.deployer_sa_email}"
}

resource "google_compute_instance_iam_member" "deployer_os_admin_login" {
  project       = var.project_id
  zone          = var.zone
  instance_name = google_compute_instance.data_node.name
  role          = "roles/compute.osAdminLogin"
  member        = "serviceAccount:${var.deployer_sa_email}"
}

output "internal_ip" { value = google_compute_address.data_node_internal.address }
output "instance_name" { value = google_compute_instance.data_node.name }
output "instance_zone" { value = google_compute_instance.data_node.zone }
