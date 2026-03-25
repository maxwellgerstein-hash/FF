"""
Qui Tam Complaint Outline Drafter.

Auto-generates structured draft complaint outlines and executive summaries
for attorney review. These are NOT filing-ready complaints and are NOT
legal advice. They are structured outlines populated with data from the
fraud detection engine to accelerate attorney intake and case evaluation.

DISCLAIMER: All output is DRAFT material for attorney review only.
"""

import json
from datetime import datetime


def _parse_evidence(sig) -> dict:
    """Safely parse the evidence JSON from a SignalRecord."""
    raw = getattr(sig, "evidence", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_json_field(value) -> list | dict:
    """Safely parse a JSON string field that may be a list or dict."""
    if not value:
        return []
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _format_currency(amount: float | None) -> str:
    """Format a number as USD currency."""
    if amount is None:
        return "[AMOUNT]"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:,.2f} million"
    return f"${amount:,.2f}"


def _format_date(date_str: str | None, fallback: str = "[DATE]") -> str:
    """Format a date string for display."""
    if not date_str:
        return fallback
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%B %d, %Y")
        except (ValueError, TypeError):
            continue
    return fallback


def _severity_to_adjective(severity: str | None) -> str:
    """Map signal severity to descriptive language."""
    mapping = {
        "CRITICAL": "egregious",
        "HIGH": "significant",
        "MEDIUM": "material",
        "LOW": "notable",
    }
    return mapping.get((severity or "").upper(), "material")


def _fca_provision_label(provision: str | None) -> str:
    """Return a human-readable label for an FCA provision code."""
    labels = {
        "3729(a)(1)(A)": "Presenting False Claims (31 U.S.C. \u00a7 3729(a)(1)(A))",
        "3729(a)(1)(B)": "Making False Statements (31 U.S.C. \u00a7 3729(a)(1)(B))",
        "3729(a)(1)(C)": "Conspiracy to Defraud (31 U.S.C. \u00a7 3729(a)(1)(C))",
        "3729(a)(1)(G)": "Reverse False Claims (31 U.S.C. \u00a7 3729(a)(1)(G))",
    }
    if not provision:
        return ""
    for key, label in labels.items():
        if key in provision:
            return label
    return provision


