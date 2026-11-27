# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "poetry>=2.0,<3.0"

COPY packages/contracts/pyproject.toml /app/packages/contracts/
COPY packages/contracts/src /app/packages/contracts/src
COPY services/control-plane/pyproject.toml services/control-plane/poetry.lock /app/services/control-plane/

WORKDIR /app/services/control-plane
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main --no-interaction --no-ansi

COPY services/control-plane /app/services/control-plane
RUN SECRET_KEY=collectstatic-build-placeholder python manage.py collectstatic --noinput

EXPOSE 8000
ARG SENTRY_RELEASE=""
ENV SENTRY_RELEASE=${SENTRY_RELEASE}
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 60 --graceful-timeout 30"]
