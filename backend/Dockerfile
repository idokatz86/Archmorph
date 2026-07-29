# ══════════════════════════════════════════════════════════════
# Multi-stage Dockerfile for Archmorph Backend (#378)
# Stage 1: Builder — compile deps with build tools
# Stage 2: Runtime — minimal image, non-root user
# Expected ~50% image size reduction vs single-stage
# ══════════════════════════════════════════════════════════════

# ── Stage 1: Builder ─────────────────────────────────────────
ARG PYTHON_BASE_IMAGE=python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG ARCHMORPH_SOURCE_SHA
ARG ARCHMORPH_SOURCE_REPOSITORY
ARG ARCHMORPH_BUILD_WORKFLOW
ARG ARCHMORPH_BUILD_RUN_ID
ARG ARCHMORPH_BUILD_RUN_ATTEMPT
ARG ARCHMORPH_IMAGE_PLATFORM
ARG ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS
ARG ARCHMORPH_SCHEMA_CONTRACT_DIGEST
FROM ${PYTHON_BASE_IMAGE} AS builder

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        gcc g++ python3-dev build-essential libc6-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Isolated venv for clean copy to runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade "pip>=26.0" "setuptools>=78.1.1" wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m pip uninstall --yes pip setuptools wheel

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM ${PYTHON_BASE_IMAGE}

ARG ARCHMORPH_SOURCE_SHA
ARG ARCHMORPH_SOURCE_REPOSITORY
ARG ARCHMORPH_BUILD_WORKFLOW
ARG ARCHMORPH_BUILD_RUN_ID
ARG ARCHMORPH_BUILD_RUN_ATTEMPT
ARG ARCHMORPH_IMAGE_PLATFORM
ARG ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS
ARG ARCHMORPH_SCHEMA_CONTRACT_DIGEST

LABEL org.opencontainers.image.revision="${ARCHMORPH_SOURCE_SHA}" \
    org.opencontainers.image.source="https://github.com/${ARCHMORPH_SOURCE_REPOSITORY}" \
    io.archmorph.build.workflow="${ARCHMORPH_BUILD_WORKFLOW}" \
    io.archmorph.build.run-id="${ARCHMORPH_BUILD_RUN_ID}" \
    io.archmorph.build.run-attempt="${ARCHMORPH_BUILD_RUN_ATTEMPT}" \
    io.archmorph.image.platform="${ARCHMORPH_IMAGE_PLATFORM}" \
    io.archmorph.release-role="final" \
    io.archmorph.schema-accepted-revisions="${ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS}" \
    io.archmorph.schema-contract-digest="${ARCHMORPH_SCHEMA_CONTRACT_DIGEST}"

# Runtime dependencies come from /opt/venv; package managers are not needed here.
RUN if python -c "import pip" >/dev/null 2>&1; then \
        python -m pip uninstall --yes pip setuptools wheel; \
    else \
        python -c "from importlib.util import find_spec; import sys; sys.exit(1 if any(find_spec(name) for name in ('setuptools', 'wheel')) else 0)"; \
    fi

# Runtime-only system deps (libpq for psycopg2, curl for healthcheck)
# Apply current Debian security patches before installing runtime packages.
RUN apt-get update && \
    apt-get upgrade -y && \
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
COPY --chown=appuser:appgroup schema-contract.json /app/release/schema-contract.json

RUN mkdir -p /app/data && chown -R appuser:appgroup /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/healthz || exit 1

# Run with gunicorn config file (#369)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
