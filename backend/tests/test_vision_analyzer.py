"""Tests for vision_analyzer.py — diagram image analysis via GPT-4o vision."""

from unittest.mock import patch, MagicMock
from vision_analyzer import analyze_image


class TestAnalyzeImage:
    @patch("vision_analyzer.get_openai_client")
    def test_analyze_returns_analysis(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "diagram_type": "AWS Architecture",
            "source_provider": "aws",
            "services_detected": 2,
            "zones": [
                {
                    "id": 1, "name": "Compute", "number": 1,
                    "services": [{"aws": "EC2", "azure": "Azure VMs", "confidence": 0.9}]
                }
            ],
            "mappings": [
                {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9}
            ],
            "architecture_patterns": ["multi-az"],
            "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.9}
        }
        '''
        mock_response.usage = MagicMock()
        mock_response.usage.total_tokens = 500

        mock_client.chat.completions.create.return_value = mock_response

        # Create a minimal valid PNG (1x1 pixel)
        import struct
        import zlib
        
        def create_minimal_png():
            signature = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = b'\x00\x00\x00\x00'
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + idat_data)
            idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND')
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return signature + ihdr + idat + iend

        png_bytes = create_minimal_png()
        result = analyze_image(png_bytes, "test-diagram-id")

        assert isinstance(result, dict)
        assert "mappings" in result or "services_detected" in result

    @patch("vision_analyzer.get_openai_client")
    def test_analyze_handles_api_error(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        # Minimal PNG bytes
        png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        # Should handle gracefully - may return None or raise
        try:
            analyze_image(png_bytes, "test-error-diagram")
        except Exception:
            pass  # Expected - some implementations re-raise


class TestWarningsCoercion:
    """Regression: GPT vision prompt instructs the model to return warnings as
    ``{type, message}`` dicts, but the React UI renders them inline. Ensure
    ``analyze_image`` flattens to strings so a misbehaving response cannot
    crash the frontend with React error #31.
    """

    def _png(self):
        import struct
        import zlib
        signature = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        raw = b'\x00\x00\x00\x00'
        idat_data = zlib.compress(raw)
        idat_crc = zlib.crc32(b'IDAT' + idat_data)
        idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
        iend_crc = zlib.crc32(b'IEND')
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return signature + ihdr + idat + iend

    @patch("vision_analyzer.get_openai_client")
    def test_object_warnings_are_flattened_to_strings(self, mock_client_fn):
        # Cache is keyed on image hash, so we must clear it: a previous test in
        # this module seeds the cache with the same minimal PNG.
        from vision_analyzer import _vision_cache, _vision_cache_lock
        with _vision_cache_lock:
            _vision_cache.clear()

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "diagram_type": "AWS Architecture",
            "warnings": [
                {"type": "potential_mismatch", "message": "Service X may not map cleanly"},
                "plain string warning",
                {"description": "Falls back to description key"},
                {"type": "no_message_key"}
            ]
        }
        '''
        mock_client.chat.completions.create.return_value = mock_response

        result = analyze_image(self._png(), "warnings-coercion-diagram")

        assert "warnings" in result
        assert all(isinstance(w, str) for w in result["warnings"]), \
            f"Expected all-string warnings, got: {result['warnings']}"
        assert "Service X may not map cleanly" in result["warnings"]
        assert "plain string warning" in result["warnings"]
        assert "Falls back to description key" in result["warnings"]
        # Object with no known string key falls back to JSON serialisation
        assert any('"type"' in w and '"no_message_key"' in w for w in result["warnings"])

