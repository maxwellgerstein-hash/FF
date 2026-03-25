"""
Hospice Fraud Signal Detection — Category A (HF01–HF12).

Detection signals based on OIG methodology (OEI-02-16-00570), DOJ settlement
patterns, and CMS hospice program integrity guidance.

Data sources:
  - CMS Hospice Compare (general info + quality measures)
  - OIG LEIE (exclusion list)
  - NPPES (authorized official names, NPI deactivation)

Thresholds aligned with OIG "composite outlier" methodology:
  - ALOS: tiered at 60/100/180 days (national mean ~92, median ~18)
  - Live discharge: flags at 40% (national avg ~17-19%)
  - Mortality: flags below 60% (national norm 75-85%)
  - Cancer diagnosis: flags below 10% (national norm ~25-30%)
"""

import re
from datetime import datetime, date

from detection.base import Signal
from config import (
    KNOWN_VIRTUAL_CHAINS,
    PO_BOX_PATTERNS,
    HOSPICE_THRESHOLDS,
    NATIONAL_MEAN_LOS,
    NATIONAL_MEDIAN_LOS,
)


def detect_hospice_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """
    Run all hospice fraud signals against a single entity.

    Args:
        entity: Entity ORM object
        hospice_measures: Dict of measure_key -> score (pivoted from Provider data)
        db_session: For LEIE lookups and cross-entity queries

    Returns:
        List of Signal objects detected for this entity
    """
    signals = []
    address_upper = (entity.address or "").upper()
    cert_date = _parse_date(entity.certification_date)
    t = HOSPICE_THRESHOLDS

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
            fca_provision="31 USC §3729(a)(1)(A) — false claims from non-existent facility",
            violation_date_start=cert_date,
            violation_date_end=date.today(),
        ))

    # ── HF02: Abnormal average length of stay (tiered per OIG methodology) ──
    # OIG uses mean ALOS, not median. National mean ~92 days, median ~18 days.
    # Investigation trigger: mean ALOS > 180 days.
    # Hospices with ALOS > 60 are already above the national mean.
    alos = _safe_float(hospice_measures.get("alos"))
    if alos is not None:
        if alos > t["alos_critical"]:
            # > 180 days: OIG investigation trigger
            signals.append(Signal(
                signal_code="HF02",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="STATISTICAL",
                weight=9,
                description=(
                    f"Average LOS: {alos:.0f} days — exceeds OIG investigation "
                    f"threshold of {t['alos_critical']} days "
                    f"(national mean ~{NATIONAL_MEAN_LOS}, median ~{NATIONAL_MEDIAN_LOS})"
                ),
                evidence={
                    "alos_days": alos,
                    "national_mean": NATIONAL_MEAN_LOS,
                    "national_median": NATIONAL_MEDIAN_LOS,
                    "ratio_to_mean": round(alos / NATIONAL_MEAN_LOS, 1),
                    "ratio_to_median": round(alos / NATIONAL_MEDIAN_LOS, 1),
                    "oig_threshold": t["alos_critical"],
                    "tier": "critical",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — enrolling non-terminal patients",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))
        elif alos > t["alos_high"]:
            # 100-180 days: strong anomaly
            signals.append(Signal(
                signal_code="HF02",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Average LOS: {alos:.0f} days — well above national mean "
                    f"of ~{NATIONAL_MEAN_LOS} days "
                    f"({alos / NATIONAL_MEAN_LOS:.1f}x national mean)"
                ),
                evidence={
                    "alos_days": alos,
                    "national_mean": NATIONAL_MEAN_LOS,
                    "national_median": NATIONAL_MEDIAN_LOS,
                    "ratio_to_mean": round(alos / NATIONAL_MEAN_LOS, 1),
                    "oig_threshold": t["alos_critical"],
                    "tier": "high",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — enrolling non-terminal patients",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))
        elif alos > t["alos_medium"]:
            # 60-100 days: warrants review
            signals.append(Signal(
                signal_code="HF02",
                signal_category="hospice_fraud",
                severity="MEDIUM",
                type="STATISTICAL",
                weight=4,
                description=(
                    f"Average LOS: {alos:.0f} days — above national mean "
                    f"of ~{NATIONAL_MEAN_LOS} days"
                ),
                evidence={
                    "alos_days": alos,
                    "national_mean": NATIONAL_MEAN_LOS,
                    "ratio_to_mean": round(alos / NATIONAL_MEAN_LOS, 1),
                    "tier": "medium",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — possible non-terminal enrollment",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF03: Abnormally low mortality rate ──
    # Legitimate hospices: 75-85% mortality (patients die while enrolled).
    # Fraudulent hospices: often 20-50% because patients were never terminal.
    # OIG flags below 60%.
    live_discharge = _safe_float(hospice_measures.get("live_discharge"))
    if live_discharge is not None:
        mortality_rate = 100 - live_discharge
        if mortality_rate < t["mortality_critical"]:
            signals.append(Signal(
                signal_code="HF03",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="STATISTICAL",
                weight=9,
                description=(
                    f"Mortality rate ~{mortality_rate:.0f}% — critically low "
                    f"(national norm 75-85%, OIG flags below {t['mortality_low']}%)"
                ),
                evidence={
                    "live_discharge_pct": live_discharge,
                    "est_mortality_pct": round(mortality_rate, 1),
                    "national_norm_low": 75,
                    "national_norm_high": 85,
                    "oig_flag_below": t["mortality_low"],
                    "tier": "critical",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — enrolling non-terminal patients",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))
        elif mortality_rate < t["mortality_low"]:
            signals.append(Signal(
                signal_code="HF03",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Mortality rate ~{mortality_rate:.0f}% — below expected "
                    f"range of 75-85%"
                ),
                evidence={
                    "live_discharge_pct": live_discharge,
                    "est_mortality_pct": round(mortality_rate, 1),
                    "national_norm_low": 75,
                    "national_norm_high": 85,
                    "tier": "high",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — enrolling non-terminal patients",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF04: High live discharge rate ──
    # National average ~17-19%. OIG flags at ~2x national average (35-40%).
    # Confirmed fraud cases show 60-80%.
    if live_discharge is not None:
        if live_discharge > t["live_discharge_extreme"]:
            signals.append(Signal(
                signal_code="HF04",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="STATISTICAL",
                weight=9,
                description=(
                    f"Live discharge rate: {live_discharge:.0f}% — extreme outlier "
                    f"(national avg ~18%, OIG flags above {t['live_discharge_flag']}%)"
                ),
                evidence={
                    "live_discharge_pct": live_discharge,
                    "national_avg": 18,
                    "oig_flag_above": t["live_discharge_flag"],
                    "ratio_to_national": round(live_discharge / 18, 1),
                    "tier": "extreme",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — patients not terminally ill",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))
        elif live_discharge > t["live_discharge_flag"]:
            signals.append(Signal(
                signal_code="HF04",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Live discharge rate: {live_discharge:.0f}% — exceeds OIG "
                    f"flag threshold of {t['live_discharge_flag']}% "
                    f"(national avg ~18%)"
                ),
                evidence={
                    "live_discharge_pct": live_discharge,
                    "national_avg": 18,
                    "oig_flag_above": t["live_discharge_flag"],
                    "ratio_to_national": round(live_discharge / 18, 1),
                    "tier": "high",
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — patients not terminally ill",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF05: Low cancer diagnosis percentage ──
    # National norm: ~25-30% of hospice patients have cancer.
    # Fraudulent hospices often <10% — they enroll non-terminal patients with
    # vague diagnoses ("debility NOS", "adult failure to thrive") that are
    # harder to prognosticate and easier to fraudulently certify.
    cancer_pct = _safe_float(hospice_measures.get("cancer_pct"))
    if cancer_pct is not None:
        if cancer_pct < t["cancer_pct_low"]:
            signals.append(Signal(
                signal_code="HF05",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Cancer diagnosis rate: {cancer_pct:.0f}% — well below "
                    f"national norm of ~25-30% (suggests enrollment of "
                    f"non-terminal patients with vague diagnoses)"
                ),
                evidence={
                    "cancer_pct": cancer_pct,
                    "national_norm_low": 25,
                    "national_norm_high": 30,
                    "oig_flag_below": t["cancer_pct_low"],
                },
                data_source="cms_hospice_measures",
                fca_provision=(
                    "31 USC §3729(a)(1)(A) — enrolling patients with "
                    "non-terminal diagnoses to collect per-diem payments"
                ),
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))
        elif cancer_pct < t["cancer_pct_normal_low"]:
            signals.append(Signal(
                signal_code="HF05",
                signal_category="hospice_fraud",
                severity="MEDIUM",
                type="STATISTICAL",
                weight=4,
                description=(
                    f"Cancer diagnosis rate: {cancer_pct:.0f}% — below normal "
                    f"range of ~25-30%"
                ),
                evidence={
                    "cancer_pct": cancer_pct,
                    "national_norm_low": 25,
                    "national_norm_high": 30,
                },
                data_source="cms_hospice_measures",
                fca_provision="31 USC §3729(a)(1)(A) — possible non-terminal enrollment",
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF06: Excluded individual operating hospice ──
    # Check both authorized official AND facility name against LEIE.
    from ingestion.oig_leie import check_leie_match

    # 6a: Authorized official check
    auth_name = (
        f"{entity.authorized_official_first_name or ''} "
        f"{entity.authorized_official_last_name or ''}"
    ).strip()
    if auth_name and len(auth_name) > 2:
        leie_match = check_leie_match(auth_name, entity.state or "", db_session)
        if leie_match:
            signals.append(Signal(
                signal_code="HF06",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="RULE_VIOLATION",
                weight=10,
                description=(
                    f"Authorized official '{auth_name}' matches excluded "
                    f"individual '{leie_match['name']}' "
                    f"(match score: {leie_match['match_score']})"
                ),
                evidence={
                    "match_type": "authorized_official",
                    "authorized_official": auth_name,
                    "leie_match_name": leie_match["name"],
                    "leie_exclusion_type": leie_match["excltype"],
                    "leie_exclusion_date": leie_match["excldate"],
                    "match_confidence": leie_match["match_score"],
                },
                data_source="nppes_bulk + oig_leie",
                fca_provision=(
                    "31 USC §3729(a)(1)(A) — excluded individual operating "
                    "healthcare entity; 42 USC §1320a-7b — employment of "
                    "excluded individual"
                ),
                violation_date_start=leie_match.get("excldate_parsed"),
                violation_date_end=date.today(),
            ))

    # 6b: Facility name check against LEIE business names
    facility_name = (entity.name or "").strip()
    if facility_name and len(facility_name) > 3:
        leie_biz_match = check_leie_match(
            facility_name, entity.state or "", db_session
        )
        if leie_biz_match and leie_biz_match["match_score"] >= 92:
            signals.append(Signal(
                signal_code="HF06",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="RULE_VIOLATION",
                weight=10,
                description=(
                    f"Facility name '{facility_name}' matches excluded entity "
                    f"'{leie_biz_match['name']}' "
                    f"(match score: {leie_biz_match['match_score']})"
                ),
                evidence={
                    "match_type": "facility_name",
                    "facility_name": facility_name,
                    "leie_match_name": leie_biz_match["name"],
                    "leie_exclusion_type": leie_biz_match["excltype"],
                    "leie_exclusion_date": leie_biz_match["excldate"],
                    "match_confidence": leie_biz_match["match_score"],
                },
                data_source="cms_hospice_general + oig_leie",
                fca_provision=(
                    "31 USC §3729(a)(1)(A) — excluded entity billing Medicare"
                ),
                violation_date_start=leie_biz_match.get("excldate_parsed"),
                violation_date_end=date.today(),
            ))

    # ── HF07: New entity, rapid volume ──
    # OIG: newly established hospices (< 2-3 years) are disproportionately
    # represented in fraud cases. Flag if < 24 months old with significant volume.
    if cert_date:
        months_since = (date.today() - cert_date).days / 30
        episodes = entity.total_episodes or 0
        if months_since < t["new_entity_months"] and episodes > t["new_entity_min_episodes"]:
            # Scale severity by how extreme it is
            episodes_per_month = episodes / max(months_since, 1)
            if months_since < 6 and episodes > 200:
                severity, weight = "HIGH", 8
            elif months_since < 12 and episodes > 100:
                severity, weight = "HIGH", 7
            else:
                severity, weight = "MEDIUM", 5

            signals.append(Signal(
                signal_code="HF07",
                signal_category="hospice_fraud",
                severity=severity,
                type="STATISTICAL",
                weight=weight,
                description=(
                    f"Certified {months_since:.0f} months ago with {episodes} "
                    f"episodes ({episodes_per_month:.0f}/month) — OIG flags "
                    f"rapid-growth new hospices"
                ),
                evidence={
                    "cert_date": str(cert_date),
                    "months_since_cert": round(months_since),
                    "episodes": episodes,
                    "episodes_per_month": round(episodes_per_month, 1),
                },
                data_source="cms_hospice_general",
                fca_provision="31 USC §3729(a)(1)(A)",
                violation_date_start=cert_date,
                violation_date_end=date.today(),
            ))

    # ── HF08: Address clustering — multiple hospices at same address ──
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

        if same_addr_count >= t["address_cluster_min"]:
            signals.append(Signal(
                signal_code="HF08",
                signal_category="hospice_fraud",
                severity="HIGH" if same_addr_count >= 3 else "MEDIUM",
                type="STATISTICAL",
                weight=8 if same_addr_count >= 3 else 6,
                description=(
                    f"{same_addr_count + 1} hospice entities at: {entity.address}"
                ),
                evidence={
                    "address": entity.address,
                    "total_at_address": same_addr_count + 1,
                },
                data_source="cms_hospice_general",
                fca_provision="31 USC §3729(a)(1)(A) — shell company pattern",
                violation_date_start=cert_date,
                violation_date_end=date.today(),
            ))

    # ── HF09: Same owner controlling multiple hospices ──
    # OIG flags franchise-style operations where one individual is the
    # authorized official across multiple hospice NPIs.
    if entity.authorized_official_last_name:
        from db.models import Entity as EntityModel
        auth_key_last = entity.authorized_official_last_name.upper().strip()
        auth_key_first = (entity.authorized_official_first_name or "").upper().strip()

        if auth_key_last and len(auth_key_last) > 1:
            same_owner_query = db_session.query(EntityModel).filter(
                EntityModel.id != entity.id,
            )
            # Match on last name + first name initial to avoid false positives
            same_owner = [
                e for e in same_owner_query.all()
                if (e.authorized_official_last_name or "").upper().strip() == auth_key_last
                and (e.authorized_official_first_name or "").upper().strip()[:2] == auth_key_first[:2]
            ]

            if len(same_owner) >= t["same_owner_min_entities"]:
                other_names = [e.name for e in same_owner[:5]]
                signals.append(Signal(
                    signal_code="HF09",
                    signal_category="hospice_fraud",
                    severity="HIGH",
                    type="STATISTICAL",
                    weight=8,
                    description=(
                        f"Authorized official "
                        f"'{entity.authorized_official_first_name} "
                        f"{entity.authorized_official_last_name}' controls "
                        f"{len(same_owner) + 1} hospice entities"
                    ),
                    evidence={
                        "authorized_official": (
                            f"{entity.authorized_official_first_name} "
                            f"{entity.authorized_official_last_name}"
                        ),
                        "total_entities": len(same_owner) + 1,
                        "other_entities": other_names,
                    },
                    data_source="nppes_bulk + cms_hospice_general",
                    fca_provision=(
                        "31 USC §3729(a)(1)(A) — franchise fraud pattern; "
                        "multiple shell entities under common control"
                    ),
                    violation_date_start=cert_date,
                    violation_date_end=date.today(),
                ))

    # ── HF10: Estimated revenue per beneficiary approaching Medicare cap ──
    # Medicare hospice aggregate cap is ~$32-34K per beneficiary per year.
    # Hospices near or exceeding this likely have very long stays.
    episodes = entity.total_episodes or 0
    patients = entity.total_patients or 0
    if patients > 0 and alos is not None:
        est_revenue_per_beneficiary = alos * AVG_HOSPICE_DAILY_RATE
        if est_revenue_per_beneficiary > t["revenue_per_beneficiary_flag"]:
            signals.append(Signal(
                signal_code="HF10",
                signal_category="hospice_fraud",
                severity="HIGH",
                type="STATISTICAL",
                weight=7,
                description=(
                    f"Estimated revenue per beneficiary: "
                    f"${est_revenue_per_beneficiary:,.0f} — approaching "
                    f"Medicare aggregate cap (~$32-34K)"
                ),
                evidence={
                    "est_revenue_per_beneficiary": round(est_revenue_per_beneficiary),
                    "alos_days": alos,
                    "daily_rate": AVG_HOSPICE_DAILY_RATE,
                    "medicare_cap_approx": 33_000,
                },
                data_source="cms_hospice_measures + cms_hospice_general",
                fca_provision=(
                    "31 USC §3729(a)(1)(A) — systematically exceeding "
                    "Medicare hospice cap through long-stay enrollment"
                ),
                violation_date_start=_parse_date(hospice_measures.get("start_date")),
                violation_date_end=_parse_date(hospice_measures.get("end_date")),
            ))

    # ── HF11: Compound signal — OIG "Rule of Sixes" ──
    # OIG flags providers that exceed thresholds on 3+ of these metrics
    # simultaneously. Even individually weak signals become a strong case
    # when corroborated across multiple dimensions.
    compound_flags = []
    if alos is not None and alos > t["alos_medium"]:
        compound_flags.append(f"ALOS {alos:.0f} days")
    if live_discharge is not None and live_discharge > t["live_discharge_flag"]:
        compound_flags.append(f"live discharge {live_discharge:.0f}%")
    if cancer_pct is not None and cancer_pct < t["cancer_pct_normal_low"]:
        compound_flags.append(f"cancer dx {cancer_pct:.0f}%")
    if cert_date and (date.today() - cert_date).days / 30 < t["new_entity_months"]:
        compound_flags.append("new entity")
    if is_virtual or is_po_box:
        compound_flags.append("virtual/PO Box address")
    if entity.address_normalized:
        from db.models import Entity as EntityModel
        _addr_count = (
            db_session.query(EntityModel)
            .filter(
                EntityModel.address_normalized == entity.address_normalized,
                EntityModel.id != entity.id,
            )
            .count()
        )
        if _addr_count >= t["address_cluster_min"]:
            compound_flags.append(f"{_addr_count + 1} entities at address")

    if len(compound_flags) >= 3:
        signals.append(Signal(
            signal_code="HF11",
            signal_category="hospice_fraud",
            severity="CRITICAL" if len(compound_flags) >= 4 else "HIGH",
            type="STATISTICAL",
            weight=9 if len(compound_flags) >= 4 else 7,
            description=(
                f"Compound outlier: {len(compound_flags)} simultaneous red flags "
                f"({', '.join(compound_flags)}) — per OIG composite methodology, "
                f"3+ concurrent anomalies indicate systematic fraud"
            ),
            evidence={
                "flags": compound_flags,
                "flag_count": len(compound_flags),
                "methodology": "OIG composite outlier (OEI-02-16-00570)",
            },
            data_source="cms_hospice_measures + cms_hospice_general",
            fca_provision=(
                "31 USC §3729(a)(1)(A) — pattern and practice of false claims "
                "evidenced by multiple corroborating statistical anomalies"
            ),
            violation_date_start=_parse_date(hospice_measures.get("start_date")) or cert_date,
            violation_date_end=date.today(),
        ))

    return signals


# Import here to avoid circular import at module level
from config import AVG_HOSPICE_DAILY_RATE


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
