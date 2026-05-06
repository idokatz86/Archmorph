# Architecture Rule Authoring Guide

This package owns the deterministic architecture-limitations engine. Rules are
YAML entries in `backend/data/architecture_rules.yaml`; predicates are Python
helpers registered in `predicates.py`; `engine.py` loads and evaluates the
library against a `vision_analyzer` analysis result.

The current library has 42 curated rules. Issue #662 expands it past the 40+
rule target without changing the public API or moving rules out of YAML.

## Rule Schema

Every rule entry must include these fields:

```yaml
- id: private-link-missing-for-database
  title: Database is public without Private Link
  severity: warning
  category: network-topology
  message: |
    Explain the architecture risk in customer-facing language.
  remediation: |
    Explain the Azure-native fix or tradeoff.
  docs_url: https://learn.microsoft.com/azure/private-link/private-link-overview
  predicate: services_all_present
  predicate_args:
    names:
      - Azure SQL
      - Public endpoint
  tags: [networking, private-link, database]
```

Field guidance:

| Field | Guidance |
| --- | --- |
| `id` | Stable kebab-case identifier. Tests and UI may depend on it. |
| `title` | Short user-visible headline. |
| `severity` | `blocker`, `warning`, or `info`. |
| `category` | Grouping key for UI and reports, such as `protocol`, `network-topology`, `identity-auth`, `data-plane`, `region`, `tier-feature`, `resilience`, `security`, or `governance`. |
| `message` | Why the design is risky or invalid. Keep it actionable. |
| `remediation` | Azure-native next steps, including alternatives when there is no single fix. |
| `docs_url` | Official Microsoft Learn URL wherever possible. |
| `predicate` | Name registered with `@register_predicate` in `predicates.py`. |
| `predicate_args` | Keyword args passed directly to the predicate. |
| `references` | Optional extra links. |
| `tags` | Optional labels for backlog, tests, and filtering. |

Severity guidance:

| Severity | Use When | Runtime Behavior |
| --- | --- | --- |
| `blocker` | Generated IaC would be non-functional or materially wrong. | IaC generation is blocked unless forced. |
| `warning` | Design can work, but has a reliability, security, cost, or migration gap. | Surfaced to users; IaC is allowed. |
| `info` | Best-practice nudge or SKU/tier awareness. | Surfaced as advisory context. |

## Predicate Catalog

Existing predicates cover most additive rules:

| Predicate | Fires When |
| --- | --- |
| `service_present` | A fuzzy service-name match exists. |
| `services_all_present` | Every requested service name is present. |
| `service_pair_connected` | A connection links two named services. |
| `connection_uses_protocol` | Any connection type contains a requested protocol token. |
| `service_count_at_least` | At least N services match one of the supplied keywords. |
| `service_keywords_without_companion` | One or more service keywords appear without companion controls; supports `exclude_keywords` plus `companion_mode: any` or `coverage`. |
| `category_present_without_companion` | A category appears without any required companion service. |
| `service_in_category_with_other` | A category coexists with another named service. |
| `path_uses_service_with_protocol_mismatch` | Traffic through a service uses an unsupported protocol. |

When adding a predicate, keep it composable and tolerant of noisy model output:

1. Accept `analysis: dict` plus keyword-only args.
2. Return `None` when the evidence is absent or ambiguous.
3. Return `PredicateMatch(affected_services=[...], evidence={...})` when it fires.
4. Use `_service_matches`, `_has_service`, `_services_in_analysis`, and `_connections` instead of strict string equality.
5. Avoid external calls, non-determinism, and side effects.

## Test Pattern

Each rule must have at least one positive and one negative assertion. Prefer a
small fixture in `backend/tests/test_architecture_rules.py` unless the case needs
a shared JSON fixture.

Positive test shape:

```python
def test_private_link_rule_fires(public_database_analysis):
    issues = evaluate(public_database_analysis)
    assert "private-link-missing-for-database" in {issue.rule_id for issue in issues}
```

Negative test shape:

```python
def test_private_link_rule_does_not_fire_when_private_link_present(private_database_analysis):
    issues = evaluate(private_database_analysis)
    assert "private-link-missing-for-database" not in {issue.rule_id for issue in issues}
```

Run the focused suite before opening a PR:

```sh
cd backend
./.venv/bin/python -m pytest tests/test_architecture_rules.py tests/test_iac_blocker_gate.py -q
```

## Contributor Checklist

1. Confirm the new rule is not already represented in `architecture_rules.yaml`.
2. Use an existing predicate when possible.
3. Add a reusable predicate only when at least two rules can plausibly share it.
4. Keep `message` and `remediation` customer-readable.
5. Link to official Microsoft Learn docs.
6. Add positive and negative tests.
7. Run the focused architecture-rules tests.
8. Update `rules-roadmap.md` when the total rule count or #662 phase status changes.
