locals {
  required_apis = [
    "run.googleapis.com",
    "compute.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "vpcaccess.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iap.googleapis.com",
    "oslogin.googleapis.com",
  ]

  common_labels = {
    app         = "vektryn"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

module "storage" {
  source     = "./modules/storage"
  project_id = var.project_id
  region     = var.region
  labels     = local.common_labels

  depends_on = [google_project_service.apis]
}

module "secrets" {
  source     = "./modules/secrets"
  project_id = var.project_id
  labels     = local.common_labels

  depends_on = [google_project_service.apis]
}

module "iam" {
  source           = "./modules/iam"
  project_id       = var.project_id
  github_repo      = var.github_repo
  snapshots_bucket = module.storage.snapshots_bucket_name
  resumes_bucket   = module.storage.resumes_bucket_name
  secret_ids       = module.secrets.secret_ids
  depends_on       = [module.storage, module.secrets]
}

module "networking" {
  source      = "./modules/networking"
  project_id  = var.project_id
  region      = var.region
  domain_name = var.domain_name
  labels      = local.common_labels

  depends_on = [google_project_service.apis]
}

module "data_node" {
  source                   = "./modules/data_node"
  project_id               = var.project_id
  region                   = var.region
  zone                     = var.data_vm_zone
  machine_type             = var.data_vm_machine_type
  internal_ip              = var.data_vm_internal_ip
  labels                   = local.common_labels
  vpc_network_id           = module.networking.vpc_network_id
  vpc_subnetwork_id        = module.networking.vpc_subnetwork_id
  stream_edge_sa_email     = module.iam.stream_edge_sa_email
  deployer_sa_email        = module.iam.deployer_sa_email
  stream_edge_latest_image = "${module.storage.artifact_registry_uri}/stream-edge:latest"
  snapshots_bucket_name    = module.storage.snapshots_bucket_name

  depends_on = [module.networking, module.iam, module.storage, module.secrets]
}

module "cloud_run" {
  source                 = "./modules/cloud_run"
  project_id             = var.project_id
  region                 = var.region
  labels                 = local.common_labels
  control_plane_image    = var.control_plane_image
  stream_edge_image      = var.stream_edge_image
  frontend_image         = var.frontend_image
  control_plane_sa_email = module.iam.control_plane_sa_email
  stream_edge_sa_email   = module.iam.stream_edge_sa_email
  frontend_sa_email      = module.iam.frontend_sa_email
  scheduler_sa_email     = module.iam.scheduler_sa_email
  snapshots_bucket_name  = module.storage.snapshots_bucket_name
  resumes_bucket_name    = module.storage.resumes_bucket_name
  secret_ids             = module.secrets.secret_ids
  vpc_network_id         = module.networking.vpc_network_id
  vpc_subnetwork_id      = module.networking.vpc_subnetwork_id
  domain_name            = var.domain_name
}