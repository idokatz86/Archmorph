"""Source-cloud provider contract helpers."""

from __future__ import annotations

from typing import Final


SUPPORTED_SOURCE_PROVIDERS: Final[frozenset[str]] = frozenset({"aws", "gcp"})


def normalize_source_provider(value: object, *, default: str = "aws") -> str:
    """Return a canonical source provider or raise ``ValueError``.

    Contract:
      * ``None`` means the caller omitted the field and falls back to ``default``.
      * Strings are stripped and lowercased.
      * Empty strings, non-strings, and unsupported values are rejected.
    """
    if value is None:
        value = default

    if not isinstance(value, str):
        raise ValueError(
            f"Unsupported source_provider: {value!r}. "
            f"Expected a string in {sorted(SUPPORTED_SOURCE_PROVIDERS)}."
        )

    provider = value.strip().lower()
    if not provider or provider not in SUPPORTED_SOURCE_PROVIDERS:
        raise ValueError(
            f"Unsupported source_provider: {value!r}. "
            f"Expected one of {sorted(SUPPORTED_SOURCE_PROVIDERS)}."
        )

    return provider