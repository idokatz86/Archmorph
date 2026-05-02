# Archmorph Realtime Status

**Updated:** May 2, 2026

## Repository State

- Active branch: `main`
- Open pull requests: none
- Remote branches: `main` only
- Local working state after convergence: synced to `origin/main`

## Landed Convergence Work

- #651 merged: service catalog hot reload now has bounded blob timeouts and better failure logging.
- #652 merged: scheduled job freshness is durable, visible in `/api/health`, and failure-aware.
- #649 merged: stale analytics retention/export references were removed.
- #667 merged: SSO, organization, profile, and multi-tenant router surfaces were removed from the active API.
- #666 merged: Architecture Package HTML/SVG exports are now available beside classic diagram exports.

## Current Product Spine

The live value spine is now: upload/sample -> analyze -> guided answers -> Azure mapping -> IaC/HLD/cost -> Architecture Package or classic diagram export. Beta/scaffold surfaces remain clearly labeled until they have production evidence.

## Remaining Backlog Shape

The highest-priority open work is no longer branch convergence. It is now production hardening for generated artifacts, Azure Landing Zone fidelity, security bounds on export/upload surfaces, and engineer-friendly validation evidence.

Newly opened convergence follow-ups:

- #669 Generated artifact validation matrix
- #670 Source-to-Azure IaC traceability map
- #671 Capability-token boundary for export and download endpoints
- #672 Cost assumptions file for migration packages
- #673 Production smoke: validate the full Architecture Package value spine
- #674 DR readiness rubric in Architecture Package output
- #675 Azure Landing Zone IaC profile with CAF and AVM defaults
- #676 Artifact manifest for Architecture Package exports

Issue #668 remains open with a triage note until the deployed `/api/health.scheduled_jobs` payload confirms `service_catalog_refresh` is no longer stale.