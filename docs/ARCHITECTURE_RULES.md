# Architecture Limitations Engine

> Status: Phase 1 (curated rules + IaC blocker gate) — [#610](https://github.com/idokatz86/Archmorph/issues/610)

## Why this exists

Archmorph turns natural-language descriptions and screenshots into Azure architectures, then generates IaC. Without guardrails the LLM happily produces compositions that look reasonable on paper but cannot work in Azure. The motivating example: an SFTP client connecting to Azure Storage's SFTP endpoint **through Azure Front Door**. Front Door is an HTTP/HTTPS Layer-7 reverse proxy — it does not speak SSH. The architecture diagram looks fine; the generated Terraform will deploy cleanly; the runtime traffic will never connect.

The architecture limitations engine catches these cases deterministically before IaC generation, with curated rules grounded in Microsoft Learn documentation.

## How it works

```
analysis_result (services + connections + mappings)
    ↓
architecture_rules.evaluate()
    ↓
for each rule: run predicate(analysis, **predicate_args)
    ↓
collect ArchitectureIssue list (sorted by severity desc)
    ↓
attach to analysis as `architecture_issues[]` + summary
    ↓
on POST /generate: if any severity == "blocker" → 409 unless ?force=true
```

## Components

| File | Purpose |
| --- | --- |
| [backend/architecture_rules/models.py](../backend/architecture_rules/models.py) | `Severity`, `Rule`, `ArchitectureIssue` dataclasses. |
| [backend/architecture_rules/predicates.py](../backend/architecture_rules/predicates.py) | 8 reusable predicates + decorator-based registry. |
| [backend/architecture_rules/engine.py](../backend/architecture_rules/engine.py) | YAML loader, schema validation, lazy thread-safe singleton, `evaluate()`. |
| [backend/data/architecture_rules.yaml](../backend/data/architecture_rules.yaml) | 25 curated rules. |
| [backend/routers/diagrams.py](../backend/routers/diagrams.py) | Wires `evaluate()` into the analysis enrichment pipeline. |
| [backend/routers/iac_routes.py](../backend/routers/iac_routes.py) | 409 gate on blockers; `?force=true` override. |
| [backend/tests/test_architecture_rules.py](../backend/tests/test_architecture_rules.py) | Engine + golden scenario tests. |
| [backend/tests/test_iac_blocker_gate.py](../backend/tests/test_iac_blocker_gate.py) | IaC gate behaviour tests. |

## Rule schema

```yaml
- id: front-door-sftp-storage-blocker          # unique, kebab-case
  title: Front Door cannot proxy SFTP to Azure Storage
  severity: blocker                              # blocker | warning | info
  category: protocol                             # for grouping in UI
  message: >
    Azure Front Door is HTTP/HTTPS-only and cannot tunnel SSH/SFTP traffic.
  remediation: >
    Connect SFTP clients directly to the storage account's SFTP endpoint,
    or front it with an Azure Load Balancer / NVA that forwards TCP port 22.
  docs_url: https://learn.microsoft.com/azure/frontdoor/front-door-overview
  predicate: path_uses_service_with_protocol_mismatch
  predicate_args:
    via: Azure Front Door
    allowed_protocols: [http, https]
    disallowed_hint: [sftp, ssh]
  references:
    - https://learn.microsoft.com/azure/storage/blobs/secure-file-transfer-protocol-support
  tags: [front-door, sftp, storage]
```

## Severity semantics

| Severity | Meaning | Behaviour |
| --- | --- | --- |
| `blocker` | The composition cannot work as drawn. Generated IaC will deploy but runtime traffic will fail. | `POST /generate` → 409 unless `?force=true`. |
| `warning` | Works in some configurations but has a known gap (non-transitive peering, region-feature mismatch, ungoverned dead-lettering). | Surfaced in UI, does not block IaC. |
| `info` | Best-practice nudge or tier prerequisite reminder (storage SFTP requires hierarchical namespace, Cosmos free tier is one-per-subscription, etc.). | Surfaced in UI for awareness. |

## Adding a rule

1. Pick or write a predicate in [predicates.py](../backend/architecture_rules/predicates.py). Reuse existing ones where possible — most architecture limits boil down to "service present", "service pair connected", or "path via X uses protocol Y".
2. Add a YAML entry in [architecture_rules.yaml](../backend/data/architecture_rules.yaml).
3. Add a golden test in [test_architecture_rules.py](../backend/tests/test_architecture_rules.py) that exercises a positive **and** a negative case (over-firing on sane architectures is a worse failure mode than under-firing).
4. Confirm `python -m pytest tests/test_architecture_rules.py` passes.

## Override path

`ARCHMORPH_ARCH_RULES_PATH=/path/to/custom.yaml` replaces the default rule set entirely (used in tests and to A/B different rule libraries in dev).

## Phase roadmap

| Phase | Scope |
| --- | --- |
| 1 (this PR) | Curated YAML rules + Python predicates + IaC blocker gate. |
| 2 | GPT-4o fallback when no curated rule fires — review queue for human approval. |
| 3 | Admin UI to approve / reject AI-suggested rules into the curated library. |
| 4 | Frontend "Architecture Health" panel surfacing blockers/warnings/info inline. |
| 5 | Backfill curated library from 25 to 60-100 rules across the long tail. |
