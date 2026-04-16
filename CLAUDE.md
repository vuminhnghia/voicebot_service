# Voicebot Service — Claude Context

## Project Overview
Production Vietnamese voicebot: Audio → ASR (Parakeet) → LLM (Qwen3.5) → TTS (MMS) via Triton Inference Server.
Async pipeline with FastAPI (API) + Worker (consumer) communicating via RabbitMQ.

## Monorepo Structure
```
voicebot_service/
├── docker-compose.yml          # All 11 services
├── justfile                    # Developer commands (just --list)
├── .dockerignore               # Excludes opt/ (model weights) from build context
├── pyrightconfig.json          # extraPaths: ["shared", "services/api", "services/worker"]
├── pyproject.toml              # uv workspace root + dev tools (pytest, ruff, pyright)
│
├── shared/                     # Shared Python package (merged into both api & worker via Docker COPY)
│   ├── pyproject.toml          # Runtime deps for api & worker (voicebot-shared, package=false)
│   ├── alembic.ini / alembic/  # DB migrations
│   └── app/                    # Namespace package (no __init__.py — see Import Resolution below)
│       ├── config.py           # Pydantic Settings (reads from .env)
│       ├── logging_config.py   # structlog JSON setup
│       ├── metrics.py          # Prometheus counters/histograms
│       ├── domain/ports/       # Abstract interfaces (ASR, LLM, TTS, storage, queue, repo)
│       ├── application/use_cases/  # voice_pipeline.py, text_pipeline.py
│       ├── infrastructure/adapters/ # Triton, SeaweedFS, Redis, RabbitMQ, Postgres
│       └── schemas/            # Pydantic models (task.py, voice.py)
│
├── services/
│   ├── api/                    # FastAPI service
│   │   ├── Dockerfile          # Build context = repo root (needs shared/ + services/api/)
│   │   ├── pyproject.toml      # uv workspace member (virtual, no deps)
│   │   ├── entrypoint.sh       # Runs alembic upgrade before uvicorn
│   │   ├── .env                # Docker credentials (not committed)
│   │   ├── .env.example        # Template for local dev (localhost URLs)
│   │   └── app/                # Namespace package (no __init__.py)
│   │       ├── main.py         # FastAPI lifespan, Prometheus instrumentation
│   │       └── api/routers/voice.py
│   │
│   ├── worker/                 # RabbitMQ consumer
│   │   ├── Dockerfile          # Same pattern as api Dockerfile
│   │   ├── pyproject.toml      # uv workspace member (virtual, no deps)
│   │   ├── entrypoint.sh
│   │   ├── .env.example        # Template for local dev
│   │   └── app/worker/main.py  # aio-pika consumer, DLQ after 2 retries
│   │
│   └── triton/                 # Triton Inference Server model configs
│       ├── parakeet_asr/       # ASR model (NVIDIA Parakeet)
│       ├── mms_tts/            # TTS model (Meta MMS Vietnamese)
│       └── qwen35_llm/         # LLM (Qwen 3.5)
│
└── infra/                      # Config files for infrastructure services
    ├── postgres/init.sql
    ├── rabbitmq/rabbitmq.conf + enabled_plugins
    ├── seaweedfs/s3.json        # IAM credentials config
    ├── prometheus/prometheus.yml
    ├── loki/loki.yml
    ├── promtail/promtail.yml
    └── grafana/                # Auto-provisioned datasources + dashboards
```

## uv Workspace
Three virtual workspace members share a single venv at repo root:
- `shared/` — all runtime deps (`voicebot-shared`, `package=false`)
- `services/api/` — no extra deps (`voicebot-api`, `package=false`)
- `services/worker/` — no extra deps (`voicebot-worker`, `package=false`)

Root `pyproject.toml` holds dev tools only (pytest, ruff, pyright). `uv sync --all-packages` installs everything into `.venv/`.

## Import Resolution & Namespace Packages
Both `shared/app/` and `services/api/app/` (and `services/worker/app/`) contribute to the same `app` namespace. There is **no `__init__.py`** at the `app/` level in any of them — Python 3.3+ namespace packages merge them transparently.

- **Docker**: `COPY shared/app ./app/` then `COPY services/api/app ./app/` — physical merge into one dir. `app/` has no `__init__.py`, so namespace package. Works as before.
- **Local**: `PYTHONPATH=shared:services/api` — Python merges `shared/app/` + `services/api/app/` at runtime. `from app.config import Settings` resolves to `shared/app/config.py`; `from app.main import app` resolves to `services/api/app/main.py`.
- **IDE (pyright)**: `pyrightconfig.json extraPaths: ["shared", "services/api", "services/worker"]` — same merge.

## Docker Build Pattern
Both `api` and `worker` use **layer-merge**: build context is repo root, shared code is copied first then service-specific code overlays it:
```dockerfile
COPY shared/app ./app/          # base shared code
COPY services/api/app ./app/    # overlays service-specific files (main.py, routers/)
```

