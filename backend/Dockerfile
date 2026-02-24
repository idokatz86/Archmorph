# ── Stage 1: Build — install dependencies in a throwaway layer ──
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime — slim image with only what's needed ──
FROM python:3.12-slim

WORKDIR /app

# Copy pre-built deps from builder (multi-stage = smaller image)
COPY --from=builder /install /usr/local

# Copy application
COPY . .

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && mkdir -p /app/data && chown -R appuser:appgroup /app
USER appuser

# Expose port
EXPOSE 8000

# Health check (using python — curl not available in slim)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run
# Production: multiple workers for concurrency (#103-S015)
# Use 2*CPU+1 formula; 4 workers for 2 vCPU Container Apps
# Issue #121: WEB_CONCURRENCY tells session store to use FileStore when no Redis
ENV WEB_CONCURRENCY=4
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
