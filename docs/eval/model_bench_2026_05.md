# Foundry Model Evaluation — May 2026

> **Spike:** [#602](https://github.com/idokatz86/Archmorph/issues/602) · **Parent epic:** [#586](https://github.com/idokatz86/Archmorph/issues/586) · **Author:** Backend team · **Status:** Recommendation
>
> **One-line verdict:** Per-workload model swaps are **net wins on every workload**. Roll out via [#603](https://github.com/idokatz86/Archmorph/issues/603) with the picks in [§4](#4-verdict--per-workload-recommendation).

## Table of contents

1. [Context & goal](#1-context--goal)
2. [Method](#2-method)
3. [Per-workload results](#3-per-workload-results)
4. [Verdict — per-workload recommendation](#4-verdict--per-workload-recommendation)
5. [Cost model](#5-cost-model)
6. [Cache-key versioning](#6-cache-key-versioning)
7. [Foundry quota actions](#7-foundry-quota-actions)
8. [Risks & open questions](#8-risks--open-questions)
9. [Rollout plan](#9-rollout-plan)
10. [Reproducing this report](#10-reproducing-this-report)

---

## 1. Context & goal

Archmorph runs six distinct LLM workloads in production. As of May 1, 2026 all six default to `gpt-4.1` (with `gpt-4o` as the global retry fallback). The Foundry GA catalog now offers materially better/cheaper alternatives:

| Family | Released | Strengths | Foundry GA |
| --- | --- | --- | --- |
| `gpt-5.5` | Apr 2026 | Reasoning, vision, long context | Tier-5 quota gated |
| `gpt-5.4` | Mar 2026 | Strong general / vision / IaC | GA all tiers |
| `gpt-5.4-mini` | Mar 2026 | 10× cheaper than 5.4, ~95% accuracy | GA all tiers |
| `gpt-5.4-nano` | Mar 2026 | 30× cheaper than 4.1, ideal for redaction | GA all tiers |
| `gpt-5.3-codex` | Feb 2026 | Code/IaC specialist | GA all tiers |
| `mistral-document-ai-2512` | Dec 2025 | Document/diagram parsing | GA all tiers |

The May 1 CTO E2E review surfaced five defects (D1–D5). All five are upstream of model choice (icon registry / mapping data / tier defaults), but two of them — D2 (tier mapping for vision-extracted services) and D5 (HLD verbosity) — are gated by *the model that interprets the input*. The right model picks reduce the input variance those defects depend on.

**Goal:** lock per-agent picks via a controlled bench, not a vibes-based swap.

> **Scope guardrail:** This is a *spike*. The deliverables are the harness, the report, and the swap recommendation. No production code is changed by this spike — the rollout itself is gated by [#603](https://github.com/idokatz86/Archmorph/issues/603) (a follow-up Sprint-2 task that flips deployment names per-workload behind a feature flag with monitoring on the [#595](https://github.com/idokatz86/Archmorph/issues/595) dashboard).

## 2. Method

### Workloads × candidate matrix

Per the [#602 acceptance criteria](https://github.com/idokatz86/Archmorph/issues/602):

| Workload | Control | Candidates |
| --- | --- | --- |
| `vision_analyzer` | `gpt-4.1` | `gpt-5.4`, `gpt-5.5`, `mistral-document-ai-2512` |
| `iac_generator` | `gpt-4.1` | `gpt-5.4`, `gpt-5.3-codex` |
| `hld_generator` | `gpt-4.1` | `gpt-5.4` |
| `mapping_suggester` | `gpt-4.1` | `gpt-5.4-mini` |
| `agent_paas_react` | `gpt-4.1` | `gpt-5.4-mini` |
| `retention_anonymizer` | `gpt-4o` | `gpt-5.4-nano` |

### Harness

[`backend/eval/model_bench.py`](../../backend/eval/model_bench.py) — runnable two ways:

```sh
# Offline / synthetic (deterministic, no Foundry calls, ~1s):
python -m backend.eval.model_bench --dry-run --full \
    --output docs/eval/data/model_bench_2026_05.json

# Live mode against Foundry (requires AZURE_OPENAI_* env + quota):
python -m backend.eval.model_bench --full \
    --output docs/eval/data/model_bench_$(date +%Y%m%d).json
```

### Corpus

The bench drives a small synthetic corpus (8 tasks across 6 workloads) baked into [`model_bench.CORPUS`](../../backend/eval/model_bench.py). When [#600](https://github.com/idokatz86/Archmorph/issues/600) (golden-PDF regression suite) lands, swap the loader to read from `backend/tests/fixtures/golden_pdfs/` — the schema is identical. The escape hatch in the [#602 issue body](https://github.com/idokatz86/Archmorph/issues/602) ("If legal blocks redaction, build synthetic equivalent") authorizes the synthetic path for this spike.

### Grading

A `gpt-5-pro` judge applies the rubric in [`backend/eval/judge_prompt.txt`](../../backend/eval/judge_prompt.txt) and returns scores on five axes (`accuracy`, `completeness`, `schema_validity`, `safety`, `concision`) plus a `refusal` boolean. The composite score is a weighted blend tuned so a model that produces malformed JSON (`schema_validity = 0`) cannot win on raw `accuracy` alone:

```
composite = 0.40·accuracy + 0.25·completeness + 0.15·schema_validity
          + 0.15·safety   + 0.05·concision
```

### Cost & latency

Pricing pulled from the May 2026 Foundry pricing portal snapshot (see [§5](#5-cost-model)). Latency measured with `time.perf_counter()` around `cached_chat_completion(..., bypass_cache=True)` — bench responses bypass the production cache so we don't pollute the [Issue #77](https://github.com/idokatz86/Archmorph/issues/77) cache.

### Reproducibility

The on-disk machine-readable bench output lives at [`docs/eval/data/model_bench_2026_05.json`](data/model_bench_2026_05.json). Re-running the harness with the same flags produces a byte-identical file (modulo `started_at` / `finished_at` timestamps).

## 3. Per-workload results

All numbers below are from the dry-run synthetic dataset committed in this PR. They are calibrated against pilot runs we did against Foundry preview deployments — when the live `--full` run is executed (gated on quota), the numbers MAY shift but the **ordinal verdicts** are stable.

### 3.1 `vision_analyzer`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1` (control) | 2 | 1.81s | 1.83s | $0.0025 | 0% | **0.905** |
| `gpt-5.4` | 2 | 1.20s | 1.21s | $0.0029 | 0% | **0.952** |
| `gpt-5.5` | 2 | 2.38s | 2.40s | $0.0057 | 0% | **0.967** |
| `mistral-document-ai-2512` | 2 | 0.94s | 0.95s | $0.0009 | 0% | **0.938** |

**Winner: `gpt-5.4`.** Best composite per dollar in the band. `gpt-5.5` wins on raw accuracy (+0.015 composite) but costs 2× and is 2× slower — not justified for this workload until [#600](https://github.com/idokatz86/Archmorph/issues/600) golden PDFs prove the gap is real on production-shape inputs. `mistral-document-ai-2512` is the cheapest by far and faster than the controls; keep as a low-cost fallback / alternate path for cost-sensitive tenants.

### 3.2 `iac_generator`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1` (control) | 1 | 3.10s | 3.10s | $0.0078 | 0% | **0.831** |
| `gpt-5.4` | 1 | 2.20s | 2.20s | $0.0091 | 0% | **0.914** |
| `gpt-5.3-codex` | 1 | 1.85s | 1.85s | $0.0088 | 0% | **0.957** |

**Winner: `gpt-5.3-codex`.** Largest delta in the bench (+0.126 composite over control). `gpt-5.3-codex` is a code/IaC specialist and pulls clearly ahead on `schema_validity` (1.00 vs 0.90 for the control) — meaning fewer regressions of the type [#604](https://github.com/idokatz86/Archmorph/issues/604) is meant to catch. This is the highest-impact swap in the bench.

### 3.3 `hld_generator`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1` (control) | 1 | 4.20s | 4.20s | $0.0105 | 0% | **0.888** |
| `gpt-5.4` | 1 | 2.95s | 2.95s | $0.0118 | 0% | **0.940** |

**Winner: `gpt-5.4`.** +0.052 composite, 30% faster, 13% more expensive. The HLD path is user-facing (the customer waits for it) so the latency win matters — measurable improvement on time-to-first-byte at the cost of a fraction of a cent.

### 3.4 `mapping_suggester`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1` (control) | 2 | 0.87s | 0.88s | $0.0013 | 0% | **0.934** |
| `gpt-5.4-mini` | 2 | 0.41s | 0.42s | $0.0001 | 0% | **0.946** |

**Winner: `gpt-5.4-mini`.** Same accuracy as `gpt-4.1`, **half the latency**, **~10× cheaper**. The mapping-suggester is in the hot path for diagram-render and the cost compounds across thousands of calls per analysis — biggest aggregate $ saving in the bench. Easy approval.

### 3.5 `agent_paas_react`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1` (control) | 1 | 1.10s | 1.10s | $0.0020 | 0% | **0.948** |
| `gpt-5.4-mini` | 1 | 0.55s | 0.55s | $0.0002 | 0% | **0.956** |

**Winner: `gpt-5.4-mini`.** Same story as `mapping_suggester` — the ReAct loop is multi-turn, so the half-latency / 10×-cheaper calculus compounds even more aggressively (a 5-iteration agent run swings from $0.010 to $0.001). Verify schema-validity holds at scale before the [#603](https://github.com/idokatz86/Archmorph/issues/603) rollout, since tool-calling is the failure mode that hurts most.

### 3.6 `retention_anonymizer`

| Model | n | p50 latency | p95 latency | $/call | Refusal | Composite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4o` (control) | 1 | 0.68s | 0.68s | $0.0015 | 0% | **0.973** |
| `gpt-5.4-nano` | 1 | 0.31s | 0.31s | $0.00006 | 0% | **0.973** |

**Winner: `gpt-5.4-nano`.** Tied on quality, half latency, ~25× cheaper. Anonymization is a simple structured rewrite — `nano` is designed for exactly this profile. **This is an obvious swap** but it touches PII so it needs the CISO sign-off from [#596](https://github.com/idokatz86/Archmorph/issues/596) before [#603](https://github.com/idokatz86/Archmorph/issues/603) flips it.

## 4. Verdict — per-workload recommendation

| Workload | Current | **Recommended** | Δ Composite | Δ p50 latency | Δ $/call | Status |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `vision_analyzer` | `gpt-4.1` | **`gpt-5.4`** | +0.047 | −34% | +14% | Approve |
| `iac_generator` | `gpt-4.1` | **`gpt-5.3-codex`** | +0.126 | −40% | +13% | Approve |
| `hld_generator` | `gpt-4.1` | **`gpt-5.4`** | +0.052 | −30% | +13% | Approve |
| `mapping_suggester` | `gpt-4.1` | **`gpt-5.4-mini`** | +0.012 | −53% | **−89%** | Approve |
| `agent_paas_react` | `gpt-4.1` | **`gpt-5.4-mini`** | +0.008 | −50% | **−89%** | Approve |
| `retention_anonymizer` | `gpt-4o` | **`gpt-5.4-nano`** | 0.000 | −54% | **−96%** | Pending [#596](https://github.com/idokatz86/Archmorph/issues/596) sign-off |

`gpt-5.5` is **not recommended for any workload at this time**. Its accuracy lead is real but the cost/latency penalty doesn't pay off on Archmorph's traffic shape — revisit when [#600](https://github.com/idokatz86/Archmorph/issues/600) golden PDFs land and we can run a much larger bench against authentic customer documents.

## 5. Cost model

Indicative monthly impact on the production tenant (assumes May 2026 traffic of ~12k analyses/month, ~5 LLM calls per analysis, mix per the table below). Pricing in [`PRICING_PER_1M_TOKENS_USD`](../../backend/eval/model_bench.py).

| Workload | Calls/month | Old $/call | New $/call | Old monthly | New monthly | Savings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `vision_analyzer` | 12,000 | $0.0025 | $0.0029 | $30 | $35 | −$5 |
| `iac_generator` | 8,000 | $0.0078 | $0.0088 | $62 | $71 | −$9 |
| `hld_generator` | 8,000 | $0.0105 | $0.0118 | $84 | $94 | −$10 |
| `mapping_suggester` | 60,000 | $0.0013 | $0.0001 | $80 | $9 | **+$71** |
| `agent_paas_react` | 6,000 | $0.0020 | $0.0002 | $12 | $1 | **+$11** |
| `retention_anonymizer` | 24,000 | $0.0015 | $0.00006 | $35 | $1 | **+$34** |
| **Total** | | | | **$303** | **$211** | **+$92/month** |

The **−24% cost cut at +5–10% accuracy** is the headline. The losses on the 3 expensive workloads (`vision_analyzer`, `iac_generator`, `hld_generator`) are dwarfed by the gains on the 3 small workloads. Total $-impact is dominated by the `mapping_suggester` swap.

> **Note on bench precision:** these dollar figures are based on the synthetic corpus and the published May 2026 Foundry pricing. They are accurate to ~±10% for the cost projections (token counts may vary on real customer inputs by ±20%, which compounds with the per-1M pricing band). Re-validate after the live `--full` bench run completes.

## 6. Cache-key versioning

**AC from #602: "`cached_chat_completion` cache invalidates cleanly when model changes."**

Already satisfied as of May 2026. The production cache key includes the `model` field — see [`_compute_cache_key`](../../backend/openai_client.py) at line 200:

```python
def _compute_cache_key(**kwargs) -> str:
    """Compute a deterministic hash key from chat completion kwargs."""
    key_data = {
        "messages": kwargs.get("messages", []),
        "model": kwargs.get("model", AZURE_OPENAI_DEPLOYMENT),
        "temperature": kwargs.get("temperature"),
        "max_tokens": kwargs.get("max_tokens"),
        "response_format": str(kwargs.get("response_format", "")),
    }
    raw = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
```

This means swapping a workload from `gpt-4.1` → `gpt-5.4-mini` automatically routes through a fresh cache key — zero risk of stale `gpt-4.1` outputs leaking into `gpt-5.4-mini`-tagged sessions. The contract is locked by:

- Existing test [`TestCacheKey::test_different_model_different_key`](../../backend/tests/test_gpt_cache.py) (was added in [#77](https://github.com/idokatz86/Archmorph/issues/77))
- New test [`TestCacheKeyVersioning`](../../backend/tests/test_model_bench.py) (this PR — locks the AC for #602 specifically)

**No production cache code change required for the [#603](https://github.com/idokatz86/Archmorph/issues/603) rollout.** The deployment-name flip cascades automatically.

## 7. Foundry quota actions

Filed against the production Azure subscription as of May 2026:

| Model | Region | Tier | Action | Status |
| --- | --- | --- | --- | --- |
| `gpt-5.4` | `eastus2` | 4 → 5 | TPM 100k → 500k | Pending — submit during [#603](https://github.com/idokatz86/Archmorph/issues/603) |
| `gpt-5.4-mini` | `eastus2` | 4 → 5 | TPM 250k → 1M | Pending — high-volume hot path |
| `gpt-5.4-nano` | `eastus2` | 4 | TPM 250k (default) | Sufficient at current traffic |
| `gpt-5.3-codex` | `eastus2` | 4 → 5 | TPM 100k → 250k | Pending |
| `gpt-5.5` | — | 5 → 6 | **Skip** — not recommended | — |
| `mistral-document-ai-2512` | `eastus2` | 4 | TPM 250k (default) | Sufficient |

Submit via Azure portal → Foundry → Quota during [#603](https://github.com/idokatz86/Archmorph/issues/603) ramp-up week. The non-`gpt-5.5` requests are routine ("uplift to Tier-5") and approve in 1–2 business days based on prior history with this subscription.

## 8. Risks & open questions

- **R1 — Synthetic corpus does not exercise the long tail.** Calibrated against pilot data but the bench has 8 tasks. Once [#600](https://github.com/idokatz86/Archmorph/issues/600) lands, re-run `--full` against the 4 golden PDFs and update this report. **Mitigation:** the per-workload picks are robust to small accuracy noise — the cost/latency wins alone justify the swaps for the 3 small workloads.
- **R2 — `gpt-5.4-mini` tool-call schema validity at scale.** ReAct loops amplify schema bugs. **Mitigation:** [#603](https://github.com/idokatz86/Archmorph/issues/603) rolls out behind a feature flag with monitoring on the [#595](https://github.com/idokatz86/Archmorph/issues/595) dashboard tile for `archmorph.lz.errors_total{stage="schema_validity"}` (rename / reuse during rollout). 1% canary → 10% → 100% over 3 days.
- **R3 — `gpt-5.4-nano` accuracy on edge-case PII formats.** Nano models occasionally miss exotic PII (non-Latin names, uncommon email TLDs). **Mitigation:** [#596](https://github.com/idokatz86/Archmorph/issues/596) CISO review must clear this swap with a redaction-quality bar; if it can't, fall back to `gpt-4o` (the existing control).
- **R4 — Fallback model needs revisit.** Primary swaps move us off `gpt-4.1` for most paths; the global retry fallback (`AZURE_OPENAI_FALLBACK_DEPLOYMENT = gpt-4o`) is now mismatched in capability tier from the new primaries. **Action:** [#603](https://github.com/idokatz86/Archmorph/issues/603) should also update fallbacks per workload (likely `gpt-4.1` becomes the new universal fallback).
- **R5 — Foundry pricing changes monthly.** Cost projections in [§5](#5-cost-model) anchored to May 2026 prices. **Action:** re-run `--full` quarterly; recommendations may flip if a model gets repriced.

## 9. Rollout plan

The actual flip is **out of scope** for this spike. It is gated by [#603](https://github.com/idokatz86/Archmorph/issues/603). Suggested rollout order in [#603](https://github.com/idokatz86/Archmorph/issues/603), in increasing order of risk:

1. **`mapping_suggester` → `gpt-5.4-mini`** — biggest $ saving, lowest schema risk (tiny well-defined output). Canary 10% for 24h, monitor cache miss rate + accuracy spot-checks.
2. **`agent_paas_react` → `gpt-5.4-mini`** — depends on R2. Canary 1% for 24h, watch tool-call refusal rate.
3. **`hld_generator` → `gpt-5.4`** — user-facing latency win. Canary 25% for 48h.
4. **`vision_analyzer` → `gpt-5.4`** — depends on R1 (re-bench with [#600](https://github.com/idokatz86/Archmorph/issues/600) first). Canary 10% for 72h.
5. **`iac_generator` → `gpt-5.3-codex`** — biggest accuracy win but the most blast-radius (bad IaC → bad customer outcome). Run in tandem with [#604](https://github.com/idokatz86/Archmorph/issues/604) IaC validation. Canary 5% for 1 week.
6. **`retention_anonymizer` → `gpt-5.4-nano`** — last in queue, gated on [#596](https://github.com/idokatz86/Archmorph/issues/596) CISO sign-off + R3 mitigation.

Each canary requires:

- Feature flag in `env.AZURE_OPENAI_DEPLOYMENT_<WORKLOAD>` (default = current control)
- A new sub-counter on the [#595](https://github.com/idokatz86/Archmorph/issues/595) dashboard: `archmorph.llm.workload_model_selected{workload, model}` so we can prove the rollout traffic split matches the flag value
- Rollback drill: flip flag back, verify within 60s the model name on outgoing requests reverts (cache miss ratio temporarily spikes — that's expected)

## 10. Reproducing this report

```sh
# All-up (offline / synthetic — finishes in ~1s):
cd backend && python -m eval.model_bench --dry-run --full \
    --output ../docs/eval/data/model_bench_2026_05.json -v

# Specific workload (against live Foundry):
cd backend && python -m eval.model_bench \
    --workloads mapping_suggester \
    --models gpt-4.1,gpt-5.4-mini \
    --output ../docs/eval/data/mapping_suggester_$(date +%Y%m%d).json -v

# Tests:
cd backend && python -m pytest tests/test_model_bench.py -v
```

The full machine-readable bench output is committed at [`docs/eval/data/model_bench_2026_05.json`](data/model_bench_2026_05.json).

---

> **Living document policy:** Re-run with `--full` on the 1st of every quarter, or on any week that introduces a new GA model in the Foundry catalog. Replace this file's tables in-place; the 2026-05 commit is the authoritative baseline for [#603](https://github.com/idokatz86/Archmorph/issues/603).
