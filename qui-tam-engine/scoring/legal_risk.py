"""
Legal Risk Assessment Layer.

Every case lead gets assessed for:
  1. Public Disclosure Bar (31 USC 3730(e)(4))
  2. Rule 9(b) Sufficiency
  3. Statute of Limitations (31 USC 3731(b))
  4. DOJ Intervention Likelihood
"""

from datetime import datetime, timedelta, date
from detection.base import Signal
from config import OIG_WORK_PLAN_PRIORITIES


def assess_public_disclosure_risk(signals: list[Signal]) -> tuple[str, str]:
    """
    Assess public disclosure bar risk.

    CAVEAT: Whether algorithmic cross-referencing of multiple public data
    sources qualifies as "original source" is NOT settled law.
    """
    sources = set(s.data_source for s in signals)

    if len(sources) >= 4:
        risk = "LOW"
        explanation = (
            f"Case theory cross-references {len(sources)} independent data sources "
            f"({', '.join(sources)}). This provides the strongest available 'original "
            f"source' argument for a data-mining relator. CAVEAT: Whether multi-source "
            f"algorithmic analysis defeats the PD bar is unsettled. The Sidesolve PPP "
            f"cases settled before this was tested in court. Consult counsel on PD bar "
            f"strategy before filing."
        )
    elif len(sources) >= 2:
        risk = "MEDIUM"
        explanation = (
            f"Case relies on {len(sources)} data sources. Cross-source analysis "
            f"provides some original source argument, but a defendant may argue "
            f"the fraud was ascertainable from any single source. Consider "
            f"supplementing with FOIA requests or field investigation."
        )
    else:
        source_name = list(sources)[0] if sources else "unknown"
        risk = "HIGH"
        explanation = (
            f"Case relies on a single public data source ({source_name}). "
            f"High risk of public disclosure bar. Courts (5th Cir., 9th Cir.) have "
            f"rejected data-mining complaints from single public sources. STRONGLY "
            f"recommend supplementing with FOIA requests, site visits, or insider "
            f"information before filing."
        )

    return risk, explanation


def assess_rule_9b(signals: list[Signal]) -> tuple[str, str]:
    """
    Assess Rule 9(b) sufficiency.

    Fed. R. Civ. P. 9(b) requires fraud allegations be stated with
    "particularity" — who, what, when, where, how.
    """
    rule_violations = [s for s in signals if s.type == "RULE_VIOLATION"]
    has_specific_dates = any(s.violation_date_start is not None for s in signals)
    has_specific_amounts = any("amount" in str(s.evidence) for s in signals)

    if len(rule_violations) >= 2 and has_specific_amounts and has_specific_dates:
        return "STRONG", (
            "Case includes specific rule violations with quantified amounts and "
            "date ranges. Satisfies Rule 9(b) by identifying the who (entity), "
            "what (specific rule violated), when (date range of conduct), where "
            "(address/NPI), and how (specific false certification or claim)."
        )
    elif len(rule_violations) >= 1:
        return "MODERATE", (
            "Case includes at least one rule violation but may need supplemental "
            "factual allegations (specific false claim examples, dates, amounts) "
            "to survive a 9(b) motion."
        )
    else:
        return "WEAK", (
            "Case relies primarily on statistical anomalies. Per Integra Med "
            "Analytics (5th & 9th Cir.), this is insufficient for 9(b). "
            "RECOMMEND: Supplement with FOIA for specific claim data, conduct "
            "physical site visit, or obtain insider information before filing."
        )


def calculate_sol(signals: list[Signal]) -> tuple[date | None, str]:
    """
    Calculate statute of limitations.

    FCA SOL: 6 years from date of violation OR 3 years from when the
    government knew/should have known (max 10 years from violation).
    31 USC 3731(b).
    """
    violation_dates = [
        s.violation_date_start for s in signals if s.violation_date_start
    ]

    if not violation_dates:
        return None, "SOL cannot be calculated \u2014 violation dates not available in source data."

    earliest_violation = min(violation_dates)
    latest_violation = max(
        s.violation_date_end or s.violation_date_start
        for s in signals
        if s.violation_date_start
    )

    # Standard: 6 years from LATEST violation
    sol_standard = latest_violation + timedelta(days=6 * 365)

    # Extended: 3 years from discovery (for data mining, discovery ~ now)
    sol_extended = date.today() + timedelta(days=3 * 365)

    # Cap at 10 years from EARLIEST violation
    sol_max = earliest_violation + timedelta(days=10 * 365)

    sol_expiry = min(max(sol_standard, sol_extended), sol_max)

    urgency = ""
    if sol_expiry < date.today() + timedelta(days=365):
        urgency = "SOL EXPIRING WITHIN 12 MONTHS \u2014 file promptly."
    elif sol_expiry < date.today() + timedelta(days=2 * 365):
        urgency = "SOL expiring within 24 months \u2014 prioritize."

    return sol_expiry, urgency


def assess_doj_intervention(signals: list[Signal]) -> tuple[str, str]:
    """
    Assess DOJ intervention likelihood.

    DOJ intervention: ~95% success rate vs ~25% without.
    """
    category = signals[0].signal_category if signals else "unknown"

    if category in OIG_WORK_PLAN_PRIORITIES:
        return "HIGH", (
            f"This fraud category ({category}) is listed in the current OIG Work Plan "
            f"as an active investigation priority. DOJ is actively seeking these cases. "
            f"High likelihood of intervention if evidence is strong."
        )
    elif category in ("ppp_fraud", "cybersecurity_false_cert", "customs_fraud"):
        return "MEDIUM", (
            f"This fraud category ({category}) aligns with recent DOJ enforcement "
            f"initiatives (Civil Cyber-Fraud, PPP Fraud Strike Force, Trade Compliance). "
            f"Moderate intervention likelihood."
        )
    else:
        return "LOW", (
            f"This fraud category ({category}) is not a current DOJ/OIG priority. "
            f"Lower intervention likelihood \u2014 but declined cases still produced "
            f"$2.2B in FY2025 recoveries. Case may still be viable."
        )
