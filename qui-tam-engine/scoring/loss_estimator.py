"""
Government loss estimation by fraud category.

Uses OIG-aligned methodology:
  - Ghost facilities / excluded operators: 100% of payments are fraudulent
  - Non-terminal enrollment (high ALOS, low mortality): excess over national mean
  - Compound outliers: higher fraud portion estimate
  - Revenue per beneficiary approaching cap: full excess over cap

National benchmarks (source: OIG, CMS):
  - Mean ALOS: ~92 days (skewed by long-stay outliers)
  - Median ALOS: ~18 days
  - Average daily rate: ~$195 (routine home care per diem)
  - Medicare aggregate cap: ~$32-34K per beneficiary per year
"""

from config import AVG_HOSPICE_DAILY_RATE, NATIONAL_MEAN_LOS, NATIONAL_MEDIAN_LOS
from detection.base import Signal


def _extract_alos(signals: list[Signal]) -> float | None:
    """Extract ALOS from any signal that has it in evidence."""
    for s in signals:
        if "alos_days" in s.evidence:
            return s.evidence["alos_days"]
    return None


def estimate_hospice_govt_loss(entity, signals: list[Signal]) -> float:
    """
    Estimate government loss for a hospice entity.

    Loss estimation tiers:
      1. Ghost facility (HF01) or excluded operator (HF06):
         100% of estimated Medicare payments are fraudulent.
      2. Compound outlier (HF11 with 4+ flags):
         80% of estimated payments — systematic fraud pattern.
      3. Non-terminal enrollment (high ALOS, low mortality, low cancer dx):
         Excess = payments × (1 - national_mean_LOS / entity_LOS)
      4. Moderate statistical anomalies:
         30-50% of estimated payments depending on signal strength.
    """
    total_patients = entity.total_patients or 0
    total_episodes = entity.total_episodes or 0

    # Use whichever is larger as the volume metric
    volume = max(total_patients, total_episodes)
    if volume == 0:
        return 0.0

    # Get ALOS from signal evidence (any signal that detected it)
    alos = _extract_alos(signals)
    if alos is None:
        # Conservative default — use national mean if no LOS data available
        alos = NATIONAL_MEAN_LOS

    # Estimate total Medicare payments
    estimated_total_payments = volume * alos * AVG_HOSPICE_DAILY_RATE

    # Collect signal codes for classification
    signal_codes = {s.signal_code for s in signals}

    # Tier 1: Ghost facility or excluded operator — 100% fraudulent
    if signal_codes & {"HF01", "HF06"}:
        return estimated_total_payments

    # Tier 2: Compound outlier with 4+ flags — 80% fraudulent
    for s in signals:
        if s.signal_code == "HF11" and s.evidence.get("flag_count", 0) >= 4:
            return estimated_total_payments * 0.80

    # Tier 3: Non-terminal enrollment — calculate excess over national mean
    # This is the OIG approach: the "fraudulent portion" is the payments
    # attributable to keeping patients enrolled beyond when they should have
    # been discharged or never enrolled at all.
    if alos > NATIONAL_MEAN_LOS:
        excess_ratio = 1 - (NATIONAL_MEAN_LOS / alos)

        # Boost if corroborated by multiple signals
        corroboration_bonus = 1.0
        if "HF03" in signal_codes or "HF04" in signal_codes:
            # Low mortality or high live discharge confirms non-terminal enrollment
            corroboration_bonus = 1.2
        if "HF05" in signal_codes:
            # Low cancer % further confirms vague-diagnosis enrollment
            corroboration_bonus = min(corroboration_bonus * 1.1, 1.5)

        return estimated_total_payments * excess_ratio * corroboration_bonus

    # Tier 4: Has signals but ALOS is normal — use signal weight to estimate
    if signals:
        max_weight = max(s.weight for s in signals)
        total_weight = sum(s.weight for s in signals)
        # Scale fraud portion from 20-50% based on signal strength
        fraud_portion = min(0.20 + (total_weight / 100), 0.50)
        return estimated_total_payments * fraud_portion

    # Default: no signals, no loss
    return 0.0


def estimate_claim_count_hospice(entity, signals: list[Signal]) -> int:
    """
    Estimate the number of individual false claims.

    For hospice: each daily per-diem billing = 1 false claim under 31 USC §3729.
    This is important because FCA penalties are PER CLAIM ($13,946-$27,894 each).

    For ghost facilities / excluded operators: all claims are false.
    For non-terminal enrollment: only excess days are false claims.
    """
    total_patients = entity.total_patients or 0
    total_episodes = entity.total_episodes or 0
    volume = max(total_patients, total_episodes)

    if volume == 0:
        return 1

    alos = _extract_alos(signals)
    if alos is None:
        alos = NATIONAL_MEAN_LOS

    signal_codes = {s.signal_code for s in signals}
    total_patient_days = int(volume * alos)

    # Ghost facility / excluded operator: all patient-days are false claims
    if signal_codes & {"HF01", "HF06"}:
        return max(total_patient_days, 1)

    # Non-terminal enrollment: only excess days beyond national mean
    if alos > NATIONAL_MEAN_LOS:
        excess_days_per_patient = alos - NATIONAL_MEAN_LOS
        return max(int(volume * excess_days_per_patient), 1)

    # Default: conservative estimate — 30% of patient-days
    return max(int(total_patient_days * 0.30), 1)
