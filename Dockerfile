FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy dependency metadata first to keep dependency installation cacheable.
COPY pyproject.toml uv.lock README.md ./
COPY grafana_azure_sync ./grafana_azure_sync

RUN uv sync --locked --no-dev --no-editable

CMD ["grafana-azure-sync"]
