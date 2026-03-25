"""
Case Docket Output Formatter.

Formats case leads into structured docket entries for attorney review.
"""

import json
from db.models import Entity, CaseLeadRecord, SignalRecord, CaseCluster


def format_case_docket_entry(lead: CaseLeadRecord, entity: Entity,
                              signals: list[SignalRecord],
                              cluster: CaseCluster | None = None) -> dict:
    """
    Format a single case lead into a structured docket entry.
    This is the format sent to counsel.
    """
    signal_details = []
    for sig in signals:
        evidence = json.loads(sig.evidence) if isinstance(sig.evidence, str) else sig.evidence
        signal_details.append({
            "code": sig.signal_code,
            "severity": sig.severity,
            "type": sig.signal_type,
            "weight": sig.weight,
            "description": sig.description,
            "evidence": evidence,
            "data_source": sig.data_source,
            "fca_provision": sig.fca_provision,
            "violation_dates": {
                "start": sig.violation_date_start,
                "end": sig.violation_date_end,
            },
        })

    docket_entry = {
        "case_id": lead.id,
        "status": lead.status,

        # Entity identification
        "entity": {
            "name": entity.name,
            "npi": entity.npi,
            "ccn": entity.ccn,
            "address": entity.address,
            "city": entity.city,
            "state": entity.state,
            "telephone": entity.telephone,
            "entity_type": entity.entity_type,
            "authorized_official": (
                f"{entity.authorized_official_first_name or ''} "
                f"{entity.authorized_official_last_name or ''}"
            ).strip() or None,
        },

        # Scoring
        "case_score": lead.case_score,
        "confidence": lead.confidence,
        "fraud_category": lead.fraud_category,

        # Legal theory
        "legal_theory": lead.legal_theory,
        "fca_provisions": json.loads(lead.fca_provisions) if lead.fca_provisions else [],

        # Recovery estimation (LOW/HIGH range)
        "recovery": {
            "government_loss": lead.estimated_govt_loss,
            "estimated_claim_count": lead.estimated_claim_count,
            "double_damages": lead.double_damages,
            "treble_damages": lead.treble_damages,
            "per_claim_penalties": {
                "low_per_claim": 13_946,
                "high_per_claim": 27_894,
                "total_low": lead.penalties_low,
                "total_high": lead.penalties_high,
            },
            "total_recovery_low": lead.total_recovery_low,
            "total_recovery_high": lead.total_recovery_high,
            "relator_share_low": lead.relator_share_low,
            "relator_share_high": lead.relator_share_high,
        },

        # Signals
        "signals": signal_details,
        "signal_count": len(signal_details),

        # Legal risk assessment
        "legal_risk": {
            "public_disclosure_risk": lead.public_disclosure_risk,
            "first_to_file_risk": lead.first_to_file_risk,
            "rule_9b_sufficiency": lead.rule_9b_sufficiency,
            "doj_intervention_likelihood": lead.doj_intervention_likelihood,
            "sol_expiry": lead.sol_expiry,
        },

        # Cluster info
        "cluster": None,
    }

    if cluster:
        docket_entry["cluster"] = {
            "cluster_id": cluster.id,
            "cluster_name": cluster.cluster_name,
            "cluster_type": cluster.cluster_type,
            "entity_count": len(json.loads(cluster.entity_ids)),
            "combined_govt_loss": cluster.combined_govt_loss,
        }

    return docket_entry


def format_currency(amount: float | None) -> str:
    """Format a number as USD currency."""
    if amount is None:
        return "N/A"
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.1f}K"
    return f"${amount:,.2f}"
