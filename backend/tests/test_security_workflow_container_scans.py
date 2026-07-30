from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
BACKEND_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
MCP_GATEWAY_DOCKERFILE = REPO_ROOT / "mcp-gateway" / "Dockerfile"


def _load() -> dict:
    return yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f'Expected workflow step "{name}"')


def test_security_workflow_scans_all_production_runtime_images():
    workflow = _load()
    trivy_job = workflow["jobs"]["trivy-container"]

    image_matrix = trivy_job["strategy"]["matrix"]["image"]
    names = {item["name"] for item in image_matrix}

    assert names == {"backend", "mcp-gateway"}
    assert _step_by_name(
        trivy_job["steps"], "Build ${{ matrix.image.name }} image for scanning"
    )
    health_step = _step_by_name(
        trivy_job["steps"], "Container healthcheck smoke (${{ matrix.image.name }})"
    )
    assert "-e ENVIRONMENT=test" in health_step["run"]
    assert "-e ALLOWED_ORIGINS=https://frontend.example.com" in health_step["run"]


def test_security_workflow_uses_distinct_sarif_category_per_runtime_image():
    workflow = _load()
    upload_step = _step_by_name(
        workflow["jobs"]["trivy-container"]["steps"],
        "Upload Trivy SARIF to GitHub Security",
    )
    assert upload_step["with"]["category"] == "trivy-container-${{ matrix.image.name }}"
    assert (
        "hashFiles(format('trivy-results-{0}.sarif', matrix.image.name)) != ''"
        in upload_step["if"]
    )


def test_security_workflow_builds_scan_images_without_layer_cache():
    workflow = _load()
    build_step = _step_by_name(
        workflow["jobs"]["trivy-container"]["steps"],
        "Build ${{ matrix.image.name }} image for scanning",
    )

    assert build_step["with"]["pull"] is True
    assert build_step["with"]["no-cache"] is True
    assert "cache-from" not in build_step["with"]
    assert "cache-to" not in build_step["with"]


def test_security_workflow_keeps_required_trivy_status_context():
    workflow = _load()
    required_job = workflow["jobs"]["trivy-container-required"]

    assert required_job["name"] == "Container Scan — Trivy"
    assert required_job["needs"] == "trivy-container"


def test_runtime_images_upgrade_pip_before_dependency_install():
    for dockerfile in (BACKEND_DOCKERFILE, MCP_GATEWAY_DOCKERFILE):
        content = dockerfile.read_text(encoding="utf-8")
        assert 'pip install --no-cache-dir --upgrade "pip>=26.0"' in content
        assert content.index(
            'pip install --no-cache-dir --upgrade "pip>=26.0"'
        ) < content.index("pip install --no-cache-dir -r requirements.txt")


def test_runtime_images_pin_patched_python_packaging_tools():
    for dockerfile in (BACKEND_DOCKERFILE, MCP_GATEWAY_DOCKERFILE):
        content = dockerfile.read_text(encoding="utf-8")
        assert '"setuptools>=78.1.1"' in content


def test_runtime_images_remove_python_package_managers():
    backend_content = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    builder_marker = "FROM ${PYTHON_BASE_IMAGE} AS builder\n"
    runtime_marker = "\nFROM ${PYTHON_BASE_IMAGE}\n"
    preamble, marker, stages = backend_content.partition(builder_marker)
    assert marker == builder_marker
    assert "FROM " not in preamble
    builder_stage, marker, runtime_stage = stages.partition(runtime_marker)
    assert marker == runtime_marker
    assert "FROM " not in builder_stage
    assert "FROM " not in runtime_stage
    assert builder_stage.index(
        "pip install --no-cache-dir -r requirements.txt"
    ) < builder_stage.index("python -m pip uninstall --yes pip setuptools wheel")
    assert 'if python -c "import pip"' in runtime_stage
    assert runtime_stage.index('if python -c "import pip"') < runtime_stage.index(
        "COPY --from=builder /opt/venv /opt/venv"
    )
    assert "python -m pip uninstall --yes pip setuptools wheel" in runtime_stage
    assert "any(find_spec(name) for name in ('setuptools', 'wheel'))" in runtime_stage

    gateway_content = MCP_GATEWAY_DOCKERFILE.read_text(encoding="utf-8")
    assert gateway_content.index(
        "pip install --no-cache-dir -r requirements.txt"
    ) < gateway_content.index("python -m pip uninstall --yes pip setuptools wheel")
    assert gateway_content.index(
        "python -m pip uninstall --yes pip setuptools wheel"
    ) < gateway_content.index("COPY . .")
