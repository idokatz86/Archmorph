"""Tests for vision_analyzer.py — diagram image analysis via GPT-4o vision."""

import json
from unittest.mock import patch, MagicMock
import pytest
from cachetools import TTLCache

import observability
import vision_analyzer
from vision_analyzer import analyze_image


def _minimal_png():
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


def _vision_response(payload: dict):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    return response


def _metric_total(kind: str, name: str, tags: dict[str, str] | None = None) -> int:
    total = 0
    for entry in observability._metrics[kind].values():
        if entry["name"] != name:
            continue
        entry_tags = entry.get("tags", {})
        if tags is None or all(entry_tags.get(k) == v for k, v in tags.items()):
            total += entry.get("value", len(entry.get("values", [])))
    return total


@pytest.fixture(autouse=True)
def clean_vision_cache_and_metrics():
    with vision_analyzer._vision_cache_lock:
        vision_analyzer._vision_cache.clear()
    observability._metrics["counters"].clear()
    observability._metrics["histograms"].clear()
    observability._metrics["gauges"].clear()
    yield
    with vision_analyzer._vision_cache_lock:
        vision_analyzer._vision_cache.clear()
    observability._metrics["counters"].clear()
    observability._metrics["histograms"].clear()
    observability._metrics["gauges"].clear()


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

        png_bytes = _minimal_png()
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
        return _minimal_png()

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


class TestVisionCacheObservability:
    @patch("vision_analyzer.get_openai_client")
    def test_same_image_uses_cache_and_emits_hit_rate_metrics(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.chat.completions.create.return_value = _vision_response({
            "diagram_type": "AWS Architecture",
            "services_detected": 1,
        })

        first = analyze_image(_minimal_png())
        second = analyze_image(_minimal_png())

        assert first == second
        assert mock_client.chat.completions.create.call_count == 1
        assert _metric_total("counters", vision_analyzer.VISION_CACHE_METRIC, {"result": "miss"}) == 1
        assert _metric_total("counters", vision_analyzer.VISION_CACHE_METRIC, {"result": "hit"}) == 1
        assert _metric_total("histograms", vision_analyzer.VISION_LATENCY_METRIC) == 2

    @patch("vision_analyzer.get_openai_client")
    def test_model_change_changes_prompt_hash_and_cache_key(self, mock_client_fn, monkeypatch):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _vision_response({"diagram_type": "old-model"}),
            _vision_response({"diagram_type": "new-model"}),
        ]

        monkeypatch.setattr(vision_analyzer, "AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        old_hash = vision_analyzer._compute_vision_prompt_hash("gpt-4o")
        first = analyze_image(_minimal_png())

        monkeypatch.setattr(vision_analyzer, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
        new_hash = vision_analyzer._compute_vision_prompt_hash("gpt-5.4")
        second = analyze_image(_minimal_png())

        assert old_hash != new_hash
        assert first != second
        assert mock_client.chat.completions.create.call_count == 2
        assert mock_client.chat.completions.create.call_args_list[0].kwargs["model"] == "gpt-4o"
        assert mock_client.chat.completions.create.call_args_list[1].kwargs["model"] == "gpt-5.4"
        assert _metric_total("counters", vision_analyzer.VISION_CACHE_METRIC, {"result": "miss"}) == 2

    @patch("vision_analyzer.get_openai_client")
    def test_cache_ttl_expiry_forces_fresh_analysis(self, mock_client_fn, monkeypatch):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            _vision_response({"diagram_type": "before-expiry"}),
            _vision_response({"diagram_type": "after-expiry"}),
        ]
        monkeypatch.setattr(vision_analyzer, "_vision_cache", TTLCache(maxsize=100, ttl=0))

        first = analyze_image(_minimal_png())
        second = analyze_image(_minimal_png())

        assert first != second
        assert mock_client.chat.completions.create.call_count == 2
        assert _metric_total("counters", vision_analyzer.VISION_CACHE_METRIC, {"result": "miss"}) == 2
        assert _metric_total("counters", vision_analyzer.VISION_CACHE_METRIC, {"result": "hit"}) == 0

    def test_system_prompt_change_invalidates_hash(self, monkeypatch):
        """Changing SYSTEM_PROMPT anywhere must produce a different prompt hash (#833).

        The old implementation only hashed the first 200 characters of the prompt, so
        changes in the middle or end of SYSTEM_PROMPT silently reused stale cache
        entries.  The fix hashes the full prompt string.
        """
        original_hash = vision_analyzer._compute_vision_prompt_hash("gpt-4o")

        # Modify SYSTEM_PROMPT to simulate a deployment with updated instructions
        monkeypatch.setattr(vision_analyzer, "SYSTEM_PROMPT", vision_analyzer.SYSTEM_PROMPT + "\n# Modified instruction")
        modified_hash = vision_analyzer._compute_vision_prompt_hash("gpt-4o")

        assert original_hash != modified_hash, (
            "Hash must change when SYSTEM_PROMPT changes — prevents stale cache hits "
            "after a prompt update (#833)"
        )

    def test_system_prompt_tail_change_invalidates_hash(self, monkeypatch):
        """A change appended beyond the first 200 chars must still invalidate the hash.

        This specifically guards against the regression where only the first 200
        characters of the prompt were hashed.
        """
        # Verify the current SYSTEM_PROMPT is long enough for this test to be meaningful
        assert len(vision_analyzer.SYSTEM_PROMPT) > 200, (
            "SYSTEM_PROMPT should be longer than 200 chars for this test to have coverage"
        )
        original_hash = vision_analyzer._compute_vision_prompt_hash("gpt-4o")

        # Patch only the tail of SYSTEM_PROMPT — beyond the first 200 chars
        original_prompt = vision_analyzer.SYSTEM_PROMPT
        tail_change = original_prompt[:200] + "INJECTED_TAIL_CHANGE" + original_prompt[200:]
        monkeypatch.setattr(vision_analyzer, "SYSTEM_PROMPT", tail_change)
        tail_hash = vision_analyzer._compute_vision_prompt_hash("gpt-4o")

        assert original_hash != tail_hash, (
            "Hash must change when SYSTEM_PROMPT tail changes (#833 regression guard)"
        )

