"""Executable Azure CLI parser contract for migration runtime arguments."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "azure_cli_parser_contract.py"


def test_installed_azure_cli_accepts_envelope_and_rejects_leading_flags():
    if shutil.which("az") is None:
        pytest.skip("az is not installed")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["azure_cli_version"]
    assert payload["envelope_arg_counts"] == {"preflight": 1, "migrate": 1}
    assert set(payload["accepted_returncodes"]) == {"preflight", "migrate"}
    assert payload["legacy_returncode"] != 0