SHELL := /bin/bash -o pipefail

ifndef NOCOLOR
	RED    := $(shell tput -Txterm setaf 1)
	GREEN  := $(shell tput -Txterm setaf 2)
	YELLOW := $(shell tput -Txterm setaf 3)
	RESET  := $(shell tput -Txterm sgr0)
endif

CONTRACTS_DIR     := packages/contracts
CONTROL_PLANE_DIR := services/control-plane
STREAM_EDGE_DIR   := services/stream-edge
FRONTEND_DIR      := frontend
BACKEND_SERVICES  := control-plane stream-edge enrichment-worker matcher-worker
PORT              ?= 8000
EDGE_PORT         ?= 8001

MANAGE := cd $(CONTROL_PLANE_DIR) && POSTGRES_HOST=localhost poetry run python manage.py
EDGE_ENV := POSTGRES_HOST=localhost KAFKA_BOOTSTRAP_SERVERS=localhost:29092 REDIS_URL=redis://localhost:6379/0

.DEFAULT_GOAL := help

## Show available Makefile targets
.PHONY: help
help:
	@awk '/^.PHONY: / { \
		msg = match(lastLine, /^## /); \
		if (msg) { \
			cmd = substr($$0, 9, 100); \
			msg = substr(lastLine, 4, 1000); \
			printf "  ${GREEN}%-30s${RESET} %s\n", cmd, msg; \
		} \
	} \
	{ lastLine = $$0 }' $(MAKEFILE_LIST)

## Start Docker Compose stack (infrastructure, backend, frontend)
.PHONY: up
up:
	@echo "${GREEN}Starting Docker Compose stack${RESET}"
	docker compose up -d --build

## Build and start/reload backend services (and required infra dependencies)
.PHONY: up/backend
up/backend:
	@echo "${GREEN}Starting backend services ($(BACKEND_SERVICES))${RESET}"
	docker compose up -d --build $(BACKEND_SERVICES)

## Build and start/reload only the frontend container
.PHONY: up/frontend
up/frontend:
	@echo "${GREEN}Starting frontend service${RESET}"
	docker compose up -d --build --no-deps frontend

## Stop and remove Docker Compose containers
.PHONY: down
down:
	@echo "${GREEN}Stopping Docker Compose infrastructure${RESET}"
	docker compose down

## Stream Docker Compose container logs
.PHONY: logs
logs:
	@echo "${GREEN}Streaming container logs${RESET}"
	docker compose logs -f

## Run Django system checks
.PHONY: check
check:
	@echo "${GREEN}Running Django checks${RESET}"
	$(MANAGE) check

## Create Django migrations (optional: make makemigrations app=jobs)
.PHONY: makemigrations
makemigrations:
	@echo "${GREEN}Creating migrations${RESET}"
	$(MANAGE) makemigrations $(app)

## Apply Django migrations (optional: make migrate app=jobs)
.PHONY: migrate
migrate:
	@echo "${GREEN}Applying migrations${RESET}"
	$(MANAGE) migrate $(app)

## Show Django migration status (optional: make showmigrations app=jobs)
.PHONY: showmigrations
showmigrations:
	@echo "${GREEN}Showing migrations${RESET}"
	$(MANAGE) showmigrations $(app)

## Create a Django superuser interactively
.PHONY: createsuperuser
createsuperuser:
	@echo "${GREEN}Creating superuser${RESET}"
	$(MANAGE) createsuperuser

## Open Django management shell
.PHONY: shell
shell:
	@echo "${GREEN}Opening Django shell${RESET}"
	$(MANAGE) shell

## Run Django development server (override port with PORT=8080)
.PHONY: runserver
runserver:
	@echo "${GREEN}Starting Django control plane on port $(PORT)${RESET}"
	$(MANAGE) runserver $(PORT)

## Run FastAPI stream-edge server (override port with EDGE_PORT=8081)
.PHONY: edge
edge:
	@echo "${GREEN}Starting FastAPI stream-edge on port $(EDGE_PORT)${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run uvicorn stream_edge.main:app --host 0.0.0.0 --port $(EDGE_PORT) --reload

## Run ATS collectors and push jobs to stream-edge
.PHONY: collect
collect:
	@echo "${GREEN}Running ATS collectors${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.collectors.run

## Run Kafka enrichment worker
.PHONY: worker/enrichment
worker/enrichment:
	@echo "${GREEN}Starting Kafka enrichment worker${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.workers.enrichment

## Run Kafka pgvector matching worker
.PHONY: worker/matcher
worker/matcher:
	@echo "${GREEN}Starting Kafka matching worker${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.workers.matcher

## Run daily StackTrendDaily analytics rollup
.PHONY: worker/rollup
worker/rollup:
	@echo "${GREEN}Running daily StackTrendDaily rollup${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.workers.rollup

## Check active JobPostings upstream and mark closed listings inactive
.PHONY: worker/lifecycle
worker/lifecycle:
	@echo "${GREEN}Running upstream closed-job lifecycle check${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.workers.lifecycle

## Inspect or replay failed events from jobs.dlq (pass args="--execute" to replay)
.PHONY: worker/dlq
worker/dlq:
	@echo "${GREEN}Running DLQ inspection/replay${RESET}"
	cd $(STREAM_EDGE_DIR) && $(EDGE_ENV) poetry run python -m stream_edge.workers.dlq_replay $(args)
	
## Run pytest test suite across all Python packages and Vitest on frontend
.PHONY: test
test:
	@echo "${GREEN}Running pytest (contracts)${RESET}"
	cd $(CONTRACTS_DIR) && poetry run pytest $(opts)
	@echo "${GREEN}Running pytest (control-plane)${RESET}"
	cd $(CONTROL_PLANE_DIR) && POSTGRES_HOST=localhost poetry run pytest $(opts)
	@echo "${GREEN}Running pytest (stream-edge)${RESET}"
	cd $(STREAM_EDGE_DIR) && poetry run pytest $(opts)
	@echo "${GREEN}Running Vitest (frontend)${RESET}"
	cd $(FRONTEND_DIR) && npm test

## Run Ruff and Black checks across all Python packages
.PHONY: lint/python
lint/python:
	@echo "${GREEN}Running Ruff and Black checks${RESET}"
	cd $(CONTRACTS_DIR) && poetry run ruff check . && poetry run black --check .
	cd $(CONTROL_PLANE_DIR) && poetry run ruff check . && poetry run black --check .
	cd $(STREAM_EDGE_DIR) && poetry run ruff check . && poetry run black --check .

## Run frontend oxlint and TypeScript typecheck
.PHONY: lint/frontend
lint/frontend:
	@echo "${GREEN}Running frontend oxlint and TypeScript checks${RESET}"
	cd $(FRONTEND_DIR) && npm run lint && npx tsc -b

## Run all linters across Python and frontend
.PHONY: lint
lint: lint/python lint/frontend

## Auto-format Python packages with Ruff and Black
.PHONY: format
format:
	@echo "${GREEN}Formatting Python packages with Ruff and Black${RESET}"
	cd $(CONTRACTS_DIR) && poetry run ruff check --fix . && poetry run black .
	cd $(CONTROL_PLANE_DIR) && poetry run ruff check --fix . && poetry run black .
	cd $(STREAM_EDGE_DIR) && poetry run ruff check --fix . && poetry run black .
