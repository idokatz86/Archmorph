#!/usr/bin/env python3
"""Build a zero-traffic Container Apps revision document from live configuration."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path


_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


def _env_index(container: dict) -> dict[str, dict]:
    return {str(item.get("name")): item for item in container.setdefault("env", [])}


def build_revision_document(
    source: dict,
    *,
    image: str,
    revision_suffix: str,
    readiness_path: str,
    env_values: dict[str, str],
    env_secret_refs: dict[str, str],
) -> dict:
    """Clone live configuration and change only one new revision template."""
    if not _DIGEST_RE.fullmatch(image):
        raise ValueError("image must be an immutable sha256 digest reference")
    if not revision_suffix or not re.fullmatch(r"[a-z0-9-]+", revision_suffix):
        raise ValueError("revision suffix must use lowercase letters, digits, and hyphens")
    if not readiness_path.startswith("/"):
        raise ValueError("readiness path must be absolute")

    properties = source.get("properties") or {}
    template = copy.deepcopy(properties.get("template") or {})
    containers = template.get("containers") or []
    if len(containers) != 1:
        raise ValueError("exactly one application container is required")
    container = containers[0]
    container["image"] = image
    template["revisionSuffix"] = revision_suffix

    env = _env_index(container)
    for name, value in env_values.items():
        env[name] = {"name": name, "value": value}
    for name, secret_ref in env_secret_refs.items():
        env[name] = {"name": name, "secretRef": secret_ref}
    container["env"] = list(env.values())

    probes = container.setdefault("probes", [])
    readiness = next(
        (probe for probe in probes if str(probe.get("type", "")).lower() == "readiness"),
        None,
    )
    if readiness is None:
        readiness = {
            "type": "Readiness",
            "httpGet": {"port": 8000, "scheme": "HTTP"},
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 3,
            "successThreshold": 1,
        }
        probes.append(readiness)
    readiness.setdefault("httpGet", {})["path"] = readiness_path

    return {
        "type": "Microsoft.App/containerApps",
        "name": source.get("name"),
        "location": source.get("location"),
        "properties": {"template": template},
    }


def _pairs(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"expected NAME=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        if not name or not value:
            raise ValueError("environment names and values must be non-empty")
        result[name] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision-suffix", required=True)
    parser.add_argument("--readiness-path", required=True)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--secret-env", action="append", default=[])
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    document = build_revision_document(
        source,
        image=args.image,
        revision_suffix=args.revision_suffix,
        readiness_path=args.readiness_path,
        env_values=_pairs(args.env),
        env_secret_refs=_pairs(args.secret_env),
    )
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
