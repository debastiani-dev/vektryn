# Vektryn — Production Operations & Runbooks

Operational reference for the Google Cloud Platform deployment of Vektryn ([vektryn.debastiani.dev](https://vektryn.debastiani.dev)). For product overview, architecture, APIs, and local development, see [README.md](../README.md).

## Contents

- [GCP Topology](#gcp-topology)
- [CI/CD Pipelines](#cicd-pipelines)
- [Consolidated Observability](#consolidated-observability)
- [One-Off Backfill & Maintenance Commands](#one-off-backfill--maintenance-commands)
- [PostgreSQL Backup & Disaster-Recovery Restore Runbook](#postgresql-backup--disaster-recovery-restore-runbook)

---

## GCP Topology

Provisioned declaratively with Terraform ([`infra/terraform/`](../infra/terraform/)) backed by GCS remote state in `us-central1`:

- **Cloud Run Services:**
  - `vektryn-frontend`: Nginx 1.27 reverse proxy serving the static Vite SPA on custom domain `vektryn.debastiani.dev` with Google-managed TLS.
  - `vektryn-control-plane`: Django 6 + DRF APIs, session auth, AI Copilot, and signed SSE token minting over Direct VPC Egress.
  - `vektryn-stream-edge`: FastAPI ingestion (`POST /ingest/jobs`) and unbuffered SSE alert stream (`GET /stream/alerts`) with a `3600s` request timeout.
- **Cloud Run Jobs & Cloud Scheduler:**
  - `vektryn-migrate`: splits `command = ["python", "manage.py"]` and `args = ["migrate", "--noinput"]`; executed conditionally during CD when Django migrations change and reusable for one-off management commands via per-execution `--args` overrides.
  - `vektryn-collect`: scheduled every 4 hours (`0 */4 * * *` UTC) to run all 14 ATS/feed collectors.
  - `vektryn-rollup`: scheduled daily (`0 1 * * *` UTC) for `StackTrendDaily` market analytics rollups.
  - `vektryn-lifecycle`: scheduled daily (`0 3 * * *` UTC) for source-aware closed-job probing/failover and lead follow-up reminders.
- **Private VPC Data & Worker Node (`vektryn-data-node`):** Compute Engine `e2-micro` VM (`us-central1-a`, static internal VPC IP, 30 GB `pd-standard`, 2 GB swap) running `pgvector/pgvector:pg17`, `redis:7-alpine`, `apache/kafka:3.9.0` (KRaft), `enrichment-worker`, and `matcher-worker`, with OS Login enabled and IAP-only SSH (zero public DB, broker, or SSH ports).
- **Storage, Registry & Secrets:** GCS buckets (`raw-snapshots`, `resumes`, `db-backups` with 14-day lifecycle for daily `pg_dump` archives, `tfstate`), Artifact Registry (`vektryn`), 9 GCP Secret Manager secrets with least-privilege `secretAccessor` bindings, and keyless GitHub Actions OIDC Workload Identity Federation (`vektryn-deployer`).

---

## CI/CD Pipelines

- **PR & Main CI** ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)): 4 required parallel jobs (`Contracts`, `Control Plane`, `Stream Edge`, `Frontend`) enforced via `main` branch protection, with path-filtered PR execution ([`detect_ci_changes.py`](../.github/scripts/detect_ci_changes.py)) and cached Poetry virtualenvs.
- **Fast Incremental CD** ([`.github/workflows/deploy-gcp.yml`](../.github/workflows/deploy-gcp.yml)): Uses [`detect_deploy_changes.py`](../.github/scripts/detect_deploy_changes.py) on push to `main` (plus `workflow_dispatch` force overrides):
  - Builds only affected Docker images in parallel with BuildKit GHA layer caching, baking immutable `SENTRY_RELEASE=<git_sha>` and `VITE_SENTRY_*` metadata into each image.
  - Runs `terraform apply` only when `infra/terraform/**` changes and executes `vektryn-migrate` only when Django migrations change.
  - Updates affected Cloud Run services and jobs in parallel.
  - Refreshes `matcher-worker` **before** `enrichment-worker` on `vektryn-data-node` via IAP OS Login SSH (maintaining `EventEnvelope(extra="forbid")` schema rollout safety, updating `/opt/vektryn/.env` atomically with `chmod 600`, and verifying container health).
  - Finishes with a live production `/api/v1/health/` smoke check.

---

## Consolidated Observability

- **In-App Pipeline Telemetry:** `PipelineStatusPopover` and `DlqInspectorModal` expose operational health with explicit `status_reasons`, per-source `CollectorRunLog` metrics, active/AI-scored/filtered job counts, Redis-backed worker liveness heartbeats (`enrichment-worker`, `matcher-worker`), a staff manual collector trigger, and staff `jobs.dlq` inspection, dry-run preview, topic-allowlisted replay, and dismissal.
- **GCP Cloud Run Logs & Metrics:** Built-in structured container logs, request latency, instance scaling, and Cloud Run Job execution history.
- **Production Sentry Monitoring (Free Plan):** Covers all 9 runtimes (`control-plane`, `vektryn-migrate`, `stream-edge`, `enrichment-worker`, `matcher-worker`, `vektryn-collect`, `vektryn-rollup`, `vektryn-lifecycle`, and React SPA) plus daily `pg-backup` failure alerting:
  - `traces_sample_rate=0.0`; profiling and session replays disabled.
  - Strict PII, cookie, header, HMAC-token, password, and resume scrubbing.
  - Health-check and expected `4xx`/noise filtering, root `<Sentry.ErrorBoundary>` dark-mode recovery UI, and immutable git-SHA release tracking.
  - Controlled CLI verification:

```bash
# Control plane
python manage.py verify_sentry

# Stream edge / workers
python -m stream_edge.telemetry --verify
```

---

## One-Off Backfill & Maintenance Commands

Because `vektryn-migrate` splits `command = ["python", "manage.py"]` from `args`, one-off Django management commands run safely in production via per-execution `--args` overrides without mutating the job definition.

### Language Backfill (`backfill_languages`)

Idempotently detects ISO 639-1 language codes for `JobPosting` and `ResumeProfile` rows currently set to `unknown` at `$0` LLM cost (`--batch-size=500`, `--dry-run`, `--only=all|jobs|resumes`):

```bash
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_languages,--batch-size=500,--dry-run" --wait
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_languages,--batch-size=500" --wait
```

### Cross-Source Dedup & Provenance Backfill (`backfill_job_sources`)

Idempotently populates normalized dedup keys and initial `JobPostingSource` rows, with optional `--merge-duplicates` historical near-duplicate cleanup (`--batch-size=500`, `--dry-run`, `--merge-duplicates`, `--cosine-threshold=0.94`):

```bash
# 1. Preview key & source backfill
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_job_sources,--batch-size=500,--dry-run" --wait

# 2. Apply key & source backfill
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_job_sources,--batch-size=500" --wait

# 3. Preview historical near-duplicate merges
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_job_sources,--batch-size=500,--dry-run,--merge-duplicates" --wait

# 4. Apply historical near-duplicate merges after verifying preview counts
gcloud run jobs execute vektryn-migrate --region us-central1 --args="backfill_job_sources,--batch-size=500,--merge-duplicates" --wait
```

---

## PostgreSQL Backup & Disaster-Recovery Restore Runbook

- **Automated Daily Backups:** `vektryn-pg-backup.timer` runs `/opt/vektryn/backup-postgres.sh` daily at `05:00 UTC` (offset after `vektryn-rollup` `01:00`, `vektryn-lifecycle` `03:00`, and the `04:00` `vektryn-collect` wave) under `flock` + `nice -n 19` + `ionice -c 3`. It runs `pg_dump -Fc --compress=6 --no-owner --no-privileges`, validates the archive with `pg_restore --list`, uploads to `gs://<project_id>-db-backups/daily/vektryn-pg-YYYYMMDD-HHMMSSZ.dump` using `ifGenerationMatch=0` and append-only `roles/storage.objectCreator` IAM (14-day GCS lifecycle delete, `soft_delete_policy = 0s`, `public_access_prevention = "enforced"`), and reports any failure to Sentry (`service=pg-backup`).
- **Offline Key Hygiene:** Keep a secure offline copy of `BYOK_ENCRYPTION_KEY` in a password manager alongside the GCS dumps; restoring encrypted user Gemini API keys (`base_userprofile.gemini_api_key_encrypted`) requires the matching Fernet key.

### Disaster-Recovery Restore Procedure

1. Download the desired archive using an operator account with bucket read access:

```bash
gcloud storage ls gs://<project_id>-db-backups/daily/
gcloud storage cp gs://<project_id>-db-backups/daily/<archive>.dump /tmp/restore.dump
```

2. Pause write workers on `vektryn-data-node`:

```bash
sudo docker compose -f /opt/vektryn/docker-compose.yml stop enrichment-worker matcher-worker
```

3. Ensure `vector` and `pgcrypto` extensions exist on the target PostgreSQL 17 database and restore cleanly:

```bash
cat /tmp/restore.dump | sudo docker exec -i vektryn-postgres sh -c 'pg_restore --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

4. Restart workers and verify row counts, `https://vektryn.debastiani.dev/api/v1/health/`, and `GET /api/v1/system/status/`:

```bash
sudo docker compose -f /opt/vektryn/docker-compose.yml start enrichment-worker matcher-worker
```
