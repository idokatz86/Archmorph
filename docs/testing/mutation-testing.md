# Mutation Testing Baseline

Archmorph tracks mutation score for the backend modules where line coverage can most easily overstate safety:

- `backend/session_store.py`
- `backend/vision_analyzer.py`
- `backend/iac_generator.py`

## Policy

- The committed baseline in `docs/testing/mutation-baseline.json` requires each critical module to stay at or above 60% mutation score.
- `.github/workflows/mutation-testing.yml` runs quarterly and can be started manually from GitHub Actions.
- The workflow runs `mutmut` against each critical module, uploads the raw result artifact, and then runs `scripts/mutation_score_gate.py`.
- A score drop below baseline fails the workflow, creating a GitHub Actions alert that should be triaged like a quality regression.

## Local Usage

Install backend dependencies and `mutmut`, then run the local Make target:

```bash
make mutation-baseline
```

To evaluate existing result files without rerunning mutation tests:

```bash
python scripts/mutation_score_gate.py \
  --baseline docs/testing/mutation-baseline.json \
  --report-dir mutation-results
```

## Updating the Baseline

Only raise or lower the baseline after reviewing the raw `mutmut` output and the affected tests. Baseline reductions require a linked issue explaining why surviving mutants are acceptable or how the team will close the gap later.