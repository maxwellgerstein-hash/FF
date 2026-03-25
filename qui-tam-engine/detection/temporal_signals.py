"""
Temporal & Trend-Based Fraud Signals (TP01–TP03).

Detects post-enforcement startups, rapid growth patterns,
and certification age vs volume mismatches.
"""

from datetime import date, datetime
from detection.base import Signal
from db.models import Entity, SourceRecord


def detect_temporal_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """Run temporal fraud detection signals."""
    signals = []

    signals.extend(_tp01_post_enforcement_startup(entity, db_session))
    signals.extend(_tp02_rapid_growth(entity, db_session))
    signals.extend(_tp03_age_volume_mismatch(entity, db_session))

    return signals


def _tp01_post_enforcement_startup(entity, db_session) -> list[Signal]:
    """TP01: Entity certified shortly after a DOJ settlement in same area."""
    signals = []

    cert_date = _parse_date(entity.certification_date)
    if not cert_date:
        return signals

    state = (entity.state or "").upper().strip()
    if not state:
        return signals

    doj_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "doj_settlement")
        .all()
    )

    for record in doj_records:
        data = record.get_data()
        doj_state = (data.get("state", data.get("location", "")) or "").upper().strip()
        settlement_date_str = data.get("settlement_date", data.get("date", ""))

        if not (doj_state == state or state in doj_state):
            continue

        settlement_date = _parse_date(settlement_date_str)
        if not settlement_date:
            continue

        # Check if entity was certified within 24 months AFTER the settlement
        days_diff = (cert_date - settlement_date).days
        if 0 < days_diff < 730:  # 0-24 months after settlement
            months_after = days_diff / 30
            signals.append(Signal(
                signal_code="TP01",
                signal_category="temporal_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Certified {months_after:.0f} months after DOJ settlement against "
                    f"'{data.get('entity_name', 'unknown')}' in {state} — "
                    f"possible phoenix operation (shut down and reopen under new name)"
                ),
                evidence={
                    "cert_date": str(cert_date),
                    "doj_settlement_target": data.get("entity_name", data.get("defendant", "")),
                    "settlement_date": str(settlement_date),
                    "months_after": round(months_after),
                    "settlement_amount": data.get("settlement_amount", ""),
                },
                data_source="doj_settlement + cms_hospice_general",
                fca_provision="31 USC §3729(a)(1)(A) — successor entity continuing fraud scheme",
                violation_date_start=cert_date,
                violation_date_end=date.today(),
            ))
            break  # One match is sufficient

    return signals


def _tp02_rapid_growth(entity, db_session) -> list[Signal]:
    """TP02: Entity growth rate far exceeds market norms."""
    signals = []

    cert_date = _parse_date(entity.certification_date)
    if not cert_date:
        return signals

    months_since = (date.today() - cert_date).days / 30
    if months_since < 6:
        return signals  # Too new to measure growth meaningfully

    episodes = entity.total_episodes or 0
    patients = entity.total_patients or 0
    volume = max(episodes, patients)

    if volume == 0:
        return signals

    # Monthly volume rate
    monthly_rate = volume / months_since

    # National avg: ~5,000 hospices serving ~1.7M patients = ~340 patients/hospice/year = ~28/month
    # For newer hospices, ramp-up period is normal, but > 50/month in first 2 years is extreme
    national_monthly_avg = 28

    if months_since < 24:
        threshold = national_monthly_avg * 3  # 3x avg for new entities
    else:
        threshold = national_monthly_avg * 2  # 2x avg for established entities

    if monthly_rate > threshold:
        ratio = monthly_rate / national_monthly_avg
        if ratio > 5:
            severity, weight = "CRITICAL", 8
        elif ratio > 3:
            severity, weight = "HIGH", 7
        else:
            severity, weight = "MEDIUM", 5

        signals.append(Signal(
            signal_code="TP02",
            signal_category="temporal_fraud",
            severity=severity,
            type="STATISTICAL",
            weight=weight,
            description=(
                f"Growth rate {monthly_rate:.0f} patients/month — "
                f"{ratio:.1f}x national average of ~{national_monthly_avg}/month. "
                f"Rapid growth in {'new' if months_since < 24 else 'established'} entity "
                f"({months_since:.0f} months old, {volume} total)"
            ),
            evidence={
                "monthly_rate": round(monthly_rate, 1),
                "national_avg_monthly": national_monthly_avg,
                "ratio": round(ratio, 1),
                "months_since_cert": round(months_since),
                "total_volume": volume,
            },
            data_source="cms_hospice_general",
            fca_provision="31 USC §3729(a)(1)(A) — rapid growth indicative of fraudulent enrollment",
            violation_date_start=cert_date,
            violation_date_end=date.today(),
        ))

    return signals


def _tp03_age_volume_mismatch(entity, db_session) -> list[Signal]:
    """TP03: Very new entity with volume in the top tier."""
    signals = []

    cert_date = _parse_date(entity.certification_date)
    if not cert_date:
        return signals

    months_since = (date.today() - cert_date).days / 30
    episodes = entity.total_episodes or 0
    patients = entity.total_patients or 0
    volume = max(episodes, patients)

    # Flag: < 12 months old with > 200 episodes/patients
    if months_since < 12 and volume > 200:
        signals.append(Signal(
            signal_code="TP03",
            signal_category="temporal_fraud",
            severity="HIGH",
            type="STATISTICAL",
            weight=7,
            description=(
                f"Entity only {months_since:.0f} months old but has {volume} "
                f"episodes/patients — top-tier volume for new entity "
                f"(suggests pre-existing patient pipeline or fraudulent enrollment)"
            ),
            evidence={
                "months_since_cert": round(months_since),
                "volume": volume,
                "cert_date": str(cert_date),
            },
            data_source="cms_hospice_general",
            fca_provision="31 USC §3729(a)(1)(A) — suspicious volume for newly certified entity",
            violation_date_start=cert_date,
            violation_date_end=date.today(),
        ))
    elif months_since < 6 and volume > 50:
        signals.append(Signal(
            signal_code="TP03",
            signal_category="temporal_fraud",
            severity="HIGH",
            type="STATISTICAL",
            weight=7,
            description=(
                f"Entity only {months_since:.0f} months old with {volume} "
                f"episodes — extremely rapid ramp-up"
            ),
            evidence={
                "months_since_cert": round(months_since),
                "volume": volume,
                "cert_date": str(cert_date),
            },
            data_source="cms_hospice_general",
            fca_provision="31 USC §3729(a)(1)(A) — suspicious volume for newly certified entity",
            violation_date_start=cert_date,
            violation_date_end=date.today(),
        ))

    return signals


def _parse_date(raw) -> date | None:
    if not raw or str(raw).strip() == "":
        return None
    raw = str(raw).strip()
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y%m%d"]:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
