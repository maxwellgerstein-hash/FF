"""
Case Viability Scoring Engine.

NOT just fraud probability. This is LITIGATION VALUE:
  Case Score = Fraud Probability x Government Loss x Evidence Strength
               x Legal Precedent x DOJ Priority x First-to-File
               x (1 - Public Disclosure Risk) x Geographic Bonus

Minimum: $500K government loss to generate a case lead.
Priority: $1M+ government loss.
"""

from detection.base import Signal, CaseScore
from scoring.loss_estimator import estimate_claim_count_hospice
from config import (
    PENALTY_PER_CLAIM_LOW,
    PENALTY_PER_CLAIM_HIGH,
    MIN_GOVT_LOSS,
    FRAUD_HOTSPOT_MSAS,
    OIG_WORK_PLAN_PRIORITIES,
)


# Legal precedent scores by fraud category
PRECEDENT_SCORES = {
    "hospice_fraud": 0.95,
    "kickback": 0.95,
    "pharma_kickback": 0.95,
    "ppp_fraud": 0.90,
    "home_health_fraud": 0.90,
    "billing_fraud": 0.85,
    "dme_fraud": 0.85,
    "nursing_snf_fraud": 0.85,
    "telehealth_fraud": 0.80,
    "medicare_advantage_fraud": 0.85,
    "set_aside_fraud": 0.80,
    "fha_fraud": 0.80,
    "cybersecurity_false_cert": 0.70,
    "bid_rigging": 0.75,
    "customs_fraud": 0.70,
    "childcare_fraud": 0.65,
    "nemt_fraud": 0.70,
    "behavioral_health_fraud": 0.75,
}


def calculate_case_score(entity, signals: list[Signal], govt_loss: float) -> CaseScore | None:
    """
    Calculate case viability score (0-100) with confidence interval
    and full recovery estimation.
    """
    if govt_loss < MIN_GOVT_LOSS:
        return None

    # 1. Fraud probability (0-1)
    rule_violation_signals = [s for s in signals if s.type == "RULE_VIOLATION"]
    statistical_signals = [s for s in signals if s.type == "STATISTICAL"]

    raw_score = (
        sum(s.weight * 2 for s in rule_violation_signals)
        + sum(s.weight for s in statistical_signals)
    )
    max_possible = (
        sum(10 * 2 for _ in rule_violation_signals)
        + sum(10 for _ in statistical_signals)
    )
    fraud_probability = min(raw_score / max(max_possible, 1), 1.0)

    # 2. Government loss (0-1, scaled to $10M)
    loss_score = min(govt_loss / 10_000_000, 1.0)

    # 3. Evidence strength (0-1)
    unique_sources = len(set(s.data_source for s in signals))
    evidence_strength = min(unique_sources / 5, 1.0)
    if len(rule_violation_signals) >= 2:
        evidence_strength = min(evidence_strength * 1.3, 1.0)

    # 4. Legal precedent (0-1)
    category = signals[0].signal_category if signals else "hospice_fraud"
    legal_precedent = PRECEDENT_SCORES.get(category, 0.50)

    # 5. DOJ intervention likelihood (0-1)
    if category in OIG_WORK_PLAN_PRIORITIES:
        doj_likelihood = 0.80
    else:
        doj_likelihood = 0.40

    # 6. First-to-file assessment (0-1)
    # Phase 1: no CourtListener check yet. Label as UNKNOWN_CLEAR.
    first_to_file = 0.65

    # 7. Public disclosure risk (0-1, where 1 = low risk)
    if unique_sources >= 4:
        pd_risk = 0.70
    elif unique_sources >= 2:
        pd_risk = 0.50
    else:
        pd_risk = 0.25

    # COMPOSITE SCORE (0-100)
    base_score = (
        fraud_probability * 0.25
        + loss_score * 0.20
        + evidence_strength * 0.15
        + legal_precedent * 0.10
        + doj_likelihood * 0.10
        + first_to_file * 0.10
        + pd_risk * 0.10
    ) * 100

    # CORROBORATION BONUS
    unique_categories = len(set(s.signal_category for s in signals))
    if unique_categories >= 5:
        base_score = min(base_score * 1.4, 100)
    elif unique_categories >= 3:
        base_score = min(base_score * 1.2, 100)

    # GEOGRAPHIC HOTSPOT BONUS
    msa = entity.fraud_hotspot_msa
    if msa and msa in FRAUD_HOTSPOT_MSAS:
        base_score = min(base_score + (FRAUD_HOTSPOT_MSAS[msa] * 100), 100)

    # CONFIDENCE
    confidence = min(unique_sources / 4, 1.0) * min(len(signals) / 5, 1.0)

    # RECOVERY ESTIMATION
    claim_count = estimate_claim_count_hospice(entity, signals)

    treble_damages = govt_loss * 3
    double_damages = govt_loss * 2
    penalties_low = claim_count * PENALTY_PER_CLAIM_LOW
    penalties_high = claim_count * PENALTY_PER_CLAIM_HIGH

    total_recovery_low = double_damages + penalties_low
    total_recovery_high = treble_damages + penalties_high

    relator_share_low = total_recovery_low * 0.15
    relator_share_high = total_recovery_high * 0.30

    doj_label = (
        "HIGH" if doj_likelihood >= 0.7
        else "MEDIUM" if doj_likelihood >= 0.4
        else "LOW"
    )

    return CaseScore(
        score=round(base_score, 2),
        confidence=round(confidence, 2),
        govt_loss=govt_loss,
        estimated_claim_count=claim_count,
        treble_damages=treble_damages,
        double_damages=double_damages,
        penalties_low=penalties_low,
        penalties_high=penalties_high,
        total_recovery_low=total_recovery_low,
        total_recovery_high=total_recovery_high,
        relator_share_low=relator_share_low,
        relator_share_high=relator_share_high,
        doj_intervention_likelihood=doj_label,
    )
