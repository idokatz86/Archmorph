import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]
DOCKER_GUARD = REPO_ROOT / "scripts" / "lint_docker_base_images.py"


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("lint_docker_base_images", DOCKER_GUARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


find_violations = _load_guard_module().find_violations


@pytest.mark.parametrize(
    "image",
    [
        "node:22",
        "node:22-alpine",
        "node:22.13-alpine",
        "docker.io/library/node:22.13.1-alpine",
    ],
)
def test_rejects_floating_node_base_images(tmp_path, image):
    dockerfile = tmp_path / "frontend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(f"FROM {image} AS build\n", encoding="utf-8")

    violations = find_violations([dockerfile])

    assert len(violations) == 1
    assert image in violations[0]


@pytest.mark.parametrize(
    "image",
    [
        "python:3.12-slim-bookworm",
        "python:3.12.9-slim-bookworm",
        "docker.io/library/python:3.12.9-slim-bookworm",
    ],
)
def test_rejects_floating_python_base_images_without_digest(tmp_path, image):
    dockerfile = tmp_path / "backend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(f"FROM {image}\n", encoding="utf-8")

    violations = find_violations([dockerfile])

    assert len(violations) == 1
    assert image in violations[0]


def test_allows_node_patch_tag_with_sha256_digest(tmp_path):
    digest = "a" * 64
    dockerfile = tmp_path / "frontend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(f"FROM node:22.13.1-alpine@sha256:{digest} AS build\n", encoding="utf-8")

    assert find_violations([dockerfile]) == []


def test_allows_python_patch_tag_with_sha256_digest(tmp_path):
    digest = "b" * 64
    dockerfile = tmp_path / "backend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(f"FROM python:3.12.9-slim-bookworm@sha256:{digest}\n", encoding="utf-8")

    assert find_violations([dockerfile]) == []


def test_rejects_floating_node_base_image_from_arg(tmp_path):
    dockerfile = tmp_path / "frontend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("ARG NODE_IMAGE=node:22\nFROM ${NODE_IMAGE} AS build\n", encoding="utf-8")

    violations = find_violations([dockerfile])

    assert len(violations) == 1
    assert "${NODE_IMAGE}" in violations[0]


def test_rejects_floating_python_base_image_from_arg(tmp_path):
    dockerfile = tmp_path / "backend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("ARG PYTHON_IMAGE=python:3.12.9-slim-bookworm\nFROM ${PYTHON_IMAGE}\n", encoding="utf-8")

    violations = find_violations([dockerfile])

    assert len(violations) == 1
    assert "${PYTHON_IMAGE}" in violations[0]


def test_skips_non_file_paths(tmp_path):
    missing = tmp_path / "missing.Dockerfile"

    assert find_violations([tmp_path, missing]) == []


def test_ignores_non_node_python_base_images(tmp_path):
    dockerfile = tmp_path / "backend" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM alpine:3.20\n", encoding="utf-8")

    assert find_violations([dockerfile]) == []
