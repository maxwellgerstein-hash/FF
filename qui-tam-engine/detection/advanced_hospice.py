"""
Advanced Hospice Fraud Signals (HF12–HF18).

Extends the core 11 signals with cross-source detection using
DOJ settlements, Open Payments, Cost Reports, SAM.gov, SEC, and News data.
"""

import json
from datetime import date, datetime
from detection.base import Signal
from db.models import Entity, SourceRecord

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


def detect_advanced_hospice_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """Run advanced hospice fraud detection signals."""
    signals = []

    signals.extend(_hf12_gip_abuse(entity, hospice_measures, db_session))
    signals.extend(_hf13_doj_settlement_match(entity, db_session))
    signals.extend(_hf14_open_payments_kickback(entity, db_session))
    signals.extend(_hf15_cost_report_anomalies(entity, db_session))
    signals.extend(_hf16_news_coverage(entity, db_session))
    signals.extend(_hf17_sam_exclusion(entity, db_session))
    signals.extend(_hf18_sec_filing_flags(entity, db_session))

    return signals


def _hf12_gip_abuse(entity, measures: dict, db_session) -> list[Signal]:
    """HF12: General Inpatient Care abuse — highest-paid hospice care level."""
    signals = []

    # Check cost report data for GIP utilization
    cost_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "cost_reports")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()
    ccn = entity.ccn or ""

    for record in cost_records:
        data = record.get_data()
        record_ccn = data.get("ccn", data.get("provider_ccn", ""))
        record_name = (data.get("provider_name", data.get("facility_name", "")) or "").upper()

        matched = False
        if ccn and record_ccn and ccn == record_ccn:
            matched = True
        elif fuzz and entity_name_upper and record_name:
            if fuzz.token_sort_ratio(entity_name_upper, record_name) >= 85:
                matched = True

        if matched:
            gip_pct = _safe_float(data.get("gip_pct", data.get("gip_utilization_pct")))
            if gip_pct is not None:
                if gip_pct > 20:
                    signals.append(Signal(
                        signal_code="HF12",
                        signal_category="hospice_fraud",
                        severity="CRITICAL",
                        type="STATISTICAL",
                        weight=9,
                        description=(
                            f"GIP utilization {gip_pct:.0f}% — extreme outlier "
                            f"(national avg 3-5%, billing ~$1,100/day vs $195/day routine)"
                        ),
                        evidence={"gip_pct": gip_pct, "national_avg": "3-5%", "gip_daily_rate": 1100, "routine_rate": 195},
                        data_source="cost_reports",
                        fca_provision="31 USC §3729(a)(1)(A) — upcoding routine care to GIP level",
                    ))
                elif gip_pct > 10:
                    signals.append(Signal(
                        signal_code="HF12",
                        signal_category="hospice_fraud",
                        severity="HIGH",
                        type="STATISTICAL",
                        weight=7,
                        description=f"GIP utilization {gip_pct:.0f}% — above expected range (national avg 3-5%)",
                        evidence={"gip_pct": gip_pct, "national_avg": "3-5%"},
                        data_source="cost_reports",
                        fca_provision="31 USC §3729(a)(1)(A) — potential GIP upcoding",
                    ))
            break

    return signals


def _hf13_doj_settlement_match(entity, db_session) -> list[Signal]:
    """HF13: Entity matches a known DOJ settlement target."""
    signals = []

    doj_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "doj_settlement")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()
    entity_state = (entity.state or "").upper()

    for record in doj_records:
        data = record.get_data()
        target_name = (data.get("entity_name", data.get("defendant", "")) or "").upper()

        if not target_name or not entity_name_upper:
            continue

        score = 0
        if fuzz:
            score = fuzz.token_sort_ratio(entity_name_upper, target_name)
        elif entity_name_upper in target_name or target_name in entity_name_upper:
            score = 85

        if score >= 80:
            settlement_amt = data.get("settlement_amount", "Unknown")
            settlement_date = data.get("settlement_date", data.get("date", "Unknown"))
            signals.append(Signal(
                signal_code="HF13",
                signal_category="hospice_fraud",
                severity="CRITICAL",
                type="RULE_VIOLATION",
                weight=10,
                description=(
                    f"Entity matches DOJ settlement target '{target_name}' "
                    f"(match: {score}%, settlement: ${settlement_amt:,} on {settlement_date})"
                    if isinstance(settlement_amt, (int, float))
                    else f"Entity matches DOJ settlement target '{target_name}' (match: {score}%)"
                ),
                evidence={
                    "doj_target": target_name,
                    "match_score": score,
                    "settlement_amount": settlement_amt,
                    "settlement_date": settlement_date,
                    "fraud_type": data.get("fraud_type", "Unknown"),
                    "press_release_url": data.get("press_release_url", data.get("url", "")),
                },
                data_source="doj_settlement",
                fca_provision="31 USC §3729 — entity with prior FCA settlement history",
            ))
            break  # One match is enough

    return signals


