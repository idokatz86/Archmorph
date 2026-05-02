import pytest

from network_translator import translate_network_topology
from source_provider import SUPPORTED_SOURCE_PROVIDERS, normalize_source_provider


class TestNormalizeSourceProvider:
    def test_supported_values_are_exactly_aws_and_gcp(self):
        assert SUPPORTED_SOURCE_PROVIDERS == frozenset({"aws", "gcp"})

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, "aws"),
            ("aws", "aws"),
            ("AWS", "aws"),
            (" gCp ", "gcp"),
        ],
    )
    def test_normalizes_supported_values(self, raw, expected):
        assert normalize_source_provider(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "azure", "amazon", "google", "alibaba"])
    def test_rejects_empty_aliases_and_unsupported_values(self, raw):
        with pytest.raises(ValueError, match="Unsupported source_provider"):
            normalize_source_provider(raw)

    @pytest.mark.parametrize("raw", [123, True, ["aws"], {"provider": "aws"}])
    def test_rejects_non_strings(self, raw):
        with pytest.raises(ValueError, match="Expected a string"):
            normalize_source_provider(raw)

    def test_network_translator_rejects_azure_as_source_provider(self):
        with pytest.raises(ValueError, match="Unsupported source_provider"):
            translate_network_topology({"source_provider": "azure"})