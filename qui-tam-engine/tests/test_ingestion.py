"""Tests for data ingestion utilities."""

from ingestion.oig_leie import normalize_name
from ingestion.cms_hospice import find_measure_code
from config import EXPECTED_MEASURE_CODES


def test_leie_normalize_name():
    assert normalize_name("JOHN DOE") == "JOHN DOE"
    assert normalize_name("  Jane   Smith  ") == "JANE SMITH"
    assert normalize_name("O'Brien-Jones") == "O BRIEN JONES"


def test_find_measure_code_exact():
    codes = ["H_ALOS_OBSERVED", "H_LIVE_DISCHARGE_OBSERVED", "H_CANCER_PCT"]
    assert find_measure_code(codes, "alos") == "H_ALOS_OBSERVED"
    assert find_measure_code(codes, "live_discharge") == "H_LIVE_DISCHARGE_OBSERVED"


def test_find_measure_code_partial():
    codes = ["SOME_ALOS_METRIC", "DISCHARGE_RATE", "OTHER"]
    result = find_measure_code(codes, "alos")
    assert result == "SOME_ALOS_METRIC"


def test_find_measure_code_missing():
    codes = ["UNRELATED_1", "UNRELATED_2"]
    result = find_measure_code(codes, "alos")
    assert result is None
