#!/usr/bin/env python3
"""
Export the Archmorph OpenAPI schema to a JSON file.

Usage:
    # From a running server:
    curl -s http://localhost:8000/openapi.json > openapi.json

    # From the backend directory (requires all deps):
    python export_openapi.py > openapi.json

Used by CI to generate the API contract for type generation
and schema drift detection.
"""

import json
import os
import sys
import warnings
from contextlib import redirect_stdout
from io import StringIO

# Ensure backend modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suppress startup logs and use in-memory defaults
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "ERROR")
os.environ.setdefault("DATABASE_URL", "sqlite:///./openapi_export.db")

warnings.filterwarnings("ignore", message="Duplicate Operation ID.*")

with redirect_stdout(StringIO()):
    from main import app  # noqa: E402


def export_schema():
    """Export the OpenAPI schema from the FastAPI app."""
    with redirect_stdout(StringIO()):
        schema = app.openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    print(export_schema())