def _hf14_open_payments_kickback(entity, db_session) -> list[Signal]:
    """HF14: Authorized official receiving industry payments (kickback signal)."""
    signals = []

    auth_first = (entity.authorized_official_first_name or "").upper().strip()
    auth_last = (entity.authorized_official_last_name or "").upper().strip()

    if not auth_last or len(auth_last) < 2:
        return signals

    op_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "open_payments")
        .all()
    )

    total_payments = 0
    payment_count = 0
    payers = {}

    for record in op_records:
        data = record.get_data()
        phys_last = (data.get("physician_last_name", data.get("covered_recipient_last_name", "")) or "").upper().strip()
        phys_first = (data.get("physician_first_name", data.get("covered_recipient_first_name", "")) or "").upper().strip()

        if phys_last == auth_last and phys_first[:2] == auth_first[:2]:
            amt = _safe_float(data.get("total_amount_of_payment_usdollars", data.get("amount", 0)))
            if amt:
                total_payments += amt
                payment_count += 1
                payer = data.get("applicable_manufacturer_or_applicable_gpo_making_payment_name",
                               data.get("manufacturer", "Unknown"))
                payers[payer] = payers.get(payer, 0) + amt

    if total_payments > 100_000:
        severity, weight = "CRITICAL", 9
    elif total_payments > 50_000:
        severity, weight = "HIGH", 7
    elif total_payments > 10_000:
        severity, weight = "MEDIUM", 5
    else:
        return signals

    top_payers = sorted(payers.items(), key=lambda x: -x[1])[:5]

    signals.append(Signal(
        signal_code="HF14",
        signal_category="hospice_fraud",
        severity=severity,
        type="STATISTICAL",
        weight=weight,
        description=(
            f"Authorized official {auth_first} {auth_last} received "
            f"${total_payments:,.0f} in industry payments ({payment_count} transactions) "
            f"— potential Anti-Kickback Statute violation"
        ),
        evidence={
            "official": f"{auth_first} {auth_last}",
            "total_payments": round(total_payments, 2),
            "payment_count": payment_count,
            "top_payers": [{"name": p[0], "amount": round(p[1], 2)} for p in top_payers],
        },
        data_source="open_payments",
        fca_provision="31 USC §3729(a)(1)(A) + 42 USC §1320a-7b(b) — kickback-tainted claims",
    ))

    return signals


def _hf15_cost_report_anomalies(entity, db_session) -> list[Signal]:
    """HF15: Cost report anomalies — extreme profit margins or revenue per patient day."""
    signals = []

    cost_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "cost_reports")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()
    ccn = entity.ccn or ""

    for record in cost_records:
        data = record.get_data()
        record_ccn = data.get("ccn", data.get("provider_ccn", ""))
        record_name = (data.get("provider_name", data.get("facility_name", "")) or "").upper()

        matched = False
        if ccn and record_ccn and ccn == record_ccn:
            matched = True
        elif fuzz and entity_name_upper and record_name:
            if fuzz.token_sort_ratio(entity_name_upper, record_name) >= 85:
                matched = True

        if matched:
            profit_margin = _safe_float(data.get("profit_margin", data.get("profit_margin_pct")))
            rev_per_day = _safe_float(data.get("revenue_per_patient_day", data.get("rev_per_patient_day")))

            if profit_margin is not None and profit_margin > 30:
                severity = "CRITICAL" if profit_margin > 50 else "HIGH"
                weight = 9 if profit_margin > 50 else 7
                signals.append(Signal(
                    signal_code="HF15",
                    signal_category="hospice_fraud",
                    severity=severity,
                    type="STATISTICAL",
                    weight=weight,
                    description=(
                        f"Profit margin {profit_margin:.0f}% — far above industry avg of 8-12% "
                        f"(suggests inflated billing or phantom services)"
                    ),
                    evidence={
                        "profit_margin_pct": round(profit_margin, 1),
                        "industry_avg": "8-12%",
                        "total_revenue": data.get("total_revenue"),
                        "total_costs": data.get("total_costs"),
                    },
                    data_source="cost_reports",
                    fca_provision="31 USC §3729(a)(1)(A) — inflated billing or phantom services",
                ))

            if rev_per_day is not None and rev_per_day > 300:
                signals.append(Signal(
                    signal_code="HF15",
                    signal_category="hospice_fraud",
                    severity="HIGH",
                    type="STATISTICAL",
                    weight=7,
                    description=(
                        f"Revenue per patient day ${rev_per_day:,.0f} — "
                        f"above national avg of ~$195 (potential GIP upcoding)"
                    ),
                    evidence={
                        "revenue_per_patient_day": round(rev_per_day, 2),
                        "national_avg": 195,
                        "ratio": round(rev_per_day / 195, 1),
                    },
                    data_source="cost_reports",
                    fca_provision="31 USC §3729(a)(1)(A) — upcoding care levels",
                ))
            break

    return signals


