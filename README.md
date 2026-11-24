# Vektryn

AI-powered job discovery, semantic resume matching, application pipeline tracker, and tech-stack market intelligence platform.

## Architecture

Vektryn is a monorepo combining an event-driven ingestion/scoring pipeline with a REST control plane and React SPA:

| Component | Path | Stack |
| --- | --- | --- |
| **Shared Contracts** | `packages/contracts/` | Pydantic v2 Kafka event schemas, domain enums, HMAC stream token signing |
| **Control Plane** | `services/control-plane/` | Django 6 + DRF + `django-filter` + `pgvector` + `drf-spectacular` + OpenTelemetry |
| **Stream Edge & Workers** | `services/stream-edge/` | FastAPI (`/ingest/jobs`, `/stream/alerts` SSE), ATS/feed collectors, Kafka enrichment & pgvector matching workers, rollup/lifecycle/DLQ jobs |
| **Frontend** | `frontend/` | React 19 + TypeScript + Vite 8 + Tailwind CSS v4 + Nginx reverse proxy |
| **Infrastructure** | `infra/terraform/`, `infra/docker/` | GCP Cloud Run, Cloud Run Jobs + Cloud Scheduler, Cloud SQL (pgvector), Memorystore, GCS, Prometheus, Grafana, OpenTelemetry Collector |

### Data Flow

```text
ATS Collectors / Feeds ─► POST /ingest/jobs (API key + GCS/local HTML snapshot)
                       ─► Kafka [jobs.raw]
                       ─► Enrichment Worker (Redis SHA-256 dedup + Gemini extraction & 768-dim embedding)
                       ─► Kafka [jobs.enriched]
                       ─► Matcher Worker (pgvector HNSW cosine filter + Gemini fit/gap scoring)
                       ─► PostgreSQL + Kafka [jobs.alerts]
                       ─► GET /stream/alerts?token=<HMAC> (SSE) ─► React SPA
```

## Quickstart

### Prerequisites
- Docker & Docker Compose
- Python 3.13+ with Poetry (`>=2.0`)
- Node.js 22+ with npm

### 1. Environment Configuration
Copy `.env.example` to `.env` and set your `GEMINI_API_KEY` (and optional `INGEST_API_KEY` / `STREAM_AUTH_SECRET` for production-parity auth):

```fish
cp .env.example .env
```

### 2. Start the Full Local Stack

```fish
make up
```

Services exposed locally:
- **Frontend SPA**: `http://localhost:3000`
- **Control Plane API & Swagger**: `http://localhost:8000/api/docs/`
- **Stream Edge (Ingest & SSE)**: `http://localhost:8001/health`
- **Prometheus**: `http://localhost:9090`
- **Grafana (`Vektryn Pipeline Overview`)**: `http://localhost:3001` (`admin` / `vektryn_admin`)

### 3. Create an Account & Run Collectors

```fish
make migrate
make createsuperuser
make collect
```

Sign in at `http://localhost:3000`, upload or paste a resume profile in the **Resumes** tab, and run `make collect` to ingest, enrich, and score jobs against your active profiles.

## Common Makefile Commands

| Command | Description |
| --- | --- |
| `make up` / `make down` | Build and start / stop all Docker Compose services |
| `make test` | Run pytest across `contracts`, `control-plane`, `stream-edge`, plus frontend tests |
| `make lint` | Run Ruff + Black checks across Python packages and `oxlint --deny-warnings` + `tsc -b` on frontend |
| `make format` | Auto-fix Ruff issues and format Python packages with Black |
| `make check` | Run Django system checks |
| `make collect` | Run ATS & multi-company feed collectors and push to stream-edge |
| `make worker/rollup` | Compute daily `StackTrendDaily` demand & salary rollups |
| `make worker/lifecycle` | Check active job listings upstream and mark closed postings inactive |
| `make worker/dlq` | Inspect `jobs.dlq` (`make worker/dlq args="--execute"` to replay) |

## CI/CD

- **Pull Requests & `main`** ([.github/workflows/ci.yml](.github/workflows/ci.yml)): Runs 4 parallel jobs (`contracts`, `control-plane` with `pgvector/pgvector:pg17`, `stream-edge`, `frontend`) covering Ruff, Black, Oxlint, TypeScript (`tsc -b`), pytest, frontend tests, and production Vite build.
- **GCP Deployment** ([.github/workflows/deploy-gcp.yml](.github/workflows/deploy-gcp.yml)): Builds and pushes container images to Artifact Registry via Workload Identity Federation and applies Terraform in `infra/terraform/`.
