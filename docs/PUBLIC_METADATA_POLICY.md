# Public Metadata Policy

Archmorph keeps deployment inventory outside the public source tree. This policy covers documentation, examples, runtime defaults, workflows, generated evidence, and one-off operator scripts.

## Canonical release metadata

- [VERSION](../VERSION) is the only editable product-version source.
- Run `python3 scripts/sync_version.py --write` after changing it.
- CI runs `python3 scripts/sync_version.py --check` and rejects drift in backend, frontend, npm, badge, PRD, OpenAPI, diagram, or changelog signals.
- The code version does not imply that every Beta capability is GA or that a GitHub Release exists. Capability maturity and release evidence remain separate claims.

## Public examples

Use role-based placeholders such as:

- `<resource-group>`
- `<storage-account>`
- `<container-app>`
- `<frontend-host>`
- `https://frontend.example.com`
- `00000000-0000-0000-0000-000000000000`

Do not publish generated Azure hostnames, live resource names, subscription or tenant IDs, private endpoint inventory, local workstation paths, or production topology history.

## Private operator state

Store current inventory in GitHub environment secrets/variables, an approved secret manager, Terraform state, or private operator notes. The repository intentionally ignores `.operator-private/` for temporary local evidence. Never copy that directory into a pull request or workflow artifact.

Terraform uses partial backend configuration. Supply its resource group, storage account, container, and environment-specific state key through private CI/operator configuration at initialization time. Production and staging keys must be distinct.

## Domain allowlist

Intentional customer-facing domains are listed in [config/public-metadata-allowlist.json](../config/public-metadata-allowlist.json), with a review date and rationale. That allowlist is not permission to add a domain to a runtime CORS default: production and staging CORS origins must always come from `ALLOWED_ORIGINS` deployment configuration.

## Validation

Run both checks before opening a pull request:

```text
python3 scripts/sync_version.py --check
python3 scripts/lint_public_metadata.py
```

The metadata lint reports only file, line, category, and remediation guidance; it does not echo matched identifiers into CI logs.
