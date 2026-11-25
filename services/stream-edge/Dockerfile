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
COPY services/stream-edge/pyproject.toml services/stream-edge/poetry.lock /app/services/stream-edge/

WORKDIR /app/services/stream-edge
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main --no-root --no-interaction --no-ansi

COPY services/stream-edge /app/services/stream-edge
RUN poetry install --only-root --no-interaction --no-ansi

EXPOSE 8001
ARG SENTRY_RELEASE=""
ENV SENTRY_RELEASE=${SENTRY_RELEASE}
CMD ["uvicorn", "stream_edge.main:app", "--host", "0.0.0.0", "--port", "8001"]
