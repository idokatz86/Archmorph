#!/usr/bin/env python3
"""Initialize an Archmorph Terraform root with private partial-backend settings."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_ENV = (
    "TFSTATE_RESOURCE_GROUP",
    "TFSTATE_STORAGE_ACCOUNT",
    "TFSTATE_CONTAINER",
)


class BackendConfigError(ValueError):
    """Raised when private backend settings are incomplete or unsafe."""


def backend_config(environment: str, environ: Mapping[str, str]) -> dict[str, str]:
    if environment not in {"production", "staging"}:
        raise BackendConfigError("environment must be production or staging")

    missing = [name for name in COMMON_ENV if not environ.get(name, "").strip()]
    production_key = environ.get("TFSTATE_KEY", "").strip()
    staging_key = environ.get("TFSTATE_STAGING_KEY", "").strip()
    selected_key = production_key if environment == "production" else staging_key
    if not selected_key:
        missing.append("TFSTATE_KEY" if environment == "production" else "TFSTATE_STAGING_KEY")
    if missing:
        raise BackendConfigError("missing private backend settings: " + ", ".join(sorted(missing)))
    if environment == "staging" and production_key and production_key == staging_key:
        raise BackendConfigError("production and staging Terraform state keys must be distinct")

    return {
        "resource_group_name": environ["TFSTATE_RESOURCE_GROUP"].strip(),
        "storage_account_name": environ["TFSTATE_STORAGE_ACCOUNT"].strip(),
        "container_name": environ["TFSTATE_CONTAINER"].strip(),
        "key": selected_key,
    }


def build_init_command(terraform: str, working_dir: Path, config: Mapping[str, str]) -> list[str]:
    return [
        terraform,
        f"-chdir={working_dir}",
        "init",
        "-input=false",
        "-lockfile=readonly",
        *(f"-backend-config={name}={value}" for name, value in config.items()),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("production", "staging"), required=True)
    parser.add_argument("--working-dir", type=Path)
    args = parser.parse_args(argv)

    working_dir = args.working_dir or (
        REPO_ROOT / "infra" if args.environment == "production" else REPO_ROOT / "infra/staging"
    )
    terraform = shutil.which("terraform")
    if not terraform:
        print("Terraform executable not found", file=sys.stderr)
        return 1

    try:
        config = backend_config(args.environment, os.environ)
    except BackendConfigError as exc:
        print(f"Terraform backend configuration error: {exc}", file=sys.stderr)
        return 1

    completed = subprocess.run(
        build_init_command(terraform, working_dir.resolve(), config),
        cwd=REPO_ROOT,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
