.PHONY: up down logs migrate makemigrations test lint collect

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

makemigrations:
	docker compose exec control-plane poetry run python manage.py makemigrations

migrate:
	docker compose exec control-plane poetry run python manage.py migrate

test:
	poetry run pytest

lint:
	poetry run ruff check .
	poetry run black --check .

collect:
	docker compose exec stream-edge poetry run python -m stream_edge.collectors.run