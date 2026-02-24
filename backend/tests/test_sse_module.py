"""
Unit tests for the SSE (Server-Sent Events) streaming helper.

Covers:
  - format_sse() output format
  - sse_response() returns correct StreamingResponse headers
  - heartbeat_wrapper passes events through
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sse import format_sse, sse_response, heartbeat_wrapper


class TestFormatSSE:
    """Test SSE event formatting."""

    def test_basic_event(self):
        result = format_sse("progress", {"step": 1})
        assert "event: progress" in result
        assert 'data: {"step": 1}' in result

    def test_event_with_id(self):
        result = format_sse("update", {"x": 1}, event_id="42")
        assert "id: 42" in result
        assert "event: update" in result

    def test_string_data(self):
        result = format_sse("msg", "hello")
        assert "data: hello" in result

    def test_dict_data_is_json(self):
        result = format_sse("data", {"key": "value"})
        # Extract the data line
        lines = result.split("\n")
        data_line = [l for l in lines if l.startswith("data:")]
        assert len(data_line) == 1
        parsed = json.loads(data_line[0].replace("data: ", ""))
        assert parsed["key"] == "value"

    def test_ends_with_double_newline(self):
        result = format_sse("test", {})
        assert result.endswith("\n\n")

    def test_no_id_when_none(self):
        result = format_sse("test", {})
        assert "id:" not in result


class TestSSEResponse:
    """Test sse_response returns proper StreamingResponse."""

    def test_returns_streaming_response(self):
        async def gen():
            yield "data: test\n\n"

        resp = sse_response(gen())
        assert resp.media_type == "text/event-stream"

    def test_has_cache_control(self):
        async def gen():
            yield "data: test\n\n"

        resp = sse_response(gen())
        headers = dict(resp.headers)
        assert "no-cache" in headers.get("cache-control", "")

    def test_has_connection_keepalive(self):
        async def gen():
            yield "data: test\n\n"

        resp = sse_response(gen())
        headers = dict(resp.headers)
        assert headers.get("connection") == "keep-alive"

    def test_has_nginx_buffering_off(self):
        async def gen():
            yield "data: test\n\n"

        resp = sse_response(gen())
        headers = dict(resp.headers)
        assert headers.get("x-accel-buffering") == "no"


class TestHeartbeatWrapper:
    """Test heartbeat_wrapper passes events through."""

    @pytest.mark.asyncio
    async def test_passes_events_through(self):
        async def gen():
            yield "event1"
            yield "event2"

        events = []
        async for event in heartbeat_wrapper(gen()):
            events.append(event)
        assert events == ["event1", "event2"]

    @pytest.mark.asyncio
    async def test_empty_generator(self):
        async def gen():
            return
            yield  # noqa: unreachable

        events = []
        async for event in heartbeat_wrapper(gen()):
            events.append(event)
        assert events == []
