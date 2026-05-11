"""Tests for SSE utilities (#281, #858)."""
import json

import anyio
import pytest

from sse import format_sse, sse_response
from job_queue import job_manager


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


@pytest.mark.asyncio
async def test_job_stream_sends_idle_heartbeat():
    job = job_manager.submit("heartbeat_test", owner_user_id="sse-test-user", tenant_id="sse-test")
    job_manager.start(job.job_id)
    stream = job_manager.stream(job.job_id)

    try:
        first = await stream.__anext__()
        assert "event: status" in first
        heartbeat = await stream.__anext__()
        assert heartbeat == ": heartbeat\n\n"
    finally:
        job_manager.cancel(job.job_id)
        await stream.aclose()


# ──────────────────────────────────────────────────────────────────────────────
# SSE event-framing correctness (#858 / F-API-7)
# JSON messages must never be split across SSE event boundaries.
# ──────────────────────────────────────────────────────────────────────────────

class TestSseEventFraming:
    """Verify that format_sse never emits raw newlines inside a data field."""

    def _parse_events(self, raw: str) -> list[dict]:
        """Parse raw SSE text into a list of event dicts.

        Returns a list of {'event': str, 'data': str} dicts.
        """
        events = []
        current: dict = {}
        data_lines: list[str] = []
        for line in raw.split("\n"):
            if line == "":
                if data_lines or current.get("event"):
                    current["data"] = "\n".join(data_lines)
                    events.append(current)
                    current = {}
                    data_lines = []
            elif line.startswith("event: "):
                current["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
            elif line.startswith("id: "):
                current["id"] = line[len("id: "):]
        return events

    def test_json_dict_no_raw_newlines_in_data_field(self):
        """json.dumps escapes newlines, so no raw \\n should appear inside data: fields."""
        payload = {"code": "line1\nline2\nline3", "nested": {"key": "val\nue"}}
        raw = format_sse("code", payload)
        # Collect each 'data:' field value; none should contain a raw newline mid-value.
        for line in raw.split("\n"):
            if line.startswith("data: "):
                field_value = line[len("data: "):]
                # The field value itself must not contain embedded newlines.
                assert "\n" not in field_value, (
                    f"Embedded newline found in SSE data field: {field_value!r}"
                )

    def test_string_payload_with_newlines_emits_multi_data_lines(self):
        """Multi-line string payloads must be split into multiple data: lines (#858)."""
        raw_string = "line one\nline two\nline three"
        raw = format_sse("code_chunk", raw_string)

        data_lines = [
            ln[len("data: "):] for ln in raw.split("\n") if ln.startswith("data: ")
        ]
        assert data_lines == ["line one", "line two", "line three"], (
            f"Expected 3 separate data: lines, got: {data_lines}"
        )

    def test_string_payload_reassembles_correctly(self):
        """Verify the client can reconstruct the original string from multi data: lines."""
        original = "alpha\nbeta\ngamma"
        raw = format_sse("chunk", original)
        data_lines = [
            ln[len("data: "):] for ln in raw.split("\n") if ln.startswith("data: ")
        ]
        reassembled = "\n".join(data_lines)
        assert reassembled == original

    def test_event_terminates_with_blank_line(self):
        raw = format_sse("progress", {"pct": 50})
        assert raw.endswith("\n\n"), "SSE event must end with blank line (\\n\\n)"

    def test_json_dict_is_valid_json_after_reassembly(self):
        """JSON dict payloads must survive an SSE round-trip as valid JSON."""
        payload = {"status": "ok", "services": ["AKS", "Cosmos DB"]}
        raw = format_sse("complete", payload)
        data_lines = [
            ln[len("data: "):] for ln in raw.split("\n") if ln.startswith("data: ")
        ]
        reassembled = "\n".join(data_lines)
        parsed = json.loads(reassembled)
        assert parsed == payload

    def test_burst_of_events_each_terminates_correctly(self):
        """Synthetic burst: 10 events must each parse as a separate, complete event."""
        burst = "".join(
            format_sse("progress", {"step": i, "message": f"step {i}\nnewline"})
            for i in range(10)
        )
        events = self._parse_events(burst)
        assert len(events) == 10, f"Expected 10 events, parsed {len(events)}"
        for ev in events:
            assert json.loads(ev["data"])["message"].startswith("step ")

    def test_sse_event_with_id(self):
        raw = format_sse("progress", {"val": 1}, event_id="42")
        assert "id: 42" in raw
        assert raw.endswith("\n\n")


# ──────────────────────────────────────────────────────────────────────────────
# SSE disconnect / client abort tests (#857)
# ──────────────────────────────────────────────────────────────────────────────

class TestSseDisconnect:
    """Verify that generators handle client disconnect gracefully."""

    @pytest.mark.asyncio
    async def test_generator_stops_on_disconnect(self):
        """A generator wrapped in sse_response must stop yielding after the client closes."""
        items_produced = []

        async def _counting_gen():
            for i in range(100):
                items_produced.append(i)
                yield format_sse("progress", {"step": i})

        gen = _counting_gen()
        # Simulate consuming only the first 3 items then 'disconnecting'
        count = 0
        async for _ in gen:
            count += 1
            if count >= 3:
                break

        # Generator stopped after 3 items (client abort simulation).
        assert len(items_produced) == 3

    @pytest.mark.asyncio
    async def test_generator_raises_generatorexit_on_aclose(self):
        """Calling aclose() on an async generator must raise GeneratorExit inside it."""
        exited = []

        async def _sensitive_gen():
            try:
                for i in range(10):
                    yield format_sse("data", {"i": i})
            except GeneratorExit:
                exited.append(True)

        gen = _sensitive_gen()
        await gen.__anext__()  # start
        await gen.aclose()     # simulate client disconnect

        # GeneratorExit was propagated into the generator.
        assert exited == [True]

    @pytest.mark.asyncio
    async def test_sse_response_generator_is_consumed_lazily(self):
        """sse_response must return without consuming the generator eagerly."""
        produced = []

        async def _lazy_gen():
            for i in range(5):
                produced.append(i)
                yield format_sse("evt", {"i": i})

        # sse_response must not consume the generator at construction time.
        resp = sse_response(_lazy_gen())
        assert produced == [], (
            "sse_response must not eagerly consume the generator at construction time"
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_streaming_response_disconnect_stops_asgi_producer(self):
        """An ASGI http.disconnect must stop the upstream SSE producer."""
        produced = []
        finalized = []

        async def _producer():
            try:
                for i in range(100):
                    produced.append(i)
                    yield format_sse("progress", {"step": i})
                    await anyio.lowlevel.checkpoint()
            finally:
                finalized.append(True)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_bodies = 0

        async def send(message):
            nonlocal sent_bodies
            if message["type"] == "http.response.body" and message.get("body"):
                sent_bodies += 1
                if sent_bodies > 1:
                    raise OSError("client disconnected")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "GET",
            "path": "/events",
            "raw_path": b"/events",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
        }

        with pytest.raises(Exception):
            await sse_response(_producer())(scope, receive, send)

        assert finalized == [True]
        assert len(produced) < 100
