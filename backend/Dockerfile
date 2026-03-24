# ══════════════════════════════════════════════════════════════
# Multi-stage Dockerfile for Archmorph Backend (#378)
# Stage 1: Builder — compile deps with build tools
# Stage 2: Runtime — minimal image, non-root user
# Expected ~50% image size reduction vs single-stage
# ══════════════════════════════════════════════════════════════

# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ python3-dev build-essential libc6-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Isolated venv for clean copy to runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade "pip>=26.0" setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM python:3.12-slim-bookworm

# Upgrade system pip to fix CVE-2026-1703 and CVE-2025-8869
RUN pip install --no-cache-dir --upgrade "pip>=26.0"

# Runtime-only system deps (libpq for psycopg2, curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user (UID 1000 matches Helm securityContext)
RUN addgroup --system --gid 1000 appgroup && \
    adduser --system --uid 1000 --ingroup appgroup appuser

WORKDIR /app

# Copy venv from builder (no gcc/build-essential carried over)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy application code (.dockerignore excludes tests, docs, .git)
COPY --chown=appuser:appgroup . .

RUN mkdir -p /app/data && chown -R appuser:appgroup /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

# Run with gunicorn config file (#369)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
