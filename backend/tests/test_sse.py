"""Tests for SSE utilities (#281)."""
import asyncio
import pytest
from sse import format_sse, sse_response


def test_format_sse_basic():
    result = format_sse("progress", {"message": "step 1"})
    assert "event: progress" in result
    assert "data:" in result
    assert "step 1" in result
    assert result.endswith("\n\n")


def test_format_sse_with_event_id():
    result = format_sse("complete", {"done": True}, event_id="42")
    assert "id: 42" in result
    assert "event: complete" in result


def test_format_sse_string_data():
    result = format_sse("ping", "heartbeat")
    assert "data:" in result


def test_sse_response_returns_streaming():
    async def gen():
        yield format_sse("test", {})

    resp = sse_response(gen())
    assert resp.status_code == 200
    assert "text/event-stream" in resp.media_type
