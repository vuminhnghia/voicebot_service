# Voicebot Service — Claude Context

## Project Overview
Production Vietnamese voicebot: Audio → ASR (Parakeet) → LLM (Qwen3.5) → TTS (MMS) via Triton Inference Server.
Async pipeline with FastAPI (API) + Worker (consumer) communicating via RabbitMQ.

## Monorepo Structure
```
voicebot_service/
├── docker-compose.yml          # All 11 services
├── .dockerignore               # Excludes opt/ (model weights) from build context
├── pyrightconfig.json          # extraPaths: ["shared"] for IDE import resolution
│
├── shared/                     # Shared Python package (merged into both api & worker via Docker COPY)
│   ├── pyproject.toml          # Single source of dependencies for api & worker
│   ├── alembic.ini / alembic/  # DB migrations
│   └── app/
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
│   │   ├── entrypoint.sh       # Runs alembic upgrade before uvicorn
│   │   ├── .env                # Credentials (not committed to prod)
│   │   └── app/
│   │       ├── main.py         # FastAPI lifespan, Prometheus instrumentation
│   │       └── api/routers/voice.py
│   │
│   ├── worker/                 # RabbitMQ consumer
│   │   ├── Dockerfile          # Same pattern as api Dockerfile
│   │   ├── entrypoint.sh
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

## Docker Build Pattern
Both `api` and `worker` use **layer-merge**: build context is repo root, shared code is copied first then service-specific code overlays it:
```dockerfile
COPY shared/app ./app/          # base shared code
COPY services/api/app ./app/    # overlays service-specific files (main.py, routers/)
```
Imports use `from app.xxx` — works in Docker. IDE resolves via `pyrightconfig.json extraPaths: ["shared"]`.

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

### Infrastructure only (no GPU needed)
```bash
docker compose up -d postgres rabbitmq redis seaweedfs
```

### Full stack (requires GPU for Triton)
```bash
docker compose up -d
```

### Rebuild after code changes
```bash
docker compose build api worker
docker compose up -d api worker
```

### Start single service
```bash
docker compose up -d --force-recreate seaweedfs
```

## Env File: services/api/.env
```
TRITON_URL=triton:8000
REDIS_URL=redis://redis:6379
POSTGRES_URL=postgresql+asyncpg://voicebot:voicebot@postgres:5432/voicebot
RABBITMQ_URL=amqp://voicebot:voicebot@rabbitmq:5672/
SEAWEEDFS_ENDPOINT=http://seaweedfs:8333
SEAWEEDFS_BUCKET=voicebot
SEAWEEDFS_ACCESS_KEY=voicebot-access-key
SEAWEEDFS_SECRET_KEY=voicebot-secret-key-change-in-prod
API_KEYS=["nghia-dev"]
SYSTEM_PROMPT=Bạn là trợ lý AI giọng nói hữu ích. Trả lời ngắn gọn, tự nhiên bằng tiếng Việt.
MAX_TOKENS=500
```

## Common Debug Commands
```bash
# Check all service status
docker compose ps

# Follow logs for a service
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f seaweedfs

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
- `pyrightconfig.json extraPaths: ["shared"]` is required for IDE to resolve `from app.xxx` imports
