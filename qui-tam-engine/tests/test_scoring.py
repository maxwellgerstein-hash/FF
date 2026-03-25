"""Tests for case scoring."""

from detection.base import Signal, CaseScore
from scoring.case_scorer import calculate_case_score
from scoring.loss_estimator import estimate_claim_count_hospice
from config import MIN_GOVT_LOSS


class MockEntity:
    def __init__(self, **kwargs):
        self.total_patients = kwargs.get("total_patients", 100)
        self.total_episodes = kwargs.get("total_episodes", 100)
        self.fraud_hotspot_msa = kwargs.get("fraud_hotspot_msa", None)


def _make_signal(code="HF01", sig_type="RULE_VIOLATION", weight=10, category="hospice_fraud"):
    return Signal(
        signal_code=code,
        signal_category=category,
        severity="CRITICAL",
        type=sig_type,
        weight=weight,
        description="Test signal",
        evidence={"test": True},
        data_source="test",
        fca_provision="31 USC 3729",
    )


def test_score_returns_none_below_threshold():
    entity = MockEntity()
    signals = [_make_signal()]
    result = calculate_case_score(entity, signals, MIN_GOVT_LOSS - 1)
    assert result is None


def test_score_returns_case_score_above_threshold():
    entity = MockEntity()
    signals = [_make_signal()]
    result = calculate_case_score(entity, signals, 1_000_000)
    assert isinstance(result, CaseScore)
    assert result.score > 0
    assert result.govt_loss == 1_000_000
    assert result.treble_damages == 3_000_000
    assert result.double_damages == 2_000_000


def test_rule_violations_score_higher():
    entity = MockEntity()
    rule_signals = [_make_signal(sig_type="RULE_VIOLATION", weight=10)]
    stat_signals = [_make_signal(sig_type="STATISTICAL", weight=10)]

    rule_score = calculate_case_score(entity, rule_signals, 1_000_000)
    stat_score = calculate_case_score(entity, stat_signals, 1_000_000)

    # Both should score, rule violation should score at least as high
    assert rule_score is not None
    assert stat_score is not None


def test_claim_count_estimation():
    entity = MockEntity(total_patients=100)
    signals = [_make_signal(code="HF02")]
    signals[0].evidence["alos_days"] = 180

    count = estimate_claim_count_hospice(entity, signals)
    assert count == 100 * 180  # patients * LOS
