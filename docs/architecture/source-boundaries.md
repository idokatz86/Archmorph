# Source dependency boundaries

Run the repository source-boundary gate with:

```bash
python3 scripts/check_source_boundaries.py
```

The checker parses Python imports under `backend/` and JavaScript/TypeScript
imports under `frontend/src/`. It rejects dependency cycles and dependencies
that point against these directions:

- backend: `bootstrap -> api/infrastructure -> application -> domain`;
- frontend: `app -> features -> shared`;
- within a frontend feature:
  `components -> orchestration/model/persistence -> api -> shared`.

The current backend names `routers`, `services`, `repositories`, and `models`
are treated as `api`, `application`, `infrastructure`, and `domain`
respectively. Current frontend `components` are treated as features, while
`services`, `hooks`, `stores`, `lib`, `utils`, and `generated` are shared.
Unclassified legacy modules are still included in cycle detection.

## Temporary exceptions

[`source-boundary-exceptions.json`](source-boundary-exceptions.json) is a
ratcheted baseline, not a general allowlist. Each entry must exactly match a
reported finding and include:

- `owner`: accountable team or person;
- `rationale`: why the violation cannot be removed now;
- `removal_reference`: issue or architecture backlog reference;
- `expires_on`: an ISO `YYYY-MM-DD` date.

The check fails for new findings, malformed or expired entries, duplicate
entries, and stale entries whose violation has been fixed. Removing a violation
therefore also requires removing its exception, and the baseline can only
decrease. New exceptions require architecture-owner review.
