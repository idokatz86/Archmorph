# Gunicorn configuration for Archmorph production (#369, #376)
# Usage: gunicorn -c gunicorn.conf.py main:app

import multiprocessing
import os

# ── Workers ──
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 9)))
worker_class = "uvicorn.workers.UvicornWorker"
threads = 1  # UvicornWorker uses asyncio, not threads

# ── Timeouts ──
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# ── Worker recycling (memory leak protection) ──
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 100

# ── Binding ──
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ── Logging ──
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# ── Preload for faster worker startup ──
preload_app = True

# ── Server header ──
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
