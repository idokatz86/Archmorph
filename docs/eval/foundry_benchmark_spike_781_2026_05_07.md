# Foundry Benchmark Spike #781 — May 7, 2026

> Issue: [#781](https://github.com/idokatz86/Archmorph/issues/781)  
> Status: Spike recommendation, no production routing change  
> Machine-readable plan: [data/foundry_benchmark_plan_781_2026_05_07.json](data/foundry_benchmark_plan_781_2026_05_07.json)

## Decision Summary

Keep the current Azure OpenAI baseline for production: `gpt-4.1` primary with `gpt-4o` fallback on the West Europe account `archmorph-openai-we-acm7pd`.

Add benchmark candidates only for the low-risk or specialist lanes where live evidence may justify a later feature-flagged route. Do not create, update, or route production deployments until the live benchmark proves quality or cost improvement without breaking structured output, export artifacts, quota headroom, safety behavior, or SLA gates.

## Current Baseline

Read-only Azure inventory on May 7, 2026 confirmed:

| Field | Value |
| --- | --- |
| Subscription | `152f2bd5-8f6b-48ba-a702-21a23172a224` |
| Tenant | `16b3c013-d300-468d-ac64-7eda0820b6d3` |
| Resource group | `archmorph-rg-dev` |
| Account | `archmorph-openai-we-acm7pd` |
| Region | West Europe (`westeurope`) |
| Primary deployment | `gpt-4.1`, model version `2025-04-14`, `GlobalStandard`, capacity `10` |
| Fallback deployment | `gpt-4o`, model version `2024-11-20`, `GlobalStandard`, capacity `10` |
| RAI policy | `Microsoft.DefaultV2` on both deployments |

Terraform already matches the desired auth posture: local auth is disabled on the OpenAI account, the Container App receives `AZURE_OPENAI_DEPLOYMENT=gpt-4.1` and `AZURE_OPENAI_FALLBACK_DEPLOYMENT=gpt-4o`, and both user-assigned and system-assigned identities hold `Cognitive Services OpenAI User` on the account.

## Regional Availability

| Region | Evidence | Candidate posture |
| --- | --- | --- |
| West Europe | `az cognitiveservices account list-models` on `archmorph-openai-we-acm7pd` exposed current `gpt-4.1`/`gpt-4o` plus deployable `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-4.1-nano`, `o4-mini`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5-codex`, `gpt-5-pro`, `gpt-5.3-codex`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, and `gpt-5.5`. | Eligible for benchmark candidates. `gpt-5.5` is `GlobalProvisionedManaged`, so it is capacity-gated and should not be treated as a default route candidate. |
| Sweden Central | Subscription inventory found an `AIServices` account, `agentsecysbz`, in `rg-agent-security-foundry-sc`. The model-list query hung and was interrupted. | Treat as pending validation for #783 migration planning. No Archmorph routing until model list, quota, RBAC, and rollback drills are captured cleanly. |

Quota usage discovery for West Europe returned no rows in this CLI environment. That is not evidence of quota headroom; the live benchmark must capture TPM/RPM, 429s, retry behavior, and p95 latency before any routed deployment is proposed.

## Benchmark Lanes

The benchmark plan covers seven Archmorph workload lanes, exceeding the issue requirement of at least five:

| Lane | Current baseline | Candidates | Dataset and gates |
| --- | --- | --- | --- |
| Diagram/image understanding | `gpt-4.1`, `gpt-4o` | `gpt-5.4`, `gpt-5.5` | Synthetic diagrams plus the legal-approved golden PDF corpus when available. Gate on service inventory F1, relationship edge F1, JSON schema validity, image/PDF refusal rate. |
| Cloud service mapping suggestions | `gpt-4.1`, `gpt-4o` | `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-5.4-mini` | AWS/GCP/on-prem mapping prompts. Gate on primary mapping accuracy, confidence calibration, rationale safety, JSON schema validity. |
| IaC generation and repair | `gpt-4.1`, `gpt-4o` | `gpt-5.3-codex`, `gpt-5-codex`, `gpt-5.4` | Terraform/Bicep generation and repair from canonical starters. Gate on `terraform fmt`/validate, Bicep diagnostics, least-privilege defaults, no secret leakage. |
| HLD architecture narrative | `gpt-4.1`, `gpt-4o` | `gpt-5.4`, `gpt-5`, `gpt-5-mini` | HLD prompts with expected sections, risks, service map, and cost context. Gate on section coverage, migration-risk accuracy, concise narrative, policy-safe recommendations. |
| Cost explanation | `gpt-4.1`, `gpt-4o` | `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-5.4-mini` | Retail-price and FinOps trade-off prompts. Gate on numeric consistency, SKU caveat accuracy, unit-cost clarity, and no fabricated prices. |
| Regression judge | `gpt-4o`, `gpt-4.1` | `gpt-5-pro`, `gpt-5.4`, `o4-mini` | Known-pass and known-fail regression answers. Gate on grader agreement, false-pass rate, false-fail rate, stable JSON scores. |
| Chat/refinement assistant | `gpt-4.1`, `gpt-4o` | `gpt-5.4-mini`, `gpt-5-mini`, `o4-mini` | Multi-turn refinement prompts with tool-call expectations and customer constraints. Gate on tool-call accuracy, constraint retention, p95 latency, safe refusal behavior. |

## Recommendation Matrix

| Lane | Candidate | Recommendation | Reason |
| --- | --- | --- | --- |
| Diagram/image understanding | `gpt-5.4` | Defer | Potential quality candidate, but it needs live image/PDF evidence and quota proof before any routed deployment. |
| Cloud service mapping | `gpt-5.4-mini` | Add routed-model candidate | Low-risk structured lane. Benchmark for cost and p95 latency savings before a feature-flag route. |
| IaC generation and repair | `gpt-5.3-codex` | Add routed-model candidate | Specialist candidate. Must pass IaC validation and security gates before canary. |
| HLD architecture narrative | `gpt-5.4` | Defer | Current baseline remains until live report proves better section coverage without verbosity regressions. |
| Cost explanation | `gpt-5.4-mini` | Add routed-model candidate | Candidate for cheaper explanation prompts if numeric consistency and no fabricated pricing hold. |
| Regression judge | `gpt-5-pro` | Defer | Use only as an offline judge candidate until cost and evaluator agreement justify continuous use. |
| Chat/refinement assistant | `gpt-5.4-mini` | Defer | Multi-turn tool use needs stronger evidence on tool-call accuracy and constraint retention. |

## Auth And Safety Requirements

- Use managed identity or local developer Azure credentials for benchmark access.
- Do not add API-key based benchmark routes or committed secret material.
- Keep `local_auth_enabled = false` as the target posture for Archmorph-owned OpenAI resources.
- Require `Cognitive Services OpenAI User` on the benchmark identity.
- Preserve `Microsoft.DefaultV2` or stricter RAI policy on any temporary benchmark deployment.
- Store benchmark artifacts as sanitized JSON/Markdown only: prompt IDs, timings, token counts, rubric scores, errors, and short excerpts. Do not store customer content or raw diagrams outside the approved golden corpus.

## Live Benchmark Procedure

1. Create temporary benchmark deployments only after explicit approval and quota validation.
2. Run the offline plan first: `cd backend && python -m eval.model_bench --plan --output ../docs/eval/data/foundry_benchmark_plan_781_2026_05_07.json`.
3. Run dry-run regression to ensure the harness is healthy: `cd backend && python -m eval.model_bench --dry-run --full --output ../docs/eval/data/model_bench_2026_05.json`.
4. For live tests, run one lane at a time with cache bypass and record prompt/completion tokens, p50/p95 latency, refusal rate, 429/5xx rate, and rubric scores.
5. Compare each candidate against both `gpt-4.1` and `gpt-4o` where the fallback is behaviorally relevant.
6. Reject any candidate that fails structured-output validity, export artifact compatibility, safety behavior, or SLA gates even if it is cheaper.

## Rollback Plan For Any Later Route

This spike does not implement routing. A later routing PR must include:

- Feature flag per workload, defaulting to the current baseline.
- Deployment name metrics with `workload` and `model` dimensions.
- A rollback drill proving traffic returns to `gpt-4.1`/`gpt-4o` within 60 seconds of flag reversal.
- Cache-key verification, already protected by the existing model-sensitive cache key tests.
- Canary stages with alert gates for 429 rate, p95 latency, schema-validity failures, and export failures.

## Open Follow-Ups

- Re-run Sweden Central model and quota discovery in a clean command before #783 migration planning.
- Capture West Europe quota/usage from Azure portal or a non-hanging quota API path because CLI usage returned no rows here.
- Attach the first live benchmark result as a separate dated JSON artifact before any production-route issue is opened.
- Keep the older #602 synthetic report for historical context, but treat this #781 report and plan artifact as the current decision record.
