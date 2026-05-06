# Architecture Rules Roadmap (#662)

Issue #662 expands the curated architecture-rule library from 25 rules to 40+
rules while keeping the engine YAML-driven and backward compatible.

## Current Status

| Metric | Value |
| --- | ---: |
| Current curated rules | 25 |
| Target curated rules | 40+ |
| Rules needed for target | 15+ |
| Current rule source | `backend/data/architecture_rules.yaml` |
| Engine entry point | `architecture_rules.evaluate()` |
| Test entry point | `backend/tests/test_architecture_rules.py` |

## Phase Plan

| Phase | Status | Scope | Exit Criteria |
| --- | --- | --- | --- |
| Phase 1 | In progress | Authoring guide and roadmap tracker. | `README.md` and this roadmap exist under `backend/architecture_rules/`. |
| Phase 2 | Planned | First 5 additive rules: disaster recovery, edge security, identity, backup posture, tagging policy. | Rules, predicates if needed, and positive/negative tests merged. |
| Phase 3 | Planned | Next 6 additive rules: Private Link, secrets management, observability overlap, regulated workload hints, multi-domain validation, tenancy detector. | Rules, predicates if needed, and positive/negative tests merged. |
| Phase 4 | Planned | Additional 4+ backlog rules selected from production learnings or CTO gap candidates. | Library reaches at least 40 curated rules. |

## Candidate Rule Backlog

| Candidate | Category | Likely Severity | Predicate Strategy | Status |
| --- | --- | --- | --- | --- |
| Cross-region replication missing for stateful workloads | resilience | warning | New `cross_region_replication_present` or composition of service/count checks. | Planned |
| Edge service without WAF or DDoS posture | security | warning | Existing service/category predicates, possibly new endpoint predicate. | Planned |
| Identity layer missing for user-facing app | identity-auth | warning | Existing `category_present_without_companion`. | Planned |
| Backup posture missing for database/storage | resilience | warning | Existing companion predicate or backup-specific helper. | Planned |
| Required tags not represented in governance design | governance | info | New tag/governance evidence predicate if analysis carries tags. | Planned |
| Database or storage public path without Private Link | network-topology | warning | Existing service co-occurrence plus new endpoint predicate if needed. | Planned |
| Secrets without Key Vault or managed secret store | security | warning | New `secret_storage_provider`. | Planned |
| Duplicate observability stacks or no observability anchor | operations | info | Existing category/service predicates. | Planned |
| Regulated workload without compliance boundary | governance | warning | Existing category/service predicates plus tags. | Planned |
| Multi-domain architecture without clear boundary services | architecture | info | New or composite domain-count predicate. | Planned |
| Multi-tenant signals without tenant isolation | architecture | warning | New tenancy detector predicate. | Planned |
| Queue or eventing without dead-letter path | data-plane | warning | Existing `category_present_without_companion`. | Candidate |
| Internet-facing app without rate limiting | security | warning | Existing service/category predicates. | Candidate |
| Stateful workload without zone or region posture | resilience | warning | Existing service/count predicates. | Candidate |
| Cost-sensitive design using premium edge services everywhere | cost | info | Existing service-count predicates. | Candidate |

## Progress Log

| Date | Change | Rule Count |
| --- | --- | ---: |
| 2026-05-06 | Phase 1 scaffold: authoring guide and roadmap tracker. | 25 |

## Validation Gates

Before closing #662:

- `backend/data/architecture_rules.yaml` contains at least 40 unique rule IDs.
- Every new predicate is registered and covered by unit tests.
- Every new rule has positive and negative fixture coverage.
- `./.venv/bin/python -m pytest tests/test_architecture_rules.py tests/test_iac_blocker_gate.py -q` passes from `backend/`.
- `docs/ARCHITECTURE_RULES.md` and `README.md` counts are updated if the public rule count changes.
