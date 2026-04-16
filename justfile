# List all available commands
default:
    @just --list

# ── Setup ──────────────────────────────────────────────────────────────────

# Install all workspace dependencies into a single venv
install:
    uv sync --all-packages

# ── Infrastructure (Docker) ────────────────────────────────────────────────

# Start infra only — postgres, rabbitmq, redis, seaweedfs (no GPU needed)
infra-up:
    docker compose up -d postgres rabbitmq redis seaweedfs

# Start full stack (requires NVIDIA GPU for Triton)
up:
    docker compose up -d

# Stop all services
down:
    docker compose down

# Show status of all services
status:
    docker compose ps

# ── Local development ──────────────────────────────────────────────────────
# Prerequisites: `just install`, `just infra-up`, copy .env.example → .env.local

# Run API locally with hot-reload
run-api:
    PYTHONPATH=shared:services/api uv run \
        --env-file services/api/.env.local \
        uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# Run Worker locally
run-worker:
    PYTHONPATH=shared:services/worker uv run \
        --env-file services/worker/.env.local \
        python -m app.worker.main

# ── Database ───────────────────────────────────────────────────────────────

# Run Alembic migrations (requires infra-up)
migrate:
    cd shared && PYTHONPATH=.. uv run \
        --env-file ../services/api/.env.local \
        alembic upgrade head

# Generate a new migration (usage: just migration "add users table")
migration name:
    cd shared && PYTHONPATH=.. uv run \
        --env-file ../services/api/.env.local \
        alembic revision --autogenerate -m "{{name}}"

# ── Build & Deploy (Docker) ────────────────────────────────────────────────

# Build api and worker Docker images
build:
    docker compose build api worker

# Rebuild images and restart api + worker
deploy: build
    docker compose up -d api worker

# ── Code quality ───────────────────────────────────────────────────────────

# Run linter
lint:
    uv run ruff check .

# Auto-fix linting issues
lint-fix:
    uv run ruff check --fix .

# Type check
typecheck:
    uv run pyright

# Run tests
test:
    uv run pytest

# Run all checks (lint + typecheck + test)
check: lint typecheck test

# ── Logs ───────────────────────────────────────────────────────────────────

# Follow API logs
logs-api:
    docker compose logs -f api

# Follow Worker logs
logs-worker:
    docker compose logs -f worker
