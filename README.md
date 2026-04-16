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
- NVIDIA GPU + CUDA drivers (for Triton)
- Model weights in `opt/models/` (see below)

## Quick Start

### 1. Prepare model weights
```bash
mkdir -p opt/models/parakeet_asr opt/models/mms_tts_vie
# Export models (requires GPU):
# python services/triton/scripts/export_parakeet.py
# python services/triton/scripts/export_mms_tts.py
```

### 2. Start infrastructure (no GPU needed)
```bash
docker compose up -d postgres rabbitmq redis seaweedfs
```

### 3. Start full stack
```bash
docker compose up -d
```

### 4. Verify
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

### Rebuild services after code change
```bash
docker compose build api worker
docker compose up -d api worker
```

### View logs
```bash
docker compose logs -f api
docker compose logs -f worker
```

### Run DB migrations manually
```bash
docker exec voicebot-api alembic upgrade head
```

## Monorepo Layout

```
shared/          # Shared Python package (domain, use cases, adapters)
services/api/    # FastAPI service
services/worker/ # RabbitMQ consumer
services/triton/ # Triton model configs
infra/           # Config for postgres, rabbitmq, seaweedfs, prometheus, loki, grafana
opt/models/      # Model weights (not in git)
```
