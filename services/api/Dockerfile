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

# Layer 2: api-specific code (main.py, api/routers/) — overlays on top
COPY services/api/app ./app/

# Alembic lives in shared
COPY shared/alembic ./alembic/
COPY shared/alembic.ini .

COPY services/api/entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
