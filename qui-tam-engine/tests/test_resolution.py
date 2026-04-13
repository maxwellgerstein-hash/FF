"""Tests for entity resolution."""

from resolution.entity_resolver import normalize_name, normalize_address


def test_normalize_name_removes_suffixes():
    assert normalize_name("ACME HOSPICE LLC") == "ACME HOSPICE"
    assert normalize_name("Good Care Services Inc.") == "GOOD CARE"
    assert normalize_name("Home Health Corp") == "HOME HEALTH"


def test_normalize_name_handles_punctuation():
    assert normalize_name("O'Brien & Associates") == "O BRIEN"
    assert normalize_name("Smith, Jones, LLC") == "SMITH JONES"


def test_normalize_name_empty():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_normalize_address_abbreviations():
    assert "ST" in normalize_address("123 Main Street")
    assert "AVE" in normalize_address("456 Park Avenue")
    assert "BLVD" in normalize_address("789 Sunset Boulevard")


def test_normalize_address_empty():
    assert normalize_address("") == ""
    assert normalize_address(None) == ""
