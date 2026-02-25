"""Tests for logging_config module (#281)."""
import logging
from logging_config import configure_logging, correlation_id_var


def test_configure_logging_sets_level():
    configure_logging("WARNING")
    root = logging.getLogger()
    assert root.level <= logging.WARNING


def test_configure_logging_default():
    configure_logging()
    root = logging.getLogger()
    assert root.level <= logging.INFO


def test_correlation_id_var_default():
    assert correlation_id_var.get() is not None or correlation_id_var.get() == ""


def test_correlation_id_var_set():
    token = correlation_id_var.set("test-123")
    assert correlation_id_var.get() == "test-123"
    correlation_id_var.reset(token)
