"""
FOIA Request Letter Generator for Qui Tam Case Engine.

Auto-generates Freedom of Information Act request letters targeting CMS records
for entities flagged by the fraud detection pipeline. Letters are formatted for
printing and mailing to the CMS FOIA Group.

DISCLAIMER: Generated letters are drafts for attorney review only.
"""

import json
from datetime import datetime, timedelta


def _parse_date(date_str: str | None) -> datetime | None:
    """Attempt to parse an ISO-format date string."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _format_date(date_str: str | None, fallback: str = "[DATE]") -> str:
    """Format a date string for display, returning a placeholder on failure."""
    dt = _parse_date(date_str)
    if dt:
        return dt.strftime("%B %d, %Y")
    return fallback


def _format_currency(amount: float | None) -> str:
    """Format a number as USD currency."""
    if amount is None:
        return "[AMOUNT]"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:,.2f} million"
    if amount >= 1_000:
        return f"${amount:,.2f}"
    return f"${amount:,.2f}"


def _compute_date_range(signals) -> tuple[str, str]:
    """
    Derive the earliest violation start and latest violation end from signals.
    Returns (start_display, end_display) strings.
    """
    starts = []
    ends = []
    for sig in signals:
        s = _parse_date(getattr(sig, "violation_date_start", None))
        e = _parse_date(getattr(sig, "violation_date_end", None))
        if s:
            starts.append(s)
        if e:
            ends.append(e)

    if starts:
        earliest = min(starts)
        start_str = earliest.strftime("%B %d, %Y")
    else:
        start_str = "[START DATE]"

    if ends:
        latest = max(ends)
        end_str = latest.strftime("%B %d, %Y")
    else:
        end_str = "the present"

    return start_str, end_str


def _sol_is_close(lead) -> bool:
    """Determine if the statute of limitations expiry is within 6 months."""
    sol = _parse_date(getattr(lead, "sol_expiry", None))
    if not sol:
        return False
    return sol - datetime.now() < timedelta(days=180)


def generate_foia_request(entity, lead, signals) -> str:
    """
    Generate a complete FOIA request letter for a specific entity.

    Args:
        entity: Entity ORM object
        lead: CaseLeadRecord ORM object
        signals: list of SignalRecord ORM objects

    Returns:
        Complete FOIA request letter as a string (plain text, formatted for
        printing).
    """
    today_str = datetime.now().strftime("%B %d, %Y")
    entity_name = entity.name or "[ENTITY NAME]"
    ccn = entity.ccn or "[CCN]"
    npi = entity.npi or "[NPI]"
    state = entity.state or "[STATE]"
    city = entity.city or "[CITY]"
    address = entity.address or "[ADDRESS]"

    date_start, date_end = _compute_date_range(signals)

    # Build the signal-specific records description
    signal_categories = set()
    for sig in signals:
        cat = getattr(sig, "signal_category", None)
        if cat:
            signal_categories.add(cat)

    additional_record_requests = []
    for sig in signals:
        code = getattr(sig, "signal_code", "") or ""
        desc = getattr(sig, "description", "") or ""
        # Add targeted requests based on signal type
        if "live_discharge" in code.lower() or "discharge" in desc.lower():
            additional_record_requests.append(
                "Live discharge records, including discharge status codes and "
                "any associated revocation or election termination documentation"
            )
        if "gip" in code.lower() or "general inpatient" in desc.lower():
            additional_record_requests.append(
                "General Inpatient Care (GIP) level-of-care certifications, "
                "attending physician orders, and related clinical documentation "
                "justifying GIP-level reimbursement"
            )
        if "continuous" in code.lower() or "continuous" in desc.lower():
            additional_record_requests.append(
                "Continuous Home Care (CHC) nursing logs, hour-by-hour care "
                "records, and crisis documentation supporting CHC billing"
            )
        if "cap" in code.lower() or "cap" in desc.lower():
            additional_record_requests.append(
                "Hospice aggregate cap calculations and any cap overpayment "
                "demand letters or offset notices"
            )
        if "leie" in code.lower() or "exclusion" in desc.lower():
            additional_record_requests.append(
                "Records of any excluded individual screening results and "
                "OIG exclusion verification checks performed by the provider"
            )

    # Deduplicate
    additional_record_requests = list(dict.fromkeys(additional_record_requests))

    # Determine if expedited processing is warranted
    expedited = _sol_is_close(lead)

    # -----------------------------------------------------------------
    # Compose the letter
    # -----------------------------------------------------------------
    lines = []

    lines.append(f"{today_str}")
    lines.append("")
    lines.append("VIA U.S. MAIL")
    lines.append("")
    lines.append("CMS Freedom of Information Group")
    lines.append("Office of Strategic Operations and Regulatory Affairs")
    lines.append("Centers for Medicare & Medicaid Services")
    lines.append("7500 Security Boulevard")
    lines.append("Baltimore, MD 21244-1850")
    lines.append("")
    lines.append("Re: Freedom of Information Act Request")
    lines.append(f"    Provider: {entity_name}")
    lines.append(f"    CMS Certification Number (CCN): {ccn}")
    lines.append(f"    National Provider Identifier (NPI): {npi}")
    lines.append(f"    Location: {city}, {state}")
    lines.append("")
    lines.append("Dear FOIA Officer:")
    lines.append("")
    lines.append(
        "Pursuant to the Freedom of Information Act, 5 U.S.C. \u00a7 552, "
        "and the implementing regulations at 45 C.F.R. Part 5, I hereby "
        "request copies of the following records pertaining to the above-"
        "referenced Medicare-certified hospice provider:"
    )
    lines.append("")

    # ---- Category 1: Claims data ----
    lines.append("1.  MEDICARE HOSPICE CLAIMS DATA")
    lines.append("")
    lines.append(
        f"    All Medicare hospice claims (Form CMS-1450 / UB-04) submitted by "
        f"{entity_name}, CCN {ccn}, for the period {date_start} through "
        f"{date_end}, including but not limited to:"
    )
    lines.append("")
    lines.append(
        "    a.  Primary and secondary diagnosis codes (ICD-10-CM) for each "
        "claim and each beneficiary episode;"
    )
    lines.append(
        "    b.  Dates of service, including election dates, certification "
        "periods, and discharge or revocation dates;"
    )
    lines.append(
        "    c.  Level of care billed for each service day (routine home care, "
        "continuous home care, general inpatient care, and inpatient respite care);"
    )
    lines.append(
        "    d.  Payment amounts, including per-diem rates and any adjustments, "
        "sequestration reductions, or recoupments;"
    )
    lines.append(
        "    e.  Beneficiary ZIP codes (de-identified to the extent required "
        "by the Privacy Act and HIPAA, e.g., first three digits only);"
    )
    lines.append(
        "    f.  Revenue codes, condition codes, occurrence codes, and value "
        "codes associated with each claim."
    )
    lines.append("")

    # ---- Category 2: Compliance / survey ----
    lines.append("2.  COMPLIANCE AND SURVEY RECORDS")
    lines.append("")
    lines.append(
        f"    All compliance reviews, state survey agency inspection reports, "
        f"complaint investigation results, and any Conditions of Participation "
        f"deficiency findings for {entity_name}, CCN {ccn}, from {date_start} "
        f"through {date_end}."
    )
    lines.append("")

    # ---- Category 3: MAC correspondence ----
    lines.append("3.  MEDICARE ADMINISTRATIVE CONTRACTOR CORRESPONDENCE")
    lines.append("")
    lines.append(
        f"    All correspondence between CMS (or the applicable Medicare "
        f"Administrative Contractor) and {entity_name} regarding claims "
        f"denials, Additional Documentation Requests (ADRs), Targeted Probe "
        f"and Educate (TPE) reviews, overpayment demands, or extrapolated "
        f"audit findings."
    )
    lines.append("")

    # ---- Category 4: Signal-specific requests ----
    if additional_record_requests:
        lines.append("4.  ADDITIONAL TARGETED RECORDS")
        lines.append("")
        for idx, req in enumerate(additional_record_requests, start=1):
            letter = chr(ord("a") + idx - 1) if idx <= 26 else str(idx)
            lines.append(f"    {letter}.  {req}.")
        lines.append("")

    # ---- Fee waiver ----
    lines.append("FEE WAIVER REQUEST")
    lines.append("")
    lines.append(
        "I request a waiver of all fees associated with this request pursuant "
        "to 5 U.S.C. \u00a7 552(a)(4)(A)(iii). Disclosure of the requested "
        "records is in the public interest because it is likely to contribute "
        "significantly to public understanding of the operations and activities "
        "of the federal government, specifically the integrity of the Medicare "
        "hospice benefit program and the use of taxpayer funds. The information "
        "is not primarily in my commercial interest. The requested records will "
        "be used to evaluate potential fraud, waste, and abuse in the Medicare "
        "hospice program, which directly serves the public interest in "
        "safeguarding federal healthcare expenditures."
    )
    lines.append("")

    # ---- Expedited processing (if SOL is close) ----
    if expedited:
        sol_date = _format_date(getattr(lead, "sol_expiry", None), "[SOL DATE]")
        lines.append("REQUEST FOR EXPEDITED PROCESSING")
        lines.append("")
        lines.append(
            "I request expedited processing of this FOIA request pursuant to "
            "5 U.S.C. \u00a7 552(a)(6)(E). There is an urgency to inform the "
            "public about actual or alleged federal government activity. "
            f"Specifically, the applicable statute of limitations for potential "
            f"False Claims Act claims related to this provider may expire on or "
            f"about {sol_date}. Delay in processing this request may result in "
            f"the permanent loss of the government's ability to recover "
            f"potentially fraudulent Medicare payments. I certify that this "
            f"statement is true and correct to the best of my knowledge and "
            f"belief."
        )
        lines.append("")

    # ---- Format / delivery ----
    lines.append("FORMAT AND DELIVERY")
    lines.append("")
    lines.append(
        "I request that responsive records be provided in electronic format "
        "(CD-ROM, USB drive, or secure electronic transmission) where available. "
        "For claims data, delimited text files (CSV) or SAS/Excel format is "
        "preferred. If electronic production is not feasible, paper copies are "
        "acceptable."
    )
    lines.append("")

    # ---- Closing ----
    lines.append(
        "If this request is denied in whole or in part, I request that you "
        "identify each record or portion thereof withheld and the specific "
        "FOIA exemption(s) relied upon for each withholding, as required by "
        "5 U.S.C. \u00a7 552(a)(6)(A)(i)."
    )
    lines.append("")
    lines.append(
        "If you have any questions regarding this request, please contact me "
        "at the address or telephone number below. I look forward to your "
        "response within the twenty (20) business day period mandated by "
        "5 U.S.C. \u00a7 552(a)(6)(A)(i)."
    )
    lines.append("")
    lines.append("Respectfully submitted,")
    lines.append("")
    lines.append("")
    lines.append("___________________________________")
    lines.append("[REQUESTOR NAME]")
    lines.append("[ADDRESS]")
    lines.append("[CITY, STATE ZIP]")
    lines.append("[TELEPHONE]")
    lines.append("[EMAIL]")
    lines.append("")
    lines.append("")
    lines.append(
        "--- DRAFT - FOR ATTORNEY REVIEW ONLY - NOT FOR FILING ---"
    )

    return "\n".join(lines)
