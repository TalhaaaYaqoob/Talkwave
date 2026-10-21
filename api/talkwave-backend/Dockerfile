# ============================================================================
# TalkWave Backend - Production Dockerfile
# ============================================================================
# Optimized for fast re-deploys: dependency layers are cached separately
# from application code so code-only pushes skip pip install entirely.

# Stage 1: Builder - Install Python dependencies (CACHED between deploys)
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencies (cached — only rebuilds when requirements.txt changes) ──
COPY requirements.txt .
RUN pip install --user --upgrade pip && \
    pip install --user -r requirements.txt

RUN find /root/.local -type f -name '*.pyc' -delete && \
    find /root/.local -type d -name '__pycache__' -delete && \
    find /root/.local -type f -name '*.pyo' -delete

# Stage 2: Runtime - Minimal image
FROM python:3.12-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder (CACHED — this layer doesn't change
# unless requirements.txt or pipecat-requirements.txt change)
COPY --from=builder /root/.local /root/.local

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── Layer 3: pipecat source (changes occasionally) ──
COPY pipecat/src/pipecat /app/pipecat

# ── Layer 4: application code (changes on every push — FAST) ──
COPY . /app/api

ENV PYTHONPATH=/app

RUN mkdir -p /app/logs /app/run && \
    chmod +x /app/api/start.sh

EXPOSE 8000
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; import os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8000)}/api/v1/health')" || exit 1

CMD ["/app/api/start.sh"]
