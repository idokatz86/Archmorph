# Mappings Ownership

## Owner

Cloud Master agent owns the cross-cloud service mapping table in `backend/services/mappings.py`. The human backup is idokatz86.

## Review Cadence

Every mapping row must include `last_reviewed` in `YYYY-MM-DD` format. Rows should be re-reviewed at least every 180 days, with low-confidence rows (`confidence < 0.8`) treated as blocking when stale or missing a review date.

The quarterly GitHub Actions workflow opens a review issue on the first day of each quarter. The issue body contains the current freshness lint report so the owner can prioritize stale or low-confidence rows.

## Update Process

When a mapping changes, update the service names, confidence, notes, and `last_reviewed` date in the same PR. Prefer precise provider/product names over generic categories, and call out stale branding or engine-specific constraints in `notes` when that context protects customers from a wrong migration choice.

CI runs `scripts/lint_mappings_freshness.py` in non-blocking mode during the one-sprint soak. After the soak, remove `continue-on-error: true` from the CI job to make stale low-confidence rows block merges.
