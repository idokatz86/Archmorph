
def test__strings():
    assert("test\nstring") == "teststring"
    assert("test\rstring") == "teststring"
    assert("test\r\nstring") == "teststring"
    assert("test") == "test"

def test__non_strings():
    assert(123) == 123
    assert(["a", "b"]) == ["a", "b"]
    assert(None) is None
    assert({"key": "value"}) == {"key": "value"}
