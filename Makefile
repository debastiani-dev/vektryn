CONTROL_PLANE_DIR := services/control-plane
MANAGE := cd $(CONTROL_PLANE_DIR) && POSTGRES_HOST=localhost poetry run python manage.py

.PHONY: up down logs check makemigrations migrate showmigrations createsuperuser shell test lint collect

# Docker Compose infrastructure
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Django Control Plane
check:
	$(MANAGE) check

makemigrations:
	$(MANAGE) makemigrations $(app)

migrate:
	$(MANAGE) migrate $(app)

showmigrations:
	$(MANAGE) showmigrations $(app)

createsuperuser:
	$(MANAGE) createsuperuser

shell:
	$(MANAGE) shell

# Quality & Collectors
test:
	poetry run pytest

lint:
	poetry run ruff check .
	poetry run black --check .

collect:
	cd services/stream-edge && POSTGRES_HOST=localhost KAFKA_BOOTSTRAP_SERVERS=localhost:29092 REDIS_URL=redis://localhost:6379/0 poetry run python -m stream_edge.collectors.run