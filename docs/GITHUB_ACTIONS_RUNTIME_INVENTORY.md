# GitHub Actions Runtime Inventory

Issue: #720
Date: 2026-05-03

This inventory tracks the workflow action runtime migration away from deprecated Node.js 20 actions before GitHub hosted runners force Node.js 24 defaults.

## Runtime Evidence

| Action | Previous pin | Latest observed | Runtime before | New pin | Runtime after | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `actions/checkout` | `v4` | `v6.0.2` | `node20` | `v6` | `node24` | Upgraded; major pin tracks Node 24-compatible patch releases. |
| `actions/setup-node` | `v4` | `v6.4.0` | `node20` | `v6` | `node24` | Upgraded; application Node version remains controlled by `node-version`. |
| `actions/setup-python` | `v5` | `v6.2.0` | `node20` | `v6` | `node24` | Upgraded; Python version remains `3.12`. |
| `actions/github-script` | `v7` | `v9.0.0` | `node20` | `v9` | `node24` | Upgraded for alert-issue workflows. |
| `actions/upload-artifact` | `v7` | `v7` | `node24` | unchanged | `node24` | Already compatible. |
| `actions/download-artifact` | `v8` | `v8` | `node24` | unchanged | `node24` | Already compatible. |
| `actions/labeler` | `v6` | `v6` | `node24` | unchanged | `node24` | Already compatible. |
| `actions/stale` | `v10` | `v10` | `node24` | unchanged | `node24` | Already compatible. |
| `amannn/action-semantic-pull-request` | `v6.1.1` | `v6.1.1` | `node24` | unchanged | `node24` | Already compatible. |
| `anchore/scan-action` | `v7` | `v7` | `node24` | unchanged | `node24` | Already compatible. |
| `astral-sh/setup-uv` | `v7` | `v7` | `node24` | unchanged | `node24` | Already compatible. |
| `docker/setup-buildx-action` | `v4` | `v4` | `node24` | unchanged | `node24` | Already compatible. |
| `docker/build-push-action` | `v7` | `v7` | `node24` | unchanged | `node24` | Already compatible. |
| `github/codeql-action/*` | `v4` | `v4.35.3` | `node24` | unchanged | `node24` | Latest CodeQL major is already in use; `init`, `analyze`, and `upload-sarif` all report `node24`. |
| `azure/login` | `v3` | `v3.0.0` | `node24` | unchanged | `node24` | Latest Azure login major is already in use. |
| `Azure/static-web-apps-deploy` | `v1` | `v1` | docker action | unchanged | docker action | No newer stable major exists. |
| `aquasecurity/trivy-action` | `master` | `v0.36.0` | unpinned composite action | `v0.36.0` | composite release tag | Pinned to the latest release tag observed during audit. |

Blocked actions: none as of this audit. If a future action cannot be moved, record the owner and review date here before merging workflow changes.

## Validation Expectations

- Required PR checks pass.
- Main CI/CD proves Azure Container Apps blue-green deploy, Static Web Apps deploy, post-deploy smoke, K6 diagnostics, Playwright, and security scanning still work.
- Any future action that remains on a deprecated runtime should be listed here with owner and review date.
