# ══════════════════════════════════════════════════════════════
# Multi-stage Dockerfile for Archmorph Backend (#378)
# Stage 1: Builder — install deps in a throwaway image
# Stage 2: Runtime — copy only what's needed for production
# ══════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──
FROM mcr.microsoft.com/oryx/python:3.12-debian-bookworm AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade setuptools>=78.1.1 wheel>=0.46.2 && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM mcr.microsoft.com/oryx/python:3.12-debian-bookworm

WORKDIR /app

# Copy installed packages from builder
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

# Run with gunicorn config file (#369)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
