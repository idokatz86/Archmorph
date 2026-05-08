#!/usr/bin/env python3
"""
dump_configs.py — Generate a terraform.tfvars file from environment variables.

SECURITY: This script NEVER writes secrets into the git working tree.
Output is redirected to ~/.config/archmorph/ (XDG_CONFIG_HOME/archmorph
if set), which is outside any repository checkout.

Usage:
    python scripts/dump_configs.py [--output-dir DIR] [--env ENV]

Environment variables read:
    SUBSCRIPTION_ID, LOCATION, OPENAI_LOCATION, ENVIRONMENT,
    DB_ADMIN_USERNAME, DB_ADMIN_PASSWORD, ALERT_EMAIL, FRONTEND_URL,
    REDIS_CAPACITY, ENABLE_DR

Fixes #913.
"""

import argparse
import os
import re
import stat
import sys
import textwrap
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Safe output directory — never inside a git working tree
# ─────────────────────────────────────────────────────────────────────────────

def _safe_output_dir() -> Path:
    """Return the directory where tfvars will be written.

    Resolution order:
    1. $XDG_CONFIG_HOME/archmorph/  (respects XDG on Linux/macOS)
    2. ~/.config/archmorph/
    """
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "archmorph"


def _is_inside_git_repo(path: Path) -> bool:
    """Return True if *path* is under a git working tree."""
    check = path
    while True:
        if (check / ".git").exists():
            return True
        parent = check.parent
        if parent == check:
            break
        check = parent


def _safe_env_slug(env_name: str) -> str:
    """Return a validated environment slug for the output filename."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", env_name):
        print(
            "\n⛔  ERROR: --env must contain only letters, numbers, underscores, or dashes.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return env_name
    return False


def _ensure_safe_dir(output_dir: Path) -> None:
    """Abort if the chosen output dir is inside a git repo."""
    resolved = output_dir.resolve()
    if _is_inside_git_repo(resolved):
        print(
            f"\n⛔  ERROR: Refusing to write secrets inside a git working tree.\n"
            f"   Resolved path: {resolved}\n"
            f"   Use --output-dir to specify a directory outside any repository.\n",
            file=sys.stderr,
        )
        sys.exit(1)


def _ensure_safe_output_file(outfile: Path, output_dir: Path) -> None:
    """Abort if the resolved output file can escape the safe output dir."""
    resolved_dir = output_dir.resolve()
    resolved_file = outfile.resolve()
    if resolved_file.parent != resolved_dir or _is_inside_git_repo(resolved_file):
        print(
            f"\n⛔  ERROR: Refusing to write secrets to an unsafe path.\n"
            f"   Resolved path: {resolved_file}\n"
            f"   Use --output-dir outside any repository and a safe --env slug.\n",
            file=sys.stderr,
        )
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Variable collection
# ─────────────────────────────────────────────────────────────────────────────

_VARS: list[tuple[str, str, str, bool]] = [
    # (env_var, tfvar_name, default, is_sensitive)
    ("SUBSCRIPTION_ID",   "subscription_id",   "00000000-0000-0000-0000-000000000000", False),
    ("LOCATION",          "location",           "westeurope",                           False),
    ("OPENAI_LOCATION",   "openai_location",    "westeurope",                           False),
    ("ENVIRONMENT",       "environment",        "dev",                                  False),
    ("DB_ADMIN_USERNAME", "db_admin_username",  "",                                     False),
    ("DB_ADMIN_PASSWORD", "db_admin_password",  "",                                     True),
    ("ALERT_EMAIL",       "alert_email",        "",                                     False),
    ("FRONTEND_URL",      "frontend_url",       "https://localhost:5173",               False),
    ("REDIS_CAPACITY",    "redis_capacity",     "0",                                    False),
    ("ENABLE_DR",         "enable_dr",          "false",                                False),
]


def _collect_vars() -> dict[str, str]:
    values: dict[str, str] = {}
    missing_required: list[str] = []
    sensitive_defaults: list[str] = []

    for env_var, tf_var, default, is_sensitive in _VARS:
        val = os.environ.get(env_var, default)
        if not val and not default:
            missing_required.append(env_var)
        if is_sensitive and val == default and default == "":
            sensitive_defaults.append(env_var)
        values[tf_var] = val

    if missing_required:
        print(
            f"\n⚠️   Warning: the following required variables are not set "
            f"and have no default:\n  {', '.join(missing_required)}\n"
            f"  Set them as environment variables before running this script.\n",
            file=sys.stderr,
        )
    return values


# ─────────────────────────────────────────────────────────────────────────────
# HCL rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_tfvars(values: dict[str, str]) -> str:
    lines = [
        "# terraform.tfvars — generated by scripts/dump_configs.py",
        "# ⚠️  Contains secrets. Keep outside version control.",
        "",
    ]
    for tf_var, val in values.items():
        # Booleans
        if val.lower() in ("true", "false"):
            lines.append(f"{tf_var} = {val.lower()}")
        # Integers
        elif val.isdigit():
            lines.append(f"{tf_var} = {val}")
        # Strings
        else:
            escaped = val.replace('"', '\\"')
            lines.append(f'{tf_var} = "{escaped}"')
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        type=Path,
        default=None,
        help=(
            "Directory to write terraform.tfvars into "
            "(default: ~/.config/archmorph/). Must NOT be inside a git repo."
        ),
    )
    parser.add_argument(
        "--env",
        metavar="ENV",
        default=os.environ.get("ENVIRONMENT", "dev"),
        help="Environment tag appended to the output filename (default: dev).",
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir or _safe_output_dir()
    _ensure_safe_dir(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    env_slug = _safe_env_slug(args.env)
    outfile = output_dir / f"terraform.{env_slug}.tfvars"
    _ensure_safe_output_file(outfile, output_dir)

    values = _collect_vars()
    content = _render_tfvars(values)

    outfile.write_text(content, encoding="utf-8")

    # Restrict permissions: owner read/write only (no group/world access)
    outfile.chmod(stat.S_IRUSR | stat.S_IWUSR)

    print(
        textwrap.dedent(f"""
        ✅  terraform.tfvars written to:
            {outfile}

        ⚠️   SECURITY REMINDER:
            • This file contains secrets — do NOT copy it into your git working tree.
            • It is stored in your user config directory, outside any repository.
            • Permissions set to 600 (owner read/write only).
            • Rotate secrets stored in Azure Key Vault; do not commit passwords here.
        """).strip()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
