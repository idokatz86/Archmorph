"""Model evaluation harness package (#602).

Houses the bench infrastructure for the Foundry model evaluation spike:
controlled comparisons of `gpt-5.4`/`gpt-5.5`/`gpt-5.3-codex`/`gpt-5.4-mini`/
`gpt-5.4-nano`/`mistral-document-ai-2512` against the `gpt-4.1`/`gpt-4o`
production controls across the six Archmorph workloads.

This package is intentionally separated from the production code path —
nothing here is imported by `app.py` or any router. Importing this package
must NOT trigger any network calls or cost.
"""