def generate_complaint_draft(entity, lead, signals, cluster=None) -> str:
    """
    Generate a draft qui tam complaint outline.

    This is NOT legal advice and NOT a filing-ready complaint.
    It is a structured outline for attorney review.

    Args:
        entity: Entity ORM object
        lead: CaseLeadRecord ORM object
        signals: list of SignalRecord ORM objects
        cluster: optional CaseCluster ORM object

    Returns:
        Formatted complaint outline as a string.
    """
    entity_name = entity.name or "[ENTITY NAME]"
    ccn = entity.ccn or "[CCN]"
    npi = entity.npi or "[NPI]"
    state = entity.state or "[STATE]"
    city = entity.city or "[CITY]"
    address = entity.address or "[ADDRESS]"
    entity_type = entity.entity_type or "healthcare provider"

    auth_first = entity.authorized_official_first_name or ""
    auth_last = entity.authorized_official_last_name or ""
    auth_official = f"{auth_first} {auth_last}".strip() or "[AUTHORIZED OFFICIAL]"

    fca_provisions = _parse_json_field(getattr(lead, "fca_provisions", None))

    lines = []

    # =================================================================
    # HEADER
    # =================================================================
    lines.append("=" * 72)
    lines.append("DRAFT QUI TAM COMPLAINT OUTLINE")
    lines.append("FOR ATTORNEY REVIEW ONLY - NOT FOR FILING")
    lines.append(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}")
    lines.append("=" * 72)
    lines.append("")

    # =================================================================
    # I. CAPTION
    # =================================================================
    lines.append("I.  CAPTION")
    lines.append("-" * 40)
    lines.append("")
    lines.append("IN THE UNITED STATES DISTRICT COURT")
    lines.append(f"FOR THE [DISTRICT OF {state}]")
    lines.append("")
    lines.append("UNITED STATES OF AMERICA,")
    lines.append("   ex rel. [RELATOR NAME],")
    lines.append("")
    lines.append("        Plaintiff / Relator,")
    lines.append("")
    lines.append("   v.                                    Case No. ____-cv-______")
    lines.append("")
    lines.append(f"   {entity_name.upper()},")
    lines.append("")
    lines.append("        Defendant.")
    lines.append("")
    lines.append("COMPLAINT FOR VIOLATIONS OF THE FEDERAL FALSE CLAIMS ACT")
    lines.append("31 U.S.C. \u00a7\u00a7 3729-3733")
    lines.append("")
    lines.append("(Filed Under Seal Pursuant to 31 U.S.C. \u00a7 3730(b)(2))")
    lines.append("")

    # =================================================================
    # II. JURISDICTION AND VENUE
    # =================================================================
    lines.append("II.  JURISDICTION AND VENUE")
    lines.append("-" * 40)
    lines.append("")
    lines.append(
        "1.  This Court has subject matter jurisdiction over this action "
        "pursuant to 28 U.S.C. \u00a7\u00a7 1331 and 1345, and 31 U.S.C. "
        "\u00a7 3730(b)."
    )
    lines.append("")
    lines.append(
        "2.  This Court has personal jurisdiction over Defendant because "
        f"Defendant conducts business in the State of {state} and the "
        "acts complained of occurred in this judicial district."
    )
    lines.append("")
    lines.append(
        f"3.  Venue is proper in this district pursuant to 28 U.S.C. "
        f"\u00a7 1391(b) and 31 U.S.C. \u00a7 3732(a) because Defendant "
        f"can be found in, resides in, and transacts business in this "
        f"district, and because the acts proscribed by 31 U.S.C. \u00a7 3729 "
        f"occurred in this district."
    )
    lines.append("")

    # =================================================================
    # III. PARTIES
    # =================================================================
    lines.append("III.  PARTIES")
    lines.append("-" * 40)
    lines.append("")
    lines.append(
        "4.  Plaintiff-Relator [RELATOR NAME] is [DESCRIPTION OF RELATOR "
        "AND BASIS OF KNOWLEDGE]. Relator brings this action on behalf of "
        "the United States of America pursuant to 31 U.S.C. \u00a7 3730(b)."
    )
    lines.append("")
    lines.append(
        f"5.  Defendant {entity_name} is a {entity_type} "
        f"located at {address}, {city}, {state}. Defendant operates "
        f"under CMS Certification Number (CCN) {ccn} and National Provider "
        f"Identifier (NPI) {npi}. Defendant's authorized official is "
        f"{auth_official}. Defendant is enrolled as a Medicare-certified "
        f"hospice provider and submits claims for reimbursement to the "
        f"Medicare program administered by the Centers for Medicare & "
        f"Medicaid Services (\"CMS\")."
    )
    lines.append("")

    if cluster:
        cluster_entity_ids = _parse_json_field(getattr(cluster, "entity_ids", None))
        lines.append(
            f"6.  Defendant is part of a cluster of {len(cluster_entity_ids)} "
            f"related entities (\"{cluster.cluster_name}\") with combined "
            f"estimated government losses of "
            f"{_format_currency(cluster.combined_govt_loss)}. "
            f"[COUNSEL: Consider naming additional defendants from the cluster.]"
        )
        lines.append("")

    # =================================================================
    # IV. FACTUAL ALLEGATIONS
    # =================================================================
    lines.append("IV.  FACTUAL ALLEGATIONS")
    lines.append("-" * 40)
    lines.append("")

    # Background
    para_num = 7 if not cluster else 8
    lines.append(f"A.  Background")
    lines.append("")
    lines.append(
        f"{para_num}.  The Medicare hospice benefit, established under "
        f"42 U.S.C. \u00a7 1395d(d), provides coverage for terminally ill "
        f"beneficiaries with a life expectancy of six months or less if the "
        f"illness runs its normal course. Hospice providers are reimbursed "
        f"on a per-diem basis at rates established by CMS, and each claim "
        f"submitted to Medicare constitutes a claim within the meaning of "
        f"the False Claims Act."
    )
    para_num += 1
    lines.append("")
    lines.append(
        f"{para_num}.  Defendant {entity_name} has received an estimated "
        f"{_format_currency(entity.total_govt_payments)} in total Medicare "
        f"payments. The engine's analysis has identified a case score of "
        f"{lead.case_score:.1f}/100 with {lead.confidence:.0%} confidence, "
        f"indicating {_severity_to_adjective(signals[0].severity if signals else None)} "
        f"indicia of fraudulent billing practices."
    )
    para_num += 1
    lines.append("")

    # Specific factual allegations from each signal
    lines.append(f"B.  Specific Fraudulent Conduct")
    lines.append("")

    for sig in signals:
        evidence = _parse_evidence(sig)
        desc = sig.description or "[DESCRIPTION]"
        code = sig.signal_code or "[CODE]"
        severity = sig.severity or "UNKNOWN"
        category = sig.signal_category or "unknown"
        fca_prov = sig.fca_provision or ""

        violation_start = _format_date(
            getattr(sig, "violation_date_start", None), "[START DATE]"
        )
        violation_end = _format_date(
            getattr(sig, "violation_date_end", None), "the present"
        )

        lines.append(
            f"{para_num}.  [{severity} - {category.upper()}] {desc}"
        )
        lines.append("")

        # Evidence details
        if evidence:
            lines.append(
                f"    Supporting evidence (Signal {code}, "
                f"weight {sig.weight}/10, source: {sig.data_source or 'N/A'}):"
            )
            for key, value in evidence.items():
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value, indent=6, default=str)
                else:
                    value_str = str(value)
                display_key = key.replace("_", " ").title()
                lines.append(f"      - {display_key}: {value_str}")
            lines.append("")

        lines.append(
            f"    Violation period: {violation_start} through {violation_end}."
        )
        if fca_prov:
            lines.append(
                f"    Applicable FCA provision: {_fca_provision_label(fca_prov)}."
            )
        lines.append("")

        lines.append(
            f"{para_num + 1}.  Defendant's conduct described in paragraph "
            f"{para_num} above demonstrates knowing submission of false or "
            f"fraudulent claims to the Medicare program. Defendant either "
            f"had actual knowledge that the claims were false, acted in "
            f"deliberate ignorance of the truth or falsity of the claims, "
            f"or acted in reckless disregard of the truth or falsity of the "
            f"claims. 31 U.S.C. \u00a7 3729(b)(1)."
        )
        lines.append("")
        para_num += 2

    # =================================================================
    # V. FCA COUNTS
    # =================================================================
    lines.append("V.  COUNTS")
    lines.append("-" * 40)
    lines.append("")

    count_num = 1

    # Count I: Presenting False Claims -- always included
    lines.append(f"COUNT {_roman(count_num)}")
    lines.append("Presenting False or Fraudulent Claims")
    lines.append("31 U.S.C. \u00a7 3729(a)(1)(A)")
    lines.append("")
    lines.append(
        f"{para_num}.  Relator re-alleges and incorporates by reference "
        f"each of the preceding paragraphs as if fully set forth herein."
    )
    para_num += 1
    lines.append("")
    lines.append(
        f"{para_num}.  Defendant knowingly presented, or caused to be "
        f"presented, false or fraudulent claims for payment or approval "
        f"to the United States, in violation of 31 U.S.C. "
        f"\u00a7 3729(a)(1)(A)."
    )
    para_num += 1
    lines.append("")
    est_claims = lead.estimated_claim_count or "[NUMBER]"
    lines.append(
        f"{para_num}.  Upon information and belief, Defendant submitted "
        f"approximately {est_claims} false claims during the relevant "
        f"period, resulting in estimated government losses of "
        f"{_format_currency(lead.estimated_govt_loss)}."
    )
    para_num += 1
    lines.append("")
    count_num += 1

    # Count II: False Statements -- if applicable
    has_false_statements = any(
        "3729(a)(1)(B)" in (p or "") for p in fca_provisions
    ) or any(
        "3729(a)(1)(B)" in (getattr(s, "fca_provision", "") or "")
        for s in signals
    )
    if has_false_statements:
        lines.append(f"COUNT {_roman(count_num)}")
        lines.append("Making or Using False Records or Statements")
        lines.append("31 U.S.C. \u00a7 3729(a)(1)(B)")
        lines.append("")
        lines.append(
            f"{para_num}.  Relator re-alleges and incorporates by reference "
            f"each of the preceding paragraphs as if fully set forth herein."
        )
        para_num += 1
        lines.append("")
        lines.append(
            f"{para_num}.  Defendant knowingly made, used, or caused to be "
            f"made or used, false records or statements material to false or "
            f"fraudulent claims, in violation of 31 U.S.C. "
            f"\u00a7 3729(a)(1)(B)."
        )
        para_num += 1
        lines.append("")
        count_num += 1

    # Count III: Reverse False Claims -- if overpayment retention evidence
    has_reverse = any(
        "3729(a)(1)(G)" in (p or "") for p in fca_provisions
    ) or any(
        "3729(a)(1)(G)" in (getattr(s, "fca_provision", "") or "")
        for s in signals
    )
    if has_reverse:
        lines.append(f"COUNT {_roman(count_num)}")
        lines.append("Retention of Overpayments (Reverse False Claims)")
        lines.append("31 U.S.C. \u00a7 3729(a)(1)(G)")
        lines.append("")
        lines.append(
            f"{para_num}.  Relator re-alleges and incorporates by reference "
            f"each of the preceding paragraphs as if fully set forth herein."
        )
        para_num += 1
        lines.append("")
        lines.append(
            f"{para_num}.  Defendant knowingly concealed or knowingly and "
            f"improperly avoided or decreased an obligation to pay or "
            f"transmit money or property to the United States, in violation "
            f"of 31 U.S.C. \u00a7 3729(a)(1)(G). Specifically, Defendant "
            f"retained Medicare overpayments that it was obligated to report "
            f"and return pursuant to 42 U.S.C. \u00a7 1320a-7k(d) (the "
            f"\"60-day rule\")."
        )
        para_num += 1
        lines.append("")
        count_num += 1

    # =================================================================
    # VI. DAMAGES
    # =================================================================
    lines.append("VI.  DAMAGES")
    lines.append("-" * 40)
    lines.append("")
    lines.append(
        f"{para_num}.  As a direct and proximate result of Defendant's "
        f"violations of the False Claims Act, the United States has "
        f"suffered damages in an amount to be determined at trial, but "
        f"estimated as follows based on available data:"
    )
    para_num += 1
    lines.append("")
    lines.append(
        f"    a.  Estimated government loss: "
        f"{_format_currency(lead.estimated_govt_loss)}"
    )
    lines.append(
        f"    b.  Treble damages (31 U.S.C. \u00a7 3729(a)(1)): "
        f"{_format_currency(lead.treble_damages)}"
    )
    lines.append(
        f"    c.  Double damages (if cooperation credit applies): "
        f"{_format_currency(lead.double_damages)}"
    )

    penalties_low_str = _format_currency(lead.penalties_low)
    penalties_high_str = _format_currency(lead.penalties_high)
    lines.append(
        f"    d.  Civil penalties ($13,946 to $27,894 per false claim, "
        f"adjusted for inflation): {penalties_low_str} to {penalties_high_str} "
        f"(based on approximately {lead.estimated_claim_count or '[N]'} claims)"
    )
    lines.append(
        f"    e.  Total estimated recovery range: "
        f"{_format_currency(lead.total_recovery_low)} to "
        f"{_format_currency(lead.total_recovery_high)}"
    )
    lines.append("")

    # =================================================================
    # VII. PRAYER FOR RELIEF
    # =================================================================
    lines.append("VII.  PRAYER FOR RELIEF")
    lines.append("-" * 40)
    lines.append("")
    lines.append(
        f"{para_num}.  WHEREFORE, Relator, on behalf of the United States "
        f"of America, respectfully requests that this Court enter judgment "
        f"against Defendant and grant the following relief:"
    )
    para_num += 1
    lines.append("")
    lines.append(
        f"    a.  Treble damages in an amount equal to three times the "
        f"amount of damages sustained by the United States, estimated at "
        f"{_format_currency(lead.treble_damages)}, pursuant to "
        f"31 U.S.C. \u00a7 3729(a)(1);"
    )
    lines.append("")
    lines.append(
        f"    b.  Civil penalties of not less than $13,946 and not more "
        f"than $27,894 for each false claim submitted, for total penalties "
        f"estimated between {penalties_low_str} and {penalties_high_str};"
    )
    lines.append("")
    lines.append(
        f"    c.  An award to Relator of the maximum percentage allowed "
        f"under 31 U.S.C. \u00a7 3730(d), estimated between "
        f"{_format_currency(lead.relator_share_low)} and "
        f"{_format_currency(lead.relator_share_high)};"
    )
    lines.append("")
    lines.append(
        "    d.  Relator's reasonable attorneys' fees, costs, and expenses "
        "pursuant to 31 U.S.C. \u00a7 3730(d);"
    )
    lines.append("")
    lines.append("    e.  Such other and further relief as this Court deems just and proper.")
    lines.append("")

    # =================================================================
    # VIII. VERIFICATION
    # =================================================================
    lines.append("VIII.  VERIFICATION")
    lines.append("-" * 40)
    lines.append("")
    lines.append(
        "I, [RELATOR NAME], declare under penalty of perjury pursuant to "
        "28 U.S.C. \u00a7 1746 that the foregoing is true and correct to "
        "the best of my knowledge, information, and belief."
    )
    lines.append("")
    lines.append(f"Dated: _______________")
    lines.append("")
    lines.append("")
    lines.append("___________________________________")
    lines.append("[RELATOR NAME]")
    lines.append("")
    lines.append("")
    lines.append("Respectfully submitted,")
    lines.append("")
    lines.append("___________________________________")
    lines.append("[ATTORNEY NAME]")
    lines.append("[BAR NUMBER]")
    lines.append("[FIRM NAME]")
    lines.append("[ADDRESS]")
    lines.append("[TELEPHONE]")
    lines.append("[EMAIL]")
    lines.append("Counsel for Plaintiff-Relator")
    lines.append("")
    lines.append("")
    lines.append("=" * 72)
    lines.append("DRAFT - FOR ATTORNEY REVIEW ONLY - NOT FOR FILING")
    lines.append(
        "This outline was auto-generated by the Qui Tam Case Engine and "
        "must be reviewed, verified, and substantially revised by qualified "
        "counsel before any filing. It does not constitute legal advice."
    )
    lines.append("=" * 72)

    return "\n".join(lines)