def _hf16_news_coverage(entity, db_session) -> list[Signal]:
    """HF16: Entity appears in fraud-related news coverage."""
    signals = []

    news_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "news_articles")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()
    if not entity_name_upper or len(entity_name_upper) < 5:
        return signals

    matching_articles = []

    for record in news_records:
        data = record.get_data()
        entities_mentioned = data.get("entities_mentioned", [])
        headline = (data.get("headline", "") or "").upper()

        for mentioned in entities_mentioned:
            if not mentioned:
                continue
            mentioned_upper = mentioned.upper()
            score = 0
            if fuzz:
                score = fuzz.token_sort_ratio(entity_name_upper, mentioned_upper)
            elif entity_name_upper in mentioned_upper or mentioned_upper in entity_name_upper:
                score = 85

            if score >= 75:
                matching_articles.append({
                    "headline": data.get("headline", ""),
                    "source": data.get("source", ""),
                    "date": data.get("date", ""),
                    "url": data.get("url", ""),
                    "match_score": score,
                })
                break

    if matching_articles:
        severity = "CRITICAL" if len(matching_articles) >= 3 else "HIGH"
        weight = 9 if len(matching_articles) >= 3 else 7
        signals.append(Signal(
            signal_code="HF16",
            signal_category="hospice_fraud",
            severity=severity,
            type="STATISTICAL",
            weight=weight,
            description=(
                f"Entity mentioned in {len(matching_articles)} fraud-related news article(s): "
                f"{matching_articles[0]['headline'][:80]}"
            ),
            evidence={
                "article_count": len(matching_articles),
                "articles": matching_articles[:5],
            },
            data_source="news_articles",
            fca_provision="31 USC §3729 — media coverage of potential fraud",
        ))

    return signals


def _hf17_sam_exclusion(entity, db_session) -> list[Signal]:
    """HF17: Entity or official on SAM.gov federal exclusion list."""
    signals = []

    sam_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "sam_exclusions")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()
    auth_name = f"{entity.authorized_official_first_name or ''} {entity.authorized_official_last_name or ''}".strip().upper()

    for record in sam_records:
        data = record.get_data()
        sam_name = (data.get("entity_name", data.get("name", "")) or "").upper()

        if not sam_name:
            continue

        # Check entity name
        for check_name, check_type in [(entity_name_upper, "entity"), (auth_name, "authorized_official")]:
            if not check_name or len(check_name) < 3:
                continue

            score = 0
            if fuzz:
                score = fuzz.token_sort_ratio(check_name, sam_name)
            elif check_name in sam_name or sam_name in check_name:
                score = 85

            if score >= 85:
                signals.append(Signal(
                    signal_code="HF17",
                    signal_category="hospice_fraud",
                    severity="CRITICAL",
                    type="RULE_VIOLATION",
                    weight=10,
                    description=(
                        f"SAM.gov exclusion match: {check_type} '{check_name}' matches "
                        f"excluded entity '{sam_name}' (score: {score}%)"
                    ),
                    evidence={
                        "match_type": check_type,
                        "matched_name": check_name,
                        "sam_name": sam_name,
                        "match_score": score,
                        "exclusion_type": data.get("exclusion_type", data.get("classification", "")),
                        "agency": data.get("agency", ""),
                    },
                    data_source="sam_exclusions",
                    fca_provision="31 USC §3729(a)(1)(A) — excluded entity/individual billing federal programs",
                ))
                return signals  # One match is enough

    return signals


def _hf18_sec_filing_flags(entity, db_session) -> list[Signal]:
    """HF18: Parent company SEC filings mention government investigations."""
    signals = []

    sec_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "sec_edgar")
        .all()
    )

    entity_name_upper = (entity.name or "").upper()

    for record in sec_records:
        data = record.get_data()
        company_name = (data.get("company_name", data.get("entity_name", "")) or "").upper()

        # Check if this SEC filing relates to a parent company of this entity
        related = False
        subsidiaries = data.get("subsidiaries", [])
        for sub in subsidiaries:
            if fuzz and fuzz.token_sort_ratio(entity_name_upper, sub.upper()) >= 75:
                related = True
                break

        if not related and fuzz:
            if fuzz.token_sort_ratio(entity_name_upper, company_name) >= 70:
                related = True

        if related:
            risk_factors = data.get("risk_factors", data.get("government_investigation_mentions", []))
            if risk_factors:
                signals.append(Signal(
                    signal_code="HF18",
                    signal_category="hospice_fraud",
                    severity="HIGH",
                    type="STATISTICAL",
                    weight=7,
                    description=(
                        f"Parent company {company_name} SEC filings disclose "
                        f"government investigation risk factors"
                    ),
                    evidence={
                        "parent_company": company_name,
                        "risk_factors": risk_factors[:3] if isinstance(risk_factors, list) else str(risk_factors)[:200],
                        "filing_type": data.get("filing_type", ""),
                    },
                    data_source="sec_edgar",
                    fca_provision="31 USC §3729 — parent company under government scrutiny",
                ))
                break

    return signals


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("%", ""))
    except (ValueError, TypeError):
        return None
