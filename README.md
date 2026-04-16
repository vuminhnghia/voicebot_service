# Voicebot Service

Vietnamese voice assistant: **Audio → ASR → LLM → TTS** — fully async, production-ready.

## Architecture

```
Client
  │
  ▼
FastAPI (api:8080)
  │  POST /voice/submit → upload audio → SeaweedFS
  │                     → create task → PostgreSQL
  │                     → cache status → Redis
  │                     → publish → RabbitMQ
  │
  ▼
Worker (consumer)
  │  consume from RabbitMQ
  │  → fetch audio ← SeaweedFS
  │  → ASR (Parakeet)  ┐
  │  → LLM (Qwen 3.5)  ├── Triton Inference Server
  │  → TTS (MMS-TTS)   ┘
  │  → store output → SeaweedFS
  │  → update task → PostgreSQL + Redis
  │
  ▼
Client polls GET /voice/tasks/{task_id}
```

## Stack

| Component | Technology |
|-----------|-----------|
| API       | FastAPI + uvicorn |
| Queue     | RabbitMQ (aio-pika) |
| Database  | PostgreSQL 16 + SQLAlchemy async |
| Cache     | Redis 7 |
| Storage   | SeaweedFS (S3-compatible) |
| Inference | Triton Inference Server (NVIDIA) |
| ASR       | NVIDIA Parakeet (Vietnamese) |
| LLM       | Qwen 3.5 |
| TTS       | Meta MMS-TTS (Vietnamese) |
| Logging   | structlog → Loki |
| Metrics   | Prometheus + Grafana |

## Requirements

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/) — Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [just](https://just.systems/) — command runner (`cargo install just` or `brew install just`)
- NVIDIA GPU + CUDA drivers (for Triton only)
- Model weights in `opt/models/` (see below)

## Quick Start

### 1. Install dependencies
```bash
just install
```

### 2. Prepare env files
```bash
cp services/api/.env.example services/api/.env.local
cp services/worker/.env.example services/worker/.env.local
# Edit .env.local files if needed (defaults work out of the box)
```

### 3. Prepare model weights (requires GPU)
```bash
mkdir -p opt/models/parakeet_asr opt/models/mms_tts_vie
# python services/triton/scripts/export_parakeet.py
# python services/triton/scripts/export_mms_tts.py
```

### 4. Start infrastructure (no GPU needed)
```bash
just infra-up
just migrate
```

### 5. Start full stack (Docker)
```bash
just up
```

### 6. Verify
```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

## API Usage

### Submit voice task
```bash
curl -X POST http://localhost:8080/voice/submit \
  -H "X-API-Key: nghia-dev" \
  -F "audio=@input.wav"
# {"task_id": "..."}
```

### Poll for result
```bash
curl http://localhost:8080/voice/tasks/{task_id} \
  -H "X-API-Key: nghia-dev"
# {"status": "completed", "output_url": "..."}
```

## Ports

| Service    | Port  | Purpose |
|------------|-------|---------|
| API        | 8080  | REST API |
| RabbitMQ   | 15672 | Management UI (voicebot/voicebot) |
| Grafana    | 3000  | Dashboards (admin/admin) |
| Prometheus | 9090  | Metrics |
| SeaweedFS  | 8333  | S3 API |
| SeaweedFS  | 9333  | Admin |

## Development

Run `just` to see all available commands.

### Local development (hot-reload, no Docker for services)
```bash
just infra-up       # start postgres, rabbitmq, redis, seaweedfs
just run-api        # terminal 1 — FastAPI with hot-reload on :8080
just run-worker     # terminal 2 — worker consuming from RabbitMQ
```

### Docker workflow
```bash
just build          # rebuild api + worker images
just deploy         # rebuild and restart api + worker
just status         # show all service status
just logs-api       # follow API logs
just logs-worker    # follow Worker logs
```

### Database migrations
```bash
just migrate                    # apply pending migrations
just migration "add new table"  # generate new migration
```

### Code quality
```bash
just lint       # ruff check
just lint-fix   # ruff check --fix
just typecheck  # pyright
just test       # pytest
just check      # lint + typecheck + test
```

## Monorepo Layout

```
justfile         # developer commands (just --list)
shared/          # shared Python package (domain, use cases, adapters)
services/api/    # FastAPI service
services/worker/ # RabbitMQ consumer
services/triton/ # Triton model configs
infra/           # config for postgres, rabbitmq, seaweedfs, prometheus, loki, grafana
opt/models/      # model weights (not in git)
```
