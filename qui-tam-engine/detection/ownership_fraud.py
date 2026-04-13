"""
Ownership & Corporate Structure Fraud Signals (OF01–OF04).

Detects shell company patterns, revolving door officials,
rapid ownership changes, and related party transactions.
"""

import json
from datetime import date, datetime
from detection.base import Signal
from db.models import Entity, SourceRecord

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


def detect_ownership_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """Run ownership fraud detection signals."""
    signals = []

    signals.extend(_of01_shell_company(entity, db_session))
    signals.extend(_of02_revolving_door(entity, db_session))
    signals.extend(_of03_multi_entity_official(entity, db_session))
    signals.extend(_of04_related_party(entity, db_session))

    return signals


def _of01_shell_company(entity, db_session) -> list[Signal]:
    """OF01: Shell company pattern — PO Box/virtual + newly certified + high volume."""
    signals = []

    is_virtual = entity.is_virtual_office or 0
    is_po_box = False
    address_upper = (entity.address or "").upper()
    if "P.O. BOX" in address_upper or "PO BOX" in address_upper or "PMB" in address_upper:
        is_po_box = True

    cert_date = _parse_date(entity.certification_date)
    if cert_date:
        months_since = (date.today() - cert_date).days / 30
    else:
        months_since = None

    episodes = entity.total_episodes or 0

    # Shell company = virtual/PO box + new + high volume
    if (is_virtual or is_po_box) and months_since is not None and months_since < 24 and episodes > 50:
        signals.append(Signal(
            signal_code="OF01",
            signal_category="ownership_fraud",
            severity="CRITICAL",
            type="RULE_VIOLATION",
            weight=9,
            description=(
                f"Shell company pattern: {'virtual office' if is_virtual else 'PO Box'} address, "
                f"certified {months_since:.0f} months ago, {episodes} episodes — "
                f"classic hospice fraud startup pattern"
            ),
            evidence={
                "address_type": "virtual_office" if is_virtual else "po_box",
                "address": entity.address,
                "months_since_cert": round(months_since) if months_since else None,
                "total_episodes": episodes,
            },
            data_source="cms_hospice_general + nppes_bulk",
            fca_provision="31 USC §3729(a)(1)(A) — fraudulent shell entity billing Medicare",
            violation_date_start=cert_date,
            violation_date_end=date.today(),
        ))

    return signals


def _of02_revolving_door(entity, db_session) -> list[Signal]:
    """OF02: Official previously associated with a DOJ settlement or news investigation."""
    signals = []

    auth_first = (entity.authorized_official_first_name or "").upper().strip()
    auth_last = (entity.authorized_official_last_name or "").upper().strip()

    if not auth_last or len(auth_last) < 2:
        return signals

    auth_name = f"{auth_first} {auth_last}"

    # Check DOJ settlements for official name
    doj_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "doj_settlement")
        .all()
    )

    for record in doj_records:
        data = record.get_data()
        individuals = data.get("individuals_named", data.get("defendants", []))
        if isinstance(individuals, str):
            individuals = [individuals]

        for individual in individuals:
            if not individual:
                continue
            ind_upper = individual.upper()
            if auth_last in ind_upper:
                score = 0
                if fuzz:
                    score = fuzz.token_sort_ratio(auth_name, ind_upper)
                elif auth_last in ind_upper:
                    score = 80

                if score >= 75:
                    signals.append(Signal(
                        signal_code="OF02",
                        signal_category="ownership_fraud",
                        severity="HIGH",
                        type="STATISTICAL",
                        weight=8,
                        description=(
                            f"Authorized official '{auth_name}' matches individual "
                            f"named in DOJ settlement: '{individual}' (match: {score}%)"
                        ),
                        evidence={
                            "official": auth_name,
                            "doj_individual": individual,
                            "match_score": score,
                            "case": data.get("entity_name", data.get("case_name", "")),
                            "settlement_amount": data.get("settlement_amount", ""),
                        },
                        data_source="doj_settlement + nppes_bulk",
                        fca_provision="31 USC §3729 — official with prior FCA enforcement history",
                    ))
                    return signals

    return signals


def _of03_multi_entity_official(entity, db_session) -> list[Signal]:
    """OF03: Official controls entities in multiple states (cross-state franchise fraud)."""
    signals = []

    auth_last = (entity.authorized_official_last_name or "").upper().strip()
    auth_first = (entity.authorized_official_first_name or "").upper().strip()

    if not auth_last or len(auth_last) < 2:
        return signals

    # Find other entities with same official in different states
    all_entities = db_session.query(Entity).filter(Entity.id != entity.id).all()

    other_state_entities = []
    for other in all_entities:
        other_last = (other.authorized_official_last_name or "").upper().strip()
        other_first = (other.authorized_official_first_name or "").upper().strip()

        if other_last == auth_last and other_first[:2] == auth_first[:2]:
            if other.state and entity.state and other.state != entity.state:
                other_state_entities.append(other)

    if len(other_state_entities) >= 1:
        states = list(set([entity.state] + [e.state for e in other_state_entities]))
        signals.append(Signal(
            signal_code="OF03",
            signal_category="ownership_fraud",
            severity="HIGH",
            type="STATISTICAL",
            weight=7,
            description=(
                f"Official '{auth_first} {auth_last}' controls hospices in "
                f"{len(states)} states: {', '.join(sorted(states))} — "
                f"cross-state franchise pattern"
            ),
            evidence={
                "official": f"{auth_first} {auth_last}",
                "states": sorted(states),
                "total_entities": len(other_state_entities) + 1,
                "other_entities": [e.name for e in other_state_entities[:5]],
            },
            data_source="cms_hospice_general + nppes_bulk",
            fca_provision="31 USC §3729(a)(1)(A) — multi-state fraud scheme under common control",
            violation_date_start=_parse_date(entity.certification_date),
            violation_date_end=date.today(),
        ))

    return signals


def _of04_related_party(entity, db_session) -> list[Signal]:
    """OF04: Cost report shows high management fees (related party transaction signal)."""
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
            mgmt_fees = _safe_float(data.get("management_fees", data.get("admin_and_general")))
            total_revenue = _safe_float(data.get("total_revenue"))

            if mgmt_fees and total_revenue and total_revenue > 0:
                fee_pct = (mgmt_fees / total_revenue) * 100
                if fee_pct > 25:
                    signals.append(Signal(
                        signal_code="OF04",
                        signal_category="ownership_fraud",
                        severity="HIGH",
                        type="STATISTICAL",
                        weight=7,
                        description=(
                            f"Management fees {fee_pct:.0f}% of revenue — "
                            f"possible related-party transaction "
                            f"(owner paying above-market fees to own LLC)"
                        ),
                        evidence={
                            "management_fees": round(mgmt_fees, 2),
                            "total_revenue": round(total_revenue, 2),
                            "fee_pct": round(fee_pct, 1),
                        },
                        data_source="cost_reports",
                        fca_provision="31 USC §3729(a)(1)(A) — inflated costs through related-party transactions",
                    ))
            break

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


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("%", ""))
    except (ValueError, TypeError):
        return None
