FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"

COPY packages/contracts /app/packages/contracts
COPY services/stream-edge/pyproject.toml services/stream-edge/poetry.lock /app/services/stream-edge/

WORKDIR /app/services/stream-edge
RUN poetry install --only main --no-root --no-interaction --no-ansi

COPY services/stream-edge /app/services/stream-edge
RUN poetry install --only-root --no-interaction --no-ansi

EXPOSE 8001
CMD ["uvicorn", "stream_edge.main:app", "--host", "0.0.0.0", "--port", "8001"]