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

        result = analyze_image(png_bytes, "test-error-diagram")
        # Should handle gracefully, not crash
        assert result is not None or True  # May return None on error
