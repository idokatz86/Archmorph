# Azure Landing Zone — `source_provider` analyzer contract

> Status: **Implemented** (epic #576, extends #571)

## What this is

The Azure Landing Zone target diagram (shipped in #571) renders a region-aware
SVG that maps an existing cloud workload onto an Azure landing zone. Most of
the diagram is target-side (Azure regions, tiers, replication, icons, palette)
and is fully provider-agnostic. The **only** part that varies per source
provider is the legend's mapping line in the bottom-right.

This document describes the analyzer-side contract that selects which mapping
line is rendered.

## The field

Set `source_provider` on the analysis dict:

```python
analysis = {
    # ... regions, tiers, mappings, etc.
    "source_provider": "gcp",   # or "aws"; default "aws" if absent
}
```

| Value      | Behaviour                                                       |
| ---------- | --------------------------------------------------------------- |
| `"aws"`    | Render the AWS→Azure mapping line (default).                    |
| `"gcp"`    | Render the GCP→Azure mapping line.                              |
| missing    | Treated as `"aws"` (backwards-compatible with #571).             |
| `"GCP"`, `"AWS"` (any case) | Lowercased before lookup.                       |
| anything else | `ValueError` raised by the generator → HTTP 400 from the route. |

## What gets rendered

### `source_provider="aws"` (default)
```
Mapping: AWS → Azure · ALB → App Gateway · EKS → AKS · EFS → Azure Files · Kafka → Event Hubs · RDS → Managed DB
```

### `source_provider="gcp"`
```
Mapping: GCP → Azure · GLB → App Gateway · GKE → AKS · Filestore → Azure Files · Pub/Sub → Event Hubs · Cloud SQL → Managed DB
```

## Why implicit (not a query param)

- The analyzer pipeline already knows the source provider — making the route
  re-state it would be duplication and a divergence risk.
- The frontend stays untouched. Frontend wiring is deferred (mirrors how
  #575 was deferred for #571).
- Symmetric with how `multi_page` and `dr_variant` were originally scoped:
  query params are reserved for *renderer-side* preferences, not for facts
  about the source workload.

## Source of truth

- The shared contract helper lives in [`backend/source_provider.py`](../backend/source_provider.py):
  - `SUPPORTED_SOURCE_PROVIDERS: frozenset[str]` — allowed values.
  - `normalize_source_provider(value) -> str` — lowercases, defaults, raises.
- Landing-zone legend constants live in [`backend/azure_landing_zone.py`](../backend/azure_landing_zone.py):
  - `_SOURCE_PROVIDER_LEGEND_LINE: dict[str, str]` — verbatim mapping line per
    provider.
- A module-load `assert` keeps `_SUPPORTED_SOURCE_PROVIDERS` and
  `_SOURCE_PROVIDER_LEGEND_LINE` in lockstep.

## Adding another provider

1. Add the new key to `_SOURCE_PROVIDER_LEGEND_LINE` with the verbatim mapping
   line.
2. Add the same key to `_SUPPORTED_SOURCE_PROVIDERS` (the lockstep assert will
   fail at import time if you forget).
3. Add a `TestXxxSource` class in `backend/tests/test_azure_landing_zone.py`
   covering: legend contains the new mapping line; legend does not contain
   other providers' lines; primary + DR variants both render; case-insensitive
   acceptance.
4. Update this document.

No router, frontend, schema, icon-registry, or replication-template changes
are required.

## References

- Parent epic: [#571](https://github.com/idokatz86/Archmorph/issues/571)
- This epic: [#576](https://github.com/idokatz86/Archmorph/issues/576)
- Sub-issues: [#577](https://github.com/idokatz86/Archmorph/issues/577) (generator), [#578](https://github.com/idokatz86/Archmorph/issues/578) (tests), [#579](https://github.com/idokatz86/Archmorph/issues/579) (validation + this doc)
