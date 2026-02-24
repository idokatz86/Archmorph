"""
Unit tests for the version module.

Covers:
  - __version__ is a valid semver string
  - Version is importable and non-empty
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from version import __version__


class TestVersionModule:
    """Validate the version module single source of truth."""

    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_not_empty(self):
        assert len(__version__) > 0

    def test_version_semver_format(self):
        parts = __version__.split(".")
        assert len(parts) >= 2, "Version should be at least major.minor"
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' is not a digit"

    def test_version_is_current(self):
        # Verify version is a valid semver — specific value may change
        parts = __version__.split(".")
        assert len(parts) == 3
        major = int(parts[0])
        assert major >= 2, "Expected major version >= 2"
