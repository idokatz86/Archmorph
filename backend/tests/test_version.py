"""Tests for version module (#281)."""
from version import __version__


def test_version_is_string():
    assert isinstance(__version__, str)


def test_version_semver_format():
    parts = __version__.split(".")
    assert len(parts) == 3
    for p in parts:
        assert p.isdigit()


def test_version_at_least_3():
    major = int(__version__.split(".")[0])
    assert major >= 3