## Services & Ports
| Service    | Port(s)            | Notes |
|------------|--------------------|-|
| triton     | 8000/8001/8002     | HTTP/gRPC/Metrics — requires NVIDIA GPU |
| postgres   | 5432               | DB: voicebot / user: voicebot |
| rabbitmq   | 5672, 15672, 15692 | AMQP, Management UI, Prometheus metrics |
| redis      | 6379               | Task status cache only |
| seaweedfs  | 9333, 8333         | Master admin, S3 API |
| api        | 8080               | FastAPI, /health, /metrics |
| worker     | —                  | No port, consumes from RabbitMQ |
| prometheus | 9090               | Scrapes api:8080 + rabbitmq:15692 |
| loki       | 3100               | Log aggregation |
| promtail   | —                  | Tails Docker logs → Loki |
| grafana    | 3000               | Dashboards (admin/admin) |

## Key Design Decisions
- **SeaweedFS** (not MinIO) for object storage — S3-compatible, self-hosted
- **RabbitMQ** queue: DLQ after 2 retries, `prefetch_count=1`
- **PostgreSQL** for task metadata (persistent), **Redis** for status cache only
- **structlog** JSON logging → stdout → Promtail → Loki
- **Prometheus** metrics: `voicebot_task_total` (counter) + `voicebot_task_duration_seconds` (histogram)

## SeaweedFS Auth Notes
- Image: `chrislusf/seaweedfs` (official Docker Hub image)
- Auth config: `infra/seaweedfs/s3.json` mounted to `/etc/seaweedfs/s3.json`
- Flag: `-s3.config=/etc/seaweedfs/s3.json` (simple static credentials, no STS)
- The warning `Failed to load IAM configuration: no signing key found for STS service` is **non-blocking** — only affects STS/AssumeRole which we don't use
- Credentials: `voicebot-access-key` / `voicebot-secret-key-change-in-prod`
- If auth breaks: check if `seaweedfs_data` volume has stale IAM → `docker volume rm voicebot_service_seaweedfs_data`

## How to Start

### Local development (debug individual services)
```bash
just install                                          # setup venv
cp services/api/.env.example services/api/.env.local
cp services/worker/.env.example services/worker/.env.local
just infra-up                                         # postgres, rabbitmq, redis, seaweedfs
just migrate                                          # run DB migrations
just run-api                                          # terminal 1
just run-worker                                       # terminal 2
```

### Infrastructure only (no GPU needed)
```bash
just infra-up
# or: docker compose up -d postgres rabbitmq redis seaweedfs
```

### Full stack (requires GPU for Triton)
```bash
just up
# or: docker compose up -d
```

### Rebuild after code changes
```bash
just deploy
# or: docker compose build api worker && docker compose up -d api worker
```

## Env Files

### Docker (services/api/.env — used by both api and worker containers)
```
TRITON_URL=triton:8000
REDIS_URL=redis://redis:6379
POSTGRES_URL=postgresql+asyncpg://voicebot:voicebot@postgres:5432/voicebot
RABBITMQ_URL=amqp://voicebot:voicebot@rabbitmq:5672/
SEAWEEDFS_ENDPOINT=http://seaweedfs:8333
SEAWEEDFS_BUCKET=voicebot
SEAWEEDFS_ACCESS_KEY=voicebot-access-key
SEAWEEDFS_SECRET_KEY=voicebot-secret-key-change-in-prod
API_KEYS=nghia-dev
SYSTEM_PROMPT=Bạn là trợ lý AI giọng nói hữu ích. Trả lời ngắn gọn, tự nhiên bằng tiếng Việt.
MAX_TOKENS=500
```

### Local dev (.env.local — same vars, localhost URLs)
Copy from `.env.example` in each service dir. These are gitignored (`*.env.local`).

## Common Debug Commands
```bash
# All just commands
just --list

# Check service status
just status

# Follow logs
just logs-api
just logs-worker

# Test API health
curl http://localhost:8080/health

# Test SeaweedFS S3 auth
aws --endpoint-url http://localhost:8333 s3 ls \
    --aws-access-key-id voicebot-access-key \
    --aws-secret-access-key voicebot-secret-key-change-in-prod

# RabbitMQ Management UI
open http://localhost:15672  # user: voicebot / pass: voicebot

# Grafana dashboards
open http://localhost:3000   # user: admin / pass: admin
```

## Known Issues / Gotchas
- RabbitMQ config uses `log.console.level` (not `log.level`) — RabbitMQ 3.x syntax
- SeaweedFS `seaweedfs_data` volume can persist stale IAM config — delete volume to reset
- `.dockerignore` at repo root excludes `opt/` (model weights ~GB) from build context
- Triton requires NVIDIA GPU + CUDA drivers — skip if not available
- `app/` is a **namespace package** (no `__init__.py` at top level) — required for local dev PYTHONPATH merge to work
- `pyrightconfig.json extraPaths` must include all three service dirs for IDE to resolve imports correctly
