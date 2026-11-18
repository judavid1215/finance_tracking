# syntax=docker/dockerfile:1.7
# Multi-arch (linux/amd64 y linux/arm64): imagen base y uv publican ambas arquitecturas.

# ---------- base: Python + uv + usuario no root ----------
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Madrid \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# tzdata: garantiza que TZ=Europe/Madrid funcione. uid/gid 1000 = usuario habitual en WSL2.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app \
    && mkdir -p /app /data/db /data/backups \
    && chown -R app:app /app /data

COPY --from=ghcr.io/astral-sh/uv:0.5.9 /uv /usr/local/bin/uv
WORKDIR /app

# ---------- deps-prod: venv solo con dependencias de producción ----------
FROM base AS deps-prod
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# ---------- dev: dependencias + herramientas de desarrollo; el código se monta ----------
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project
COPY --chown=app:app pyproject.toml alembic.ini ./
COPY --chown=app:app src ./src
COPY --chown=app:app tests ./tests
USER app
EXPOSE 8000 5678
CMD ["uvicorn", "finanzas.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- prod: mínima, sin herramientas de desarrollo ----------
FROM base AS prod
COPY --from=deps-prod --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app src ./src
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
# Un solo proceso (sin --workers): el planificador vive en este proceso.
CMD ["uvicorn", "finanzas.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
