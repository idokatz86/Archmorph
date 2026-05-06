# Architecture Rules Roadmap (#662)

Issue #662 expands the curated architecture-rule library from 25 rules to 40+
rules while keeping the engine YAML-driven and backward compatible.

## Current Status

| Metric | Value |
| --- | ---: |
| Current curated rules | 42 |
| Target curated rules | 40+ |
| Rules needed for target | 0 |
| Current rule source | `backend/data/architecture_rules.yaml` |
| Engine entry point | `architecture_rules.evaluate()` |
| Test entry point | `backend/tests/test_architecture_rules.py` |

## Phase Plan

| Phase | Status | Scope | Exit Criteria |
| --- | --- | --- | --- |
| Phase 1 | Complete | Authoring guide and roadmap tracker. | `README.md` and this roadmap exist under `backend/architecture_rules/`. |
| Phase 2 | Complete | First 5 additive rules: disaster recovery, edge security, identity, backup posture, tagging policy. | Rules, predicates if needed, and positive/negative tests merged. |
| Phase 3 | Complete | Next 12 additive rules: Private Link, secrets management, observability anchor/overlap, regulated workload hints, multi-domain validation, tenancy detector, DLQ/checkpointing, API rate limiting, zone posture, and premium edge cost. | Rules and positive/negative tests merged. |
| Phase 4 | Planned | Additional backlog rules selected from production learnings or CTO gap candidates. | Library stays above 40 curated rules while reducing noisy or overlapping findings. |

## Candidate Rule Backlog

| Candidate | Category | Likely Severity | Predicate Strategy | Status |
| --- | --- | --- | --- | --- |
| Cross-region replication missing for stateful workloads | resilience | warning | `service_keywords_without_companion`. | Complete |
| Edge service without WAF or DDoS posture | security | warning | `service_keywords_without_companion`. | Complete |
| Identity layer missing for user-facing app | identity-auth | warning | `service_keywords_without_companion`. | Complete |
| Backup posture missing for database/storage | resilience | warning | `service_keywords_without_companion`. | Complete |
| Required tags not represented in governance design | governance | info | `service_keywords_without_companion` with multi-service threshold. | Complete |
| Database or storage public path without Private Link | network-topology | warning | `service_keywords_without_companion`. | Complete |
| Secrets without Key Vault or managed secret store | identity-auth | warning | `service_keywords_without_companion`. | Complete |
| Duplicate observability stacks or no observability anchor | operations | info/warning | Existing service predicates. | Complete |
| Regulated workload without compliance boundary | governance | warning | `service_keywords_without_companion`. | Complete |
| Multi-domain architecture without clear boundary services | network-topology | info | `service_keywords_without_companion`. | Complete |
| Multi-tenant signals without tenant isolation | identity-auth | warning | `service_keywords_without_companion`. | Complete |
| Queue or eventing without dead-letter path | data-plane | warning | `service_keywords_without_companion`. | Complete |
| Internet-facing app without rate limiting | security | warning | `service_keywords_without_companion`. | Complete |
| Stateful workload without zone or region posture | resilience | warning | `service_keywords_without_companion`. | Complete |
| Cost-sensitive design using premium edge services everywhere | cost | info | `services_all_present`. | Complete |

## Progress Log

| Date | Change | Rule Count |
| --- | --- | ---: |
| 2026-05-06 | Phase 1 scaffold: authoring guide and roadmap tracker. | 25 |
| 2026-05-06 | Phase 2 first rule pack: DR, edge security, identity, backup, and tagging posture. | 30 |
| 2026-05-06 | Phase 3 rule pack: Private Link, secrets, observability, compliance, tenancy, eventing, API, zone, and edge-cost posture. | 42 |

## Validation Gates

Before closing #662:

- `backend/data/architecture_rules.yaml` contains at least 40 unique rule IDs.
- Every new predicate is registered and covered by unit tests.
- Every new rule has positive and negative fixture coverage.
- `./.venv/bin/python -m pytest tests/test_architecture_rules.py tests/test_iac_blocker_gate.py -q` passes from `backend/`.
- `docs/ARCHITECTURE_RULES.md` and `README.md` counts are updated if the public rule count changes.
