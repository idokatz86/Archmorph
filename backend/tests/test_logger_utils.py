from utils.logger_utils import sanitize_log

def test_sanitize_log_strings():
    assert sanitize_log("test\nstring") == "teststring"
    assert sanitize_log("test\rstring") == "teststring"
    assert sanitize_log("test\r\nstring") == "teststring"
    assert sanitize_log("test") == "test"

def test_sanitize_log_non_strings():
    assert sanitize_log(123) == 123
    assert sanitize_log(["a", "b"]) == ["a", "b"]
    assert sanitize_log(None) is None
    assert sanitize_log({"key": "value"}) == {"key": "value"}
