"""Tests for hospice fraud signal detection."""

from detection.hospice_fraud import _safe_float, _parse_date
from datetime import date


def test_safe_float():
    assert _safe_float("123.45") == 123.45
    assert _safe_float("1,234.56") == 1234.56
    assert _safe_float("Not Available") is None
    assert _safe_float("") is None
    assert _safe_float(None) is None
    assert _safe_float("nan") is None


def test_parse_date():
    assert _parse_date("01/15/2024") == date(2024, 1, 15)
    assert _parse_date("2024-01-15") == date(2024, 1, 15)
    assert _parse_date("20240115") == date(2024, 1, 15)
    assert _parse_date("") is None
    assert _parse_date(None) is None
