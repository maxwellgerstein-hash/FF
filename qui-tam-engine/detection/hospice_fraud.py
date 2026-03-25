"""
Hospice Fraud Signal Detection — Category A (HF01–HF08).

Phase 1 implements signals that can be detected from:
  - CMS Hospice Compare (general info + quality measures)
  - OIG LEIE (exclusion list)
  - NPPES (authorized official names)

Deferred to Phase 2+: HF05, HF09, HF10, HF11, HF12
"""

import re
from datetime import datetime, date

from detection.base import Signal
from config import KNOWN_VIRTUAL_CHAINS, PO_BOX_PATTERNS


def detect_hospice_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """
    Run hospice fraud signals against a single entity.

    Args:
        entity: Entity ORM object
        hospice_measures: Dict of measure_key -> score (pivoted from Provider data)
        db_session: For LEIE lookups

    Returns:
        List of Signal objects
    """
    signals = []
    address_upper = (entity.address or "").upper()

    # ── HF01: Ghost hospice — virtual office / PO Box ──
    is_virtual = any(chain in address_upper for chain in KNOWN_VIRTUAL_CHAINS)
    is_po_box = any(re.search(pat, address_upper) for pat in PO_BOX_PATTERNS)

    if is_virtual or is_po_box:
        addr_type = "virtual_office" if is_virtual else "po_box"
        signals.append(Signal(
            signal_code="HF01",
            signal_category="hospice_fraud",
            severity="CRITICAL",
            type="RULE_VIOLATION",
            weight=10,
            description=(
                f"Hospice at {'virtual office' if is_virtual else 'PO Box'}: "
                f"{entity.address}"
            ),
            evidence={
                "address": entity.address,
                "address_type": addr_type,
            },
            data_source="cms_hospice_general",
            fca_provision="31 USC \u00a73729(a)(1)(A) \u2014 false claims from non-existent facility",
            violation_date_start=_parse_date(entity.certification_date),
            violation_date_end=date.today(),
        ))

    # ── HF02: Abnormal average length of stay ──
    alos = _safe_float(hospice_measures.get("alos"))
    if alos is not None and alos > 150:
        weight = 8 if alos > 200 else 6
        signals.append(Signal(
            signal_code="HF02",
            signal_category="hospice_fraud",
            severity="HIGH",
            type="STATISTICAL",
            weight=weight,
            description=(
                f"Average LOS: {alos:.0f} days "
                f"(national median ~18 days, ratio: {alos / 18:.1f}x)"
            ),
            evidence={
                "alos_days": alos,
                "national_median": 18,
                "ratio": round(alos / 18, 1),
            },
            data_source="cms_hospice_measures",
            fca_provision="31 USC \u00a73729(a)(1)(A) \u2014 enrolling non-terminal patients",
            violation_date_start=_parse_date(hospice_measures.get("start_date")),
            violation_date_end=_parse_date(hospice_measures.get("end_date")),
        ))

    # ── HF03: Abnormally low mortality rate ──
    live_discharge = _safe_float(hospice_measures.get("live_discharge"))
    if live_discharge is not None:
        mortality_rate = 100 - live_discharge
        if mortality_rate < 30:
            signals.append(Signal(
                signal_code="HF03",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=f"Mortality rate ~{mortality_rate:.0f}% (expected 70-80%)",
                evidence={
                    "live_discharge_pct": live_discharge,
                    "est_mortality_pct": mortality_rate,
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC \u00a73729(a)(1)(A) \u2014 enrolling non-terminal patients",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF04: High live discharge rate ──
    if live_discharge is not None and live_discharge > 50:
        signals.append(Signal(
            signal_code="HF04",
            signal_category="hospice_fraud",
            severity="HIGH",
            type="STATISTICAL",
            weight=7,
            description=(
                f"Live discharge rate: {live_discharge:.0f}% (national avg ~20%)"
            ),
            evidence={
                "live_discharge_pct": live_discharge,
                "national_avg": 20,
            },
            data_source="cms_hospice_measures",
            fca_provision="31 USC \u00a73729(a)(1)(A)",
            violation_date_start=_parse_date(hospice_measures.get("start_date")),
            violation_date_end=_parse_date(hospice_measures.get("end_date")),
        ))

    # ── HF06: Authorized official on OIG exclusion list ──
    auth_name = (
        f"{entity.authorized_official_first_name or ''} "
        f"{entity.authorized_official_last_name or ''}"
    ).strip()
    if auth_name and len(auth_name) > 2:
        from ingestion.oig_leie import check_leie_match
        leie_match = check_leie_match(auth_name, entity.state or "", db_session)
        if leie_match:
            signals.append(Signal(
                signal_code="HF06",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="RULE_VIOLATION",
                weight=10,
                description=(
                    f"Authorized official '{auth_name}' matches excluded individual "
                    f"'{leie_match['name']}' (score: {leie_match['match_score']})"
                ),
                evidence={
                    "authorized_official": auth_name,
                    "leie_match_name": leie_match["name"],
                    "leie_exclusion_type": leie_match["excltype"],
                    "leie_exclusion_date": leie_match["excldate"],
                    "match_confidence": leie_match["match_score"],
                },
                data_source="nppes_bulk + oig_leie",
                fca_provision=(
                    "31 USC \u00a73729(a)(1)(A) \u2014 "
                    "excluded individual operating healthcare entity"
                ),
                violation_date_start=leie_match.get("excldate_parsed"),
                violation_date_end=date.today(),
            ))

    # ── HF07: New entity, immediate high volume ──
    cert_date = _parse_date(entity.certification_date)
    if cert_date:
        months_since = (date.today() - cert_date).days / 30
        episodes = entity.total_episodes or 0
        if months_since < 12 and episodes > 100:
            signals.append(Signal(
                signal_code="HF07",
                signal_category="hospice_fraud",
                severity="MEDIUM",
                type="STATISTICAL",
                weight=6,
                description=(
                    f"Certified {months_since:.0f} months ago, "
                    f"already {episodes} episodes"
                ),
                evidence={
                    "cert_date": str(cert_date),
                    "months": round(months_since),
                    "episodes": episodes,
                },
                data_source="cms_hospice_general",
                fca_provision="31 USC \u00a73729(a)(1)(A)",
                violation_date_start=cert_date,
                violation_date_end=date.today(),
            ))

    # ── HF08: Clustering — multiple hospices at same address ──
    if entity.address_normalized:
        from db.models import Entity as EntityModel
        same_addr_count = (
            db_session.query(EntityModel)
            .filter(
                EntityModel.address_normalized == entity.address_normalized,
                EntityModel.id != entity.id,
            )
            .count()
        )

        if same_addr_count >= 2:  # 3+ total at this address
            signals.append(Signal(
                signal_code="HF08",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=8,
                description=(
                    f"{same_addr_count + 1} hospice entities at: {entity.address}"
                ),
                evidence={
                    "address": entity.address,
                    "total_at_address": same_addr_count + 1,
                },
                data_source="cms_hospice_general",
                fca_provision="31 USC \u00a73729(a)(1)(A) \u2014 shell company pattern",
                violation_date_start=cert_date,
                violation_date_end=date.today(),
            ))

    return signals


def _safe_float(val) -> float | None:
    """Safely convert a value to float."""
    if val is None or str(val).strip().lower() in (
        "", "not available", "nan", "none",
    ):
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_date(raw) -> date | None:
    """Parse various date formats to a date object."""
    if not raw or str(raw).strip() == "":
        return None
    raw = str(raw).strip()
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y%m%d"]:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
