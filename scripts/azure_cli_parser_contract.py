#!/usr/bin/env python3
"""Exercise the installed Azure CLI Container Apps Job args parser offline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from migration_runtime_contract import (  # noqa: E402
    build_runtime_envelope,
    containerapp_job_start_argv,
)


def _run(argv: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )


def run_contract(
    azure_cli: str,
    *,
    expected_version: str = "",
) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    preflight_envelope = build_runtime_envelope(
        mode="preflight",
        accepted_current=("013", "014"),
        execution_marker="preflight-parser-contract",
        image_digest=digest,
    )
    migration_envelope = build_runtime_envelope(
        mode="migrate",
        expected_head="014",
        execution_marker="migration-parser-contract",
        image_digest=digest,
    )
    with tempfile.TemporaryDirectory(prefix="archmorph-az-parser-") as config_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "AZURE_CONFIG_DIR": config_dir,
                "AZURE_CORE_COLLECT_TELEMETRY": "false",
                "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
            }
        )
        version_result = _run(
            [azure_cli, "version", "--output", "json"],
            environment=environment,
        )
        if version_result.returncode != 0:
            raise AssertionError("Azure CLI version could not be determined")
        try:
            azure_cli_version = str(json.loads(version_result.stdout)["azure-cli"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise AssertionError("Azure CLI version response is malformed") from error
        if expected_version and azure_cli_version != expected_version:
            raise AssertionError(
                f"Azure CLI version {azure_cli_version} is not pinned {expected_version}"
            )
        accepted_argv = {
            "preflight": containerapp_job_start_argv(
                job_name="placeholder-job",
                resource_group="placeholder-rg",
                container_name="migrate",
                command=("python", "run_migrations.py"),
                runtime_envelope=preflight_envelope,
            ),
            "migrate": containerapp_job_start_argv(
                job_name="placeholder-job",
                resource_group="placeholder-rg",
                runtime_envelope=migration_envelope,
            ),
        }
        for argv in accepted_argv.values():
            argv[0] = azure_cli
        old_argv = [
            azure_cli,
            "containerapp",
            "job",
            "start",
            "--name",
            "placeholder-job",
            "--resource-group",
            "placeholder-rg",
            "--args",
            "--expect-head",
            "014",
            "--query",
            "name",
            "--output",
            "tsv",
        ]
        accepted = {
            mode: _run(argv, environment=environment)
            for mode, argv in accepted_argv.items()
        }
        rejected = _run(old_argv, environment=environment)

    rejected_output = rejected.stdout + rejected.stderr
    for mode, result in accepted.items():
        accepted_output = result.stdout + result.stderr
        if "unrecognized arguments" in accepted_output.lower():
            raise AssertionError(
                f"canonical {mode} envelope was rejected by the Azure CLI parser"
            )
        if "az login" not in accepted_output.lower():
            raise AssertionError(
                f"canonical {mode} envelope did not reach authentication"
            )
    if rejected.returncode == 0 or "unrecognized arguments" not in rejected_output.lower():
        raise AssertionError(
            "legacy leading-option migration args unexpectedly passed Azure CLI parsing"
        )
    envelopes = {
        "preflight": preflight_envelope,
        "migrate": migration_envelope,
    }
    envelope_arg_counts: dict[str, int] = {}
    for mode, argv in accepted_argv.items():
        envelope = envelopes[mode]
        args_index = argv.index("--args")
        envelope_arg_counts[mode] = argv.count(envelope)
        if argv[args_index + 1] != envelope or envelope_arg_counts[mode] != 1:
            raise AssertionError(
                f"canonical {mode} envelope was not one argv token"
            )
    return {
        "status": "passed",
        "azure_cli_version": azure_cli_version,
        "accepted_returncodes": {
            mode: result.returncode for mode, result in accepted.items()
        },
        "legacy_returncode": rejected.returncode,
        "envelope_arg_counts": envelope_arg_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-az", action="store_true")
    parser.add_argument("--expected-version", default="")
    arguments = parser.parse_args()
    azure_cli = shutil.which("az")
    if azure_cli is None:
        if arguments.require_az:
            raise RuntimeError("az is required for the CI parser contract")
        print(json.dumps({"status": "skipped", "reason": "az is not installed"}))
        return 0
    print(
        json.dumps(
            run_contract(azure_cli, expected_version=arguments.expected_version),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())