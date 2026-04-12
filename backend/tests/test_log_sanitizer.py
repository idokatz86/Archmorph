"""Tests for log_sanitizer.py — CWE-117 log injection prevention."""

from log_sanitizer import safe


class TestSafe:
    def test_plain_string(self):
        assert safe("hello world") == "hello world"

    def test_strips_newlines(self):
        result = safe("line1\nline2\rline3")
        assert "\n" not in result
        assert "\r" not in result

    def test_strips_crlf(self):
        result = safe("hello\r\nworld")
        assert "\r\n" not in result

    def test_none_input(self):
        result = safe(None)
        assert isinstance(result, str)

    def test_numeric_input(self):
        result = safe(42)
        assert result == "42"

    def test_empty_string(self):
        assert safe("") == ""

    def test_dict_input(self):
        result = safe({"key": "value"})
        assert isinstance(result, str)

    def test_injection_attempt(self):
        result = safe("user input\nINFO: fake log entry")
        assert "\n" not in result
