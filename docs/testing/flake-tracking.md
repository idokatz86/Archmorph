# Flake Tracking Dashboard

This dashboard keeps backend test flakes visible instead of masking them with default `pytest` retries.

## Current Policy

- Default backend `pytest` runs must not use `--reruns`, `--reruns-delay`, or `pytest-rerunfailures`.
- CI fails through `scripts/lint_pytest_no_reruns.py` if retry flags or the rerun plugin appear in default pytest config, workflow files, or backend requirements.
- A failed backend test should stay red until the race, isolation gap, timing bug, or fixture leak is understood.

## Flake Intake

| Field | Required Evidence |
| --- | --- |
| Test | Fully qualified test path and name |
| Workflow | GitHub Actions run URL and job name |
| First failure | Error excerpt from the first failing attempt |
| Local reproduction | Command used locally, including seed or worker count when relevant |
| Suspected owner | Backend, API, infra, data, or frontend boundary |
| Status | New, triaged, fixed, or quarantined with owner approval |

## Triage Rules

1. Open or update a tracking issue with the evidence above.
2. Prefer a root-cause fix over retrying the test.
3. Use `pytest --lf` locally only as a diagnostic shortcut; do not commit it into default config or CI commands.
4. Quarantine only when an owner accepts the risk and creates a dated follow-up issue.
5. Close the flake entry only after the fix lands and the affected workflow passes without automatic retries.

## Dashboard Queue

| Issue | Test | Symptom | Owner | Status | Last Seen |
| --- | --- | --- | --- | --- | --- |
| _None currently open_ | | | | | |