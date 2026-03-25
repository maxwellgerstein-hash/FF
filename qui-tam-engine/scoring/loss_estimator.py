"""
Government loss estimation by fraud category.

Phase 1: Hospice only (uses episode counts × daily rate × LOS).
Phase 2 will add actual Medicare payment data.
"""

from config import AVG_HOSPICE_DAILY_RATE, NATIONAL_MEDIAN_LOS
from detection.base import Signal


def estimate_hospice_govt_loss(entity, signals: list[Signal]) -> float:
    """
    Estimate government loss for a hospice entity.

    For Phase 1 (no payment data), use:
      loss = total_patients x average_LOS x daily_rate

    For ghost facilities (HF01) or excluded operators (HF06):
      100% of estimated payments are fraudulent.

    For statistical anomalies (HF02 upcoding, HF03/HF04 non-terminal):
      Excess = payments x (1 - national_median_LOS / entity_LOS)
    """
    total_patients = entity.total_patients or 0
    total_episodes = entity.total_episodes or 0

    # Use whichever is larger as the volume metric
    volume = max(total_patients, total_episodes)
    if volume == 0:
        return 0.0

    # Get ALOS from measures (if available via HF02 signal)
    alos = None
    for s in signals:
        if s.signal_code == "HF02" and "alos_days" in s.evidence:
            alos = s.evidence["alos_days"]
            break

    if not alos:
        alos = 90  # Conservative default if no LOS data

    # Estimate total Medicare payments
    estimated_total_payments = volume * alos * AVG_HOSPICE_DAILY_RATE

    # If ghost facility or excluded operator, 100% is fraudulent
    is_ghost = any(
        s.signal_code in ("HF01", "HF06") for s in signals
    )
    if is_ghost:
        return estimated_total_payments

    # For non-terminal enrollment (statistical fraud), calculate excess
    if alos > NATIONAL_MEDIAN_LOS:
        excess_ratio = 1 - (NATIONAL_MEDIAN_LOS / alos)
        return estimated_total_payments * excess_ratio

    # Default: 50% if can't determine fraud portion
    return estimated_total_payments * 0.5


def estimate_claim_count_hospice(entity, signals: list[Signal]) -> int:
    """
    Estimate the number of individual false claims.
    For hospice: each daily per-diem claim = 1 false claim.
    """
    total_patients = entity.total_patients or 0
    total_episodes = entity.total_episodes or 0
    volume = max(total_patients, total_episodes)

    if volume == 0:
        return 1

    alos = None
    for s in signals:
        if s.signal_code == "HF02" and "alos_days" in s.evidence:
            alos = s.evidence["alos_days"]
            break

    if not alos:
        alos = 90

    # Each day of service = 1 false claim
    return max(int(volume * alos), 1)
