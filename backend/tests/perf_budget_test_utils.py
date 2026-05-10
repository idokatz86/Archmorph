from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
PERF_BUDGET_SCRIPT = REPO_ROOT / "scripts" / "perf_budget.py"


def load_perf_budget_module():
    spec = importlib.util.spec_from_file_location("perf_budget", PERF_BUDGET_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module