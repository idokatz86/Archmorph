# ══════════════════════════════════════════════════════════════
# Dockerfile for Archmorph Backend (#378)
# Uses python:3.12-slim-bookworm for minimal image with fewer CVEs
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim-bookworm

# Install system dependencies (libpq for psycopg2, gcc for compiling)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev build-essential libc6-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (layer cached)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove gcc && \
    rm -rf /root/.cache

# Copy application
COPY . .

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && mkdir -p /app/data && chown -R appuser:appgroup /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with gunicorn config file (#369)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
