# ==============================================================================
# Multi-Stage Dockerfile for Shift Handover Copilot
# Stage 1: Build Frontend with Node.js
# Stage 2: Run FastAPI Backend with Python and static assets
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Frontend
# ------------------------------------------------------------------------------
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend

# Copy package manifests and install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy openapi spec (referenced by codegen checks) and frontend source
COPY openapi.yaml /build/openapi.yaml
COPY frontend/ ./

# Build static production bundle into dist/
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Build Python Backend Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim

# Install uv from the official Astral image for fast, deterministic dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment settings
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8000 \
    HOST=0.0.0.0 \
    FRONTEND_DIR=/app/static

WORKDIR /app

# Copy dependency definition files first for efficient Docker layer caching
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy backend source code, migrations, and configuration
COPY backend/ ./

# Install project into virtualenv
RUN uv sync --frozen --no-dev

# Copy static frontend files built in Stage 1
COPY --from=frontend-builder /build/frontend/dist /app/static

# Expose HTTP port (defaults to 8000, compatible with Cloud Run $PORT)
EXPOSE 8000

# Create an entrypoint script that applies database migrations and launches Uvicorn
RUN printf '#!/bin/sh\nset -e\necho "Applying database migrations..."\nuv run alembic upgrade head || true\necho "Starting Shift Handover Copilot on ${HOST:-0.0.0.0}:${PORT:-8000}..."\nexec uv run uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"\n' > /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
