FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"

COPY packages/contracts /app/packages/contracts
COPY services/control-plane/pyproject.toml services/control-plane/poetry.lock /app/services/control-plane/

WORKDIR /app/services/control-plane
RUN poetry install --only main --no-interaction --no-ansi

COPY services/control-plane /app/services/control-plane

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"]