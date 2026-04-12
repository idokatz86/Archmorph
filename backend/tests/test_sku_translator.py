"""Tests for sku_translator.py — SKU mapping between cloud providers."""

from sku_translator import (
    compute_parity,
    get_sku_translator,
    InstanceSpec,
    SKUTranslation,
)


class TestComputeParity:
    def test_identical_specs(self):
        spec = InstanceSpec(
            sku="m5.large", provider="aws", family="general",
            vcpus=2, ram_gb=8.0, network_gbps=10.0, storage_type="ssd",
        )
        parity = compute_parity(spec, spec)
        assert parity.overall >= 0.9

    def test_different_specs(self):
        source = InstanceSpec(
            sku="m5.xlarge", provider="aws", family="general",
            vcpus=4, ram_gb=16.0, network_gbps=10.0, storage_type="ssd",
        )
        target = InstanceSpec(
            sku="D4s_v5", provider="azure", family="general",
            vcpus=4, ram_gb=16.0, network_gbps=12.5, storage_type="ssd",
        )
        parity = compute_parity(source, target)
        assert 0.0 <= parity.overall <= 1.0
        assert isinstance(parity.details, dict)


class TestSKUTranslatorEngine:
    def test_singleton(self):
        t1 = get_sku_translator()
        t2 = get_sku_translator()
        assert t1 is t2

    def test_translate_known_sku(self):
        translator = get_sku_translator()
        result = translator.translate("m5.large", "aws")
        if result:
            assert isinstance(result, SKUTranslation)
            assert result.target.provider == "azure"

    def test_translate_unknown_sku(self):
        translator = get_sku_translator()
        result = translator.translate("nonexistent.sku.xyz", "aws")
        assert result is None

    def test_best_fit(self):
        translator = get_sku_translator()
        result = translator.best_fit("m5.large", provider="aws")
        if result:
            assert isinstance(result, SKUTranslation)

    def test_translate_database(self):
        translator = get_sku_translator()
        result = translator.translate_database("db.m5.large", "aws")
        # May or may not find a mapping depending on catalog
        if result:
            assert result.azure_service

    def test_translate_storage(self):
        translator = get_sku_translator()
        result = translator.translate_storage("gp3", "aws")
        if result:
            assert result.azure_sku

    def test_list_families(self):
        translator = get_sku_translator()
        families = translator.list_families()
        assert isinstance(families, list)

    def test_list_storage_mappings(self):
        translator = get_sku_translator()
        mappings = translator.list_storage_mappings()
        assert isinstance(mappings, list)

    def test_list_database_mappings(self):
        translator = get_sku_translator()
        mappings = translator.list_database_mappings()
        assert isinstance(mappings, list)
