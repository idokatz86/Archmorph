"""Tests for Azure pricing cache Blob Storage persistence (Issue #91)."""

import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.azure_pricing as pricing


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset cache state between tests."""
    pricing._price_cache = {}
    pricing._cache_loaded = False
    yield
    pricing._price_cache = {}
    pricing._cache_loaded = False


class TestBlobClientCreation:
    @patch.dict(os.environ, {"AZURE_STORAGE_ACCOUNT_URL": "", "AZURE_STORAGE_CONNECTION_STRING": ""})
    def test_returns_none_when_not_configured(self):
        old_url = pricing.AZURE_STORAGE_ACCOUNT_URL
        old_cs = pricing.AZURE_STORAGE_CONNECTION_STRING
        pricing.AZURE_STORAGE_ACCOUNT_URL = ""
        pricing.AZURE_STORAGE_CONNECTION_STRING = ""
        try:
            assert pricing._get_blob_client() is None
        finally:
            pricing.AZURE_STORAGE_ACCOUNT_URL = old_url
            pricing.AZURE_STORAGE_CONNECTION_STRING = old_cs

    @patch("services.azure_pricing.AZURE_STORAGE_ACCOUNT_URL", "https://test.blob.core.windows.net")
    def test_creates_blob_client_with_rbac(self):
        mock_bsc = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob
        mock_bsc.get_container_client.return_value = mock_container

        with patch("services.azure_pricing.AZURE_STORAGE_CONNECTION_STRING", ""):
            with patch.dict("sys.modules", {}):
                from unittest.mock import patch as p2
                with p2("azure.storage.blob.BlobServiceClient", return_value=mock_bsc):
                    with p2("azure.identity.DefaultAzureCredential"):
                        result = pricing._get_blob_client()
                        assert result is mock_blob


class TestCacheValidity:
    def test_valid_cache(self):
        data = {"cached_at": time.time() - 100}
        assert pricing._is_cache_valid(data) is True

    def test_expired_cache(self):
        data = {"cached_at": time.time() - (25 * 3600)}  # 25h ago with 24h default TTL
        assert pricing._is_cache_valid(data) is False

    def test_missing_cached_at(self):
        assert pricing._is_cache_valid({}) is False


class TestLoadCacheWithBlob:
    @patch("services.azure_pricing._get_blob_client")
    def test_loads_from_blob_when_valid(self, mock_blob_fn):
        mock_blob = MagicMock()
        cache_data = {"cached_at": time.time(), "prices_westeurope": {"Azure SQL": 50}}
        mock_blob.download_blob.return_value.readall.return_value = json.dumps(cache_data).encode()
        mock_blob_fn.return_value = mock_blob

        result = pricing._load_cache()
        assert result.get("prices_westeurope", {}).get("Azure SQL") == 50

    @patch("services.azure_pricing._get_blob_client")
    def test_falls_back_to_disk_on_blob_error(self, mock_blob_fn):
        mock_blob_fn.return_value = None  # Blob not configured
        # _load_cache should fall through to disk (which is also empty in test)
        result = pricing._load_cache()
        assert result == {}


class TestSaveCacheWithBlob:
    @patch("services.azure_pricing._get_blob_client")
    @patch("services.azure_pricing.CACHE_DIR")
    @patch("services.azure_pricing.CACHE_FILE")
    def test_saves_to_blob_and_disk(self, mock_file, mock_dir, mock_blob_fn):
        mock_blob = MagicMock()
        mock_blob_fn.return_value = mock_blob
        mock_dir.mkdir = MagicMock()
        mock_file.write_text = MagicMock()

        data = {"prices_westeurope": {"Azure SQL": 50}}
        pricing._save_cache(data)

        # Blob should be called
        mock_blob.upload_blob.assert_called_once()
        # Disk should also be called
        mock_file.write_text.assert_called_once()
        # In-memory cache should be updated
        assert "cached_at" in pricing._price_cache


class TestInvalidateCacheWithBlob:
    @patch("services.azure_pricing._get_blob_client")
    @patch("services.azure_pricing.CACHE_FILE")
    def test_invalidate_deletes_blob(self, mock_file, mock_blob_fn):
        mock_blob = MagicMock()
        mock_blob_fn.return_value = mock_blob
        mock_file.exists.return_value = False

        pricing._price_cache = {"some": "data"}
        pricing._cache_loaded = True

        pricing.invalidate_cache()

        mock_blob.delete_blob.assert_called_once()
        assert pricing._price_cache == {}
        assert pricing._cache_loaded is False
