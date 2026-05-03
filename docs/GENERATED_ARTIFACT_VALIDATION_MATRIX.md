# Generated Artifact Validation Matrix

This matrix is the release-control view for generated customer artifacts. It shows which outputs are contract-tested, snapshot-tested, smoke-tested, or manually reviewed before release sign-off.

## Coverage Matrix

| Artifact | Owner Agent | Contract Test | Snapshot Test | Production Smoke | Fixture / Sample | Release Evidence | Gap Tracking |
|---|---|---|---|---|---|---|---|
| Architecture Package HTML | QA Master | `cd backend && .venv/bin/python -m pytest tests/test_architecture_package.py -q` | Missing visual snapshot | `./scripts/architecture_package_smoke.sh` checks required sections and inline SVG | `aws-hub-spoke` sample and `SAMPLE_ANALYSIS` in `tests/test_architecture_package.py` | `architecture-package-smoke-<run id>/artifacts/architecture-package.html` plus `summary.md` | #699 |
| Architecture Package target SVG | QA Master | `cd backend && .venv/bin/python -m pytest tests/test_architecture_package.py tests/test_azure_landing_zone*.py -q` | Missing visual snapshot | Smoke parses SVG XML and checks target topology text | `aws-hub-spoke` sample and landing-zone canonical fixtures | `architecture-package-smoke-<run id>/artifacts/target.svg` | #699 |
| Architecture Package DR SVG | QA Master | `cd backend && .venv/bin/python -m pytest tests/test_architecture_package.py tests/test_azure_landing_zone*.py -q` | Missing visual snapshot | Smoke parses SVG XML and checks DR/resilience language | `aws-hub-spoke` sample and landing-zone canonical fixtures | `architecture-package-smoke-<run id>/artifacts/dr.svg` | #699 |
| Classic diagram exports | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_diagram_export.py -q` validates Excalidraw, Draw.io, and VDX structure | No golden snapshot for all formats | Smoke validates Excalidraw only | `tests/test_diagram_export.py` mock analysis | `architecture-package-smoke-<run id>/artifacts/classic.excalidraw` | #701 |
| IaC output | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_iac_generator.py tests/test_iac_blocker_gate.py -q` | No golden snapshot for every format | Smoke validates Terraform shape with `force=true` | Sample analysis fixtures in IaC tests and `aws-hub-spoke` smoke sample | `architecture-package-smoke-<run id>/artifacts/archmorph-iac.tf` | #701 |
| HLD markdown | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_hld_generator.py -q` | No customer-facing markdown snapshot | Smoke validates non-empty Azure-referencing markdown | `aws-hub-spoke` sample and HLD generator fixtures | `architecture-package-smoke-<run id>/artifacts/hld.md` | #701 |
| HLD DOCX/PDF/PPTX | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_hld_export.py -q` validates export bytes and format dispatch | No full document snapshot | Smoke decodes DOCX only | `MOCK_HLD` fixtures in `tests/test_hld_export.py` | `architecture-package-smoke-<run id>/artifacts/hld.docx` | #701 |
| Cost estimate JSON | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_cost_artifacts_contract.py -q` validates currency, service rows, and total monthly estimate | Contract snapshot fixture in `tests/fixtures/cost_estimate_contract.json` | Smoke validates USD currency and service rows | `aws-hub-spoke` sample and cost contract fixture | `architecture-package-smoke-<run id>/raw/08-cost.json` | #703 |
| Cost CSV | Backend Master | `cd backend && .venv/bin/python -m pytest tests/test_cost_artifacts_contract.py -q` validates CSV header, rows, overrides, and TOTAL reconciliation | Contract snapshot fixture in `tests/fixtures/cost_estimate_contract.json` | Smoke checks `Service,` header and `TOTAL` row | `aws-hub-spoke` sample and cost contract fixture | `architecture-package-smoke-<run id>/artifacts/cost-estimate.csv` | #703 |
| OpenAPI schema | API Master | `cd backend && python export_openapi.py > openapi.json && python check_openapi_contract.py openapi.json` | `backend/openapi.snapshot.json` is the committed contract snapshot | `./scripts/deployment_smoke.sh` checks deployed `/openapi.json` title | FastAPI app schema generation | CI `openapi-schema` artifact and post-deploy smoke summary | #700 |

## Release Evidence Locations

- CI/CD: backend test logs, OpenAPI schema artifact, frontend build artifact, SBOM and scanner outputs.
- Production Architecture Package Smoke: `smoke-artifacts/architecture-package/<run id>/summary.md`, `manifest.json`, `raw/`, and `artifacts/`.
- Release checklist: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) section 4 requires the Architecture Package smoke with `strict_freshness=true`.

## Operator Notes

- Treat this matrix as the source of truth for release evidence. If a generated artifact changes customer-visible behavior, update the relevant row in the same PR.
- Missing coverage must be tracked as an issue in the `Gap Tracking` column. Do not leave uncovered release risk only in prose.
- The main production smoke should stay fast enough for release sign-off. Broader secondary-format coverage can run as a matrix or scheduled workflow once #701 is implemented.