def _roman(n: int) -> str:
    """Convert a small integer to a Roman numeral string."""
    vals = [
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = ""
    for value, numeral in vals:
        while n >= value:
            result += numeral
            n -= value
    return result


def generate_case_summary(entity, lead, signals) -> str:
    """
    Generate a 1-page executive summary for attorney intake.

    Args:
        entity: Entity ORM object
        lead: CaseLeadRecord ORM object
        signals: list of SignalRecord ORM objects

    Returns:
        Formatted executive summary as a string.
    """
    entity_name = entity.name or "[ENTITY NAME]"
    ccn = entity.ccn or "[CCN]"
    npi = entity.npi or "[NPI]"
    state = entity.state or "[STATE]"
    city = entity.city or "[CITY]"
    address = entity.address or "[ADDRESS]"

    auth_first = entity.authorized_official_first_name or ""
    auth_last = entity.authorized_official_last_name or ""
    auth_official = f"{auth_first} {auth_last}".strip() or "N/A"

    fca_provisions = _parse_json_field(getattr(lead, "fca_provisions", None))

    lines = []

    lines.append("=" * 72)
    lines.append("QUI TAM CASE LEAD - EXECUTIVE SUMMARY")
    lines.append("PRIVILEGED AND CONFIDENTIAL - FOR ATTORNEY REVIEW ONLY")
    lines.append(f"Generated: {datetime.now().strftime('%B %d, %Y')}")
    lines.append("=" * 72)
    lines.append("")

    # ---- Entity identification ----
    lines.append("SUBJECT ENTITY")
    lines.append(f"  Name:                {entity_name}")
    lines.append(f"  CCN:                 {ccn}")
    lines.append(f"  NPI:                 {npi}")
    lines.append(f"  Address:             {address}, {city}, {state}")
    lines.append(f"  Authorized Official: {auth_official}")
    lines.append(f"  Entity Type:         {entity.entity_type or 'N/A'}")
    lines.append("")

    # ---- Case metrics ----
    lines.append("CASE METRICS")
    lines.append(f"  Case Score:          {lead.case_score:.1f} / 100")
    lines.append(f"  Confidence:          {lead.confidence:.0%}")
    lines.append(f"  Fraud Category:      {lead.fraud_category or 'N/A'}")
    lines.append(f"  Signal Count:        {len(signals)}")
    lines.append(f"  Est. Govt Loss:      {_format_currency(lead.estimated_govt_loss)}")
    lines.append(f"  Est. Claim Count:    {lead.estimated_claim_count or 'N/A'}")
    lines.append("")

    # ---- Recovery estimate ----
    lines.append("RECOVERY ESTIMATE")
    lines.append(
        f"  Treble Damages:      {_format_currency(lead.treble_damages)}"
    )
    lines.append(
        f"  Per-Claim Penalties: {_format_currency(lead.penalties_low)} - "
        f"{_format_currency(lead.penalties_high)}"
    )
    lines.append(
        f"  Total Recovery:      {_format_currency(lead.total_recovery_low)} - "
        f"{_format_currency(lead.total_recovery_high)}"
    )
    lines.append(
        f"  Relator Share:       {_format_currency(lead.relator_share_low)} - "
        f"{_format_currency(lead.relator_share_high)}"
    )
    lines.append("")

    # ---- Legal assessment ----
    lines.append("LEGAL ASSESSMENT")
    lines.append(f"  FCA Provisions:            {', '.join(fca_provisions) if fca_provisions else 'N/A'}")
    lines.append(f"  Public Disclosure Risk:    {lead.public_disclosure_risk or 'N/A'}")
    lines.append(f"  First-to-File Risk:        {lead.first_to_file_risk or 'N/A'}")
    lines.append(f"  Rule 9(b) Sufficiency:     {lead.rule_9b_sufficiency or 'N/A'}")
    lines.append(f"  DOJ Intervention Likely:   {lead.doj_intervention_likelihood or 'N/A'}")
    lines.append(f"  SOL Expiry:                {_format_date(lead.sol_expiry, 'N/A')}")
    lines.append(f"  Recommended Counsel:       {lead.recommended_counsel_type or 'N/A'}")
    lines.append("")

    # ---- Signal summary ----
    lines.append("SIGNALS DETECTED")
    lines.append("-" * 40)

    for i, sig in enumerate(signals, start=1):
        severity = sig.severity or "UNKNOWN"
        desc = sig.description or "[No description]"
        code = sig.signal_code or ""
        evidence = _parse_evidence(sig)

        lines.append(f"  {i}. [{severity}] {code}")
        lines.append(f"     {desc}")

        # Show key evidence metrics (up to 3 items to keep it concise)
        evidence_items = list(evidence.items())[:3]
        for key, value in evidence_items:
            display_key = key.replace("_", " ").title()
            if isinstance(value, float):
                value_str = f"{value:.2f}"
            elif isinstance(value, (dict, list)):
                value_str = json.dumps(value, default=str)
            else:
                value_str = str(value)
            lines.append(f"     {display_key}: {value_str}")

        v_start = _format_date(getattr(sig, "violation_date_start", None), "N/A")
        v_end = _format_date(getattr(sig, "violation_date_end", None), "present")
        lines.append(f"     Period: {v_start} - {v_end}")
        lines.append("")

    # ---- Legal theory ----
    if lead.legal_theory:
        lines.append("LEGAL THEORY")
        lines.append("-" * 40)
        lines.append(f"  {lead.legal_theory}")
        lines.append("")

    # ---- Recommended next steps ----
    lines.append("RECOMMENDED NEXT STEPS")
    lines.append("-" * 40)
    lines.append("  1. Attorney review of signal evidence and legal theory")
    lines.append("  2. FOIA request to CMS for claims data and survey records")
    lines.append("  3. Relator interview and independent knowledge assessment")
    lines.append("  4. Public disclosure bar / first-to-file search")

    sol_str = _format_date(lead.sol_expiry)
    if sol_str != "[DATE]":
        lines.append(f"  5. URGENT: SOL expires {sol_str} - prioritize filing decision")

    lines.append("")
    lines.append("=" * 72)
    lines.append("DRAFT - FOR ATTORNEY REVIEW ONLY")
    lines.append("=" * 72)

    return "\n".join(lines)
