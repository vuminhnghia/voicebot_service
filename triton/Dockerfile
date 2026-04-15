FROM nvcr.io/nvidia/tritonserver:25.12-vllm-python-py3

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/opt/models/hf_cache

WORKDIR /app

# System deps cho audio processing (soundfile + librosa)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && uv pip install --system --break-system-packages --no-cache -r pyproject.toml


# Triton ports: 8000 HTTP | 8001 gRPC | 8002 metrics
EXPOSE 8000 8001 8002
