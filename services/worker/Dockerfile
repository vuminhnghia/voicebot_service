FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Install deps from shared package definition
COPY shared/pyproject.toml .
RUN pip install --no-cache-dir uv \
 && uv pip install --system --no-cache -r pyproject.toml

# Layer 1: shared code (domain, application, infrastructure, schemas, config)
COPY shared/app ./app/

# Layer 2: worker-specific code (app/worker/main.py) — overlays on top
COPY services/worker/app ./app/

# Alembic lives in shared
COPY shared/alembic ./alembic/
COPY shared/alembic.ini .

COPY services/worker/entrypoint.sh .
RUN chmod +x entrypoint.sh

CMD ["python", "-m", "app.worker.main"]
