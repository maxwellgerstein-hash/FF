"""
Demo script that loads realistic sample data and runs the full
detection/scoring pipeline so you can see what the engine produces.

This simulates what happens when the real CMS, OIG, and NPPES data
is available — using realistic (but fictional) hospice providers
modeled after real fraud patterns from DOJ press releases.
"""

import sys
import os
import json
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, SessionLocal
from db.models import Entity, SourceRecord, SignalRecord, CaseLeadRecord, LEIEIndex, DataSourceStatus
from resolution.entity_resolver import normalize_name, normalize_address
from detection.hospice_fraud import detect_hospice_signals
from detection.base import Signal
from scoring.case_scorer import calculate_case_score
from scoring.loss_estimator import estimate_hospice_govt_loss
from scoring.legal_risk import assess_public_disclosure_risk, assess_rule_9b, calculate_sol
from clustering.case_clusterer import cluster_case_leads
from output.case_docket import format_currency


# ═══════════════════════════════════════════════════════════════
# SAMPLE DATA — modeled after real fraud patterns
# ═══════════════════════════════════════════════════════════════

SAMPLE_HOSPICES = [
    {
        "name": "Sunrise Comfort Care Hospice LLC",
        "ccn": "051890",
        "npi": "1234567890",
        "address": "8834 VICTORY BLVD STE 200",
        "city": "VAN NUYS",
        "state": "CA",
        "phone": "818-555-0100",
        "cert_date": "01/15/2023",
        "episodes": 450,
        "patients": 380,
        "auth_first": "MARIANA",
        "auth_last": "HERNANDEZ",
        "measures": {"alos": 187, "live_discharge": 78, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Golden State Palliative Services Inc",
        "ccn": "051891",
        "npi": "1234567891",
        "address": "8834 VICTORY BLVD STE 201",  # Same building as above
        "city": "VAN NUYS",
        "state": "CA",
        "phone": "818-555-0101",
        "cert_date": "03/20/2023",
        "episodes": 320,
        "patients": 290,
        "auth_first": "MARIANA",  # Same owner as above
        "auth_last": "HERNANDEZ",
        "measures": {"alos": 210, "live_discharge": 82, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Pacific Hospice Group",
        "ccn": "051892",
        "npi": "1234567892",
        "address": "8834 VICTORY BLVD STE 203",  # Same building again
        "city": "VAN NUYS",
        "state": "CA",
        "phone": "818-555-0103",
        "cert_date": "06/01/2023",
        "episodes": 280,
        "patients": 250,
        "auth_first": "CARLOS",
        "auth_last": "HERNANDEZ",
        "measures": {"alos": 165, "live_discharge": 72, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Eternal Peace Hospice",
        "ccn": "101234",
        "npi": "9876543210",
        "address": "THE UPS STORE 4521 PO BOX 998",
        "city": "MIAMI",
        "state": "FL",
        "phone": "305-555-0200",
        "cert_date": "09/01/2024",
        "episodes": 180,
        "patients": 160,
        "auth_first": "DMITRI",
        "auth_last": "VOLKOV",
        "measures": {"alos": 220, "live_discharge": 85, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Compassionate Journey Home Health & Hospice",
        "ccn": "451567",
        "npi": "5551234567",
        "address": "2200 ROSS AVE STE 4500",
        "city": "DALLAS",
        "state": "TX",
        "phone": "214-555-0300",
        "cert_date": "01/10/2020",
        "episodes": 890,
        "patients": 750,
        "auth_first": "ROBERT",
        "auth_last": "JOHNSON",
        "measures": {"alos": 195, "live_discharge": 76, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Serenity Now Hospice Care",
        "ccn": "241890",
        "npi": "3335557777",
        "address": "PMB 445 1200 NICOLLET MALL",
        "city": "MINNEAPOLIS",
        "state": "MN",
        "phone": "612-555-0400",
        "cert_date": "11/01/2024",
        "episodes": 95,
        "patients": 88,
        "auth_first": "JAMES",
        "auth_last": "SMITH",
        "measures": {"alos": 155, "live_discharge": 68, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
    {
        "name": "Harbor Light End of Life Services",
        "ccn": "051999",
        "npi": "4445556666",
        "address": "15200 SUNSET BLVD STE 100",
        "city": "PACIFIC PALISADES",
        "state": "CA",
        "phone": "310-555-0500",
        "cert_date": "06/15/2019",
        "episodes": 1200,
        "patients": 1050,
        "auth_first": "LINDA",
        "auth_last": "CHEN",
        "measures": {"alos": 45, "live_discharge": 25, "start_date": "01/01/2024", "end_date": "12/31/2024"},
    },
]

# Simulated LEIE entries (excluded individuals)
SAMPLE_LEIE = [
    {
        "LASTNAME": "VOLKOV", "FIRSTNAME": "DMITRI", "MIDNAME": "",
        "BUSNAME": "", "GENERAL": "INDIVIDUAL", "SPECIALTY": "",
        "UPIN": "", "NPI": "", "DOB": "19750315",
        "ADDRESS": "100 BISCAYNE BLVD", "CITY": "MIAMI", "STATE": "FL",
        "ZIP": "33131", "EXCLTYPE": "1128(a)(1)", "EXCLDATE": "20220601",
        "REINDATE": "", "WAIVERDATE": "", "WAIVERSTATE": "",
    },
    {
        "LASTNAME": "HERNANDEZ", "FIRSTNAME": "MARIANA", "MIDNAME": "",
        "BUSNAME": "", "GENERAL": "INDIVIDUAL", "SPECIALTY": "",
        "UPIN": "", "NPI": "", "DOB": "19800722",
        "ADDRESS": "8834 VICTORY BLVD", "CITY": "VAN NUYS", "STATE": "CA",
        "ZIP": "91411", "EXCLTYPE": "1128(a)(2)", "EXCLDATE": "20210901",
        "REINDATE": "", "WAIVERDATE": "", "WAIVERSTATE": "",
    },
]


def run_demo():
    """Load sample data and run the full pipeline."""

    # Clean start
    if os.path.exists("qui_tam_engine.db"):
        os.remove("qui_tam_engine.db")

    init_db()
    db = SessionLocal()

    print("=" * 70)
    print("QUI TAM CASE ENGINE — DEMO RUN")
    print("Using realistic sample data modeled after DOJ fraud cases")
    print("=" * 70)
    print()

    # ── Step 1: Load LEIE exclusion index ──
    print("[1/5] Loading OIG exclusion list...")
    for entry in SAMPLE_LEIE:
        firstname = entry["FIRSTNAME"]
        lastname = entry["LASTNAME"]
        full_name = f"{firstname} {lastname}".strip()
        idx = LEIEIndex(
            full_name_normalized=normalize_name(full_name),
            state=entry["STATE"],
            npi=entry.get("NPI", ""),
            exclusion_type=entry["EXCLTYPE"],
            exclusion_date=entry["EXCLDATE"],
            raw_record=json.dumps(entry),
        )
        db.add(idx)
    db.commit()
    print(f"  Loaded {len(SAMPLE_LEIE)} excluded individuals")

    # ── Step 2: Create entities ──
    print("[2/5] Creating hospice entities...")
    for h in SAMPLE_HOSPICES:
        entity = Entity(
            name=h["name"],
            name_normalized=normalize_name(h["name"]),
            entity_type="healthcare_provider",
            ccn=h["ccn"],
            npi=h["npi"],
            address=h["address"],
            address_normalized=normalize_address(h["address"]),
            city=h["city"],
            state=h["state"],
            telephone=h["phone"],
            certification_date=h["cert_date"],
            total_episodes=h["episodes"],
            total_patients=h["patients"],
            estimated_annual_medicare_payments=float(h["episodes"]) * 18 * 195.0,
            authorized_official_first_name=h["auth_first"],
            authorized_official_last_name=h["auth_last"],
            created_at=datetime.now().isoformat(),
        )
        db.add(entity)
    db.commit()
    print(f"  Created {len(SAMPLE_HOSPICES)} hospice entities")

    # ── Step 3: Detect signals ──
    print("[3/5] Running fraud detection...")
    entities = db.query(Entity).all()
    total_signals = 0

    for entity in entities:
        # Find matching measures
        matching = [h for h in SAMPLE_HOSPICES if h["ccn"] == entity.ccn]
        measures = matching[0]["measures"] if matching else {}

        signals = detect_hospice_signals(entity, measures, db)

        for signal in signals:
            sig_record = SignalRecord(
                entity_id=entity.id,
                signal_code=signal.signal_code,
                signal_category=signal.signal_category,
                severity=signal.severity,
                signal_type=signal.type,
                weight=signal.weight,
                description=signal.description,
                evidence=signal.evidence_json(),
                data_source=signal.data_source,
                fca_provision=signal.fca_provision,
                violation_date_start=str(signal.violation_date_start) if signal.violation_date_start else None,
                violation_date_end=str(signal.violation_date_end) if signal.violation_date_end else None,
                detected_at=datetime.now().isoformat(),
            )
            db.add(sig_record)
            total_signals += 1

    db.commit()
    print(f"  Detected {total_signals} fraud signals")

    # ── Step 4: Score and generate case leads ──
    print("[4/5] Scoring case leads...")
    flagged_ids = [eid[0] for eid in db.query(SignalRecord.entity_id).distinct().all()]
    leads_generated = 0

    for entity_id in flagged_ids:
        entity = db.query(Entity).filter(Entity.id == entity_id).first()
        sig_records = db.query(SignalRecord).filter(SignalRecord.entity_id == entity_id).all()

        signals = []
        for sr in sig_records:
            signals.append(Signal(
                signal_code=sr.signal_code,
                signal_category=sr.signal_category,
                severity=sr.severity,
                type=sr.signal_type,
                weight=sr.weight,
                description=sr.description,
                evidence=json.loads(sr.evidence),
                data_source=sr.data_source,
                fca_provision=sr.fca_provision or "",
                violation_date_start=_parse_date(sr.violation_date_start),
                violation_date_end=_parse_date(sr.violation_date_end),
            ))

        govt_loss = estimate_hospice_govt_loss(entity, signals)
        if govt_loss < 500_000:
            continue

        case_score = calculate_case_score(entity, signals, govt_loss)
        if not case_score:
            continue

        pd_risk, _ = assess_public_disclosure_risk(signals)
        rule_9b, _ = assess_rule_9b(signals)
        sol_expiry, _ = calculate_sol(signals)

        lead = CaseLeadRecord(
            entity_id=entity_id,
            case_score=case_score.score,
            confidence=case_score.confidence,
            estimated_govt_loss=case_score.govt_loss,
            estimated_claim_count=case_score.estimated_claim_count,
            treble_damages=case_score.treble_damages,
            double_damages=case_score.double_damages,
            penalties_low=case_score.penalties_low,
            penalties_high=case_score.penalties_high,
            total_recovery_low=case_score.total_recovery_low,
            total_recovery_high=case_score.total_recovery_high,
            relator_share_low=case_score.relator_share_low,
            relator_share_high=case_score.relator_share_high,
            legal_theory="FCA 31 USC \u00a73729(a)(1)(A) — knowingly presenting false claims",
            fca_provisions=json.dumps(["31 USC \u00a73729(a)(1)(A)"]),
            fraud_category="hospice_fraud",
            public_disclosure_risk=pd_risk,
            first_to_file_risk="UNKNOWN_CLEAR",
            rule_9b_sufficiency=rule_9b,
            doj_intervention_likelihood=case_score.doj_intervention_likelihood,
            sol_expiry=str(sol_expiry) if sol_expiry else None,
            signal_ids=json.dumps([sr.id for sr in sig_records]),
            status="NEW",
            created_at=datetime.now().isoformat(),
        )
        db.add(lead)
        leads_generated += 1

    db.commit()
    print(f"  Generated {leads_generated} case leads above $500K threshold")

    # ── Step 5: Cluster ──
    print("[5/5] Clustering related leads...")
    cluster_stats = cluster_case_leads(db)
    print(f"  Created {cluster_stats['clusters_created']} clusters")

    # ═══════════════════════════════════════════════════════════════
    # PRINT RESULTS
    # ═══════════════════════════════════════════════════════════════

    print()
    print("=" * 70)
    print("CASE DOCKET — RANKED BY CASE SCORE")
    print("=" * 70)

    leads = db.query(CaseLeadRecord).order_by(CaseLeadRecord.case_score.desc()).all()

    for rank, lead in enumerate(leads, 1):
        entity = db.query(Entity).filter(Entity.id == lead.entity_id).first()
        sigs = db.query(SignalRecord).filter(SignalRecord.entity_id == lead.entity_id).order_by(SignalRecord.weight.desc()).all()

        print()
        print(f"{'─' * 70}")
        print(f"  CASE #{rank}  |  Score: {lead.case_score:.1f}/100  |  Confidence: {lead.confidence:.0%}")
        print(f"{'─' * 70}")
        print(f"  Entity:    {entity.name}")
        print(f"  Address:   {entity.address}, {entity.city}, {entity.state}")
        if entity.npi:
            print(f"  NPI:       {entity.npi}")
        if entity.authorized_official_last_name:
            print(f"  Official:  {entity.authorized_official_first_name} {entity.authorized_official_last_name}")
        print()

        print(f"  ESTIMATED RECOVERY")
        print(f"  {'Government Loss:':<30} {format_currency(lead.estimated_govt_loss)}")
        print(f"  {'False Claims:':<30} {lead.estimated_claim_count:,}")
        print(f"  {'Double Damages:':<30} {format_currency(lead.double_damages)}")
        print(f"  {'Treble Damages:':<30} {format_currency(lead.treble_damages)}")
        print(f"  {'Per-Claim Penalties:':<30} {format_currency(lead.penalties_low)} - {format_currency(lead.penalties_high)}")
        print(f"  {'TOTAL RECOVERY:':<30} {format_currency(lead.total_recovery_low)} - {format_currency(lead.total_recovery_high)}")
        print(f"  {'Relator Share (15-30%):':<30} {format_currency(lead.relator_share_low)} - {format_currency(lead.relator_share_high)}")
        print()

        print(f"  LEGAL RISK")
        print(f"  {'Public Disclosure:':<30} {lead.public_disclosure_risk}")
        print(f"  {'First-to-File:':<30} {lead.first_to_file_risk}")
        print(f"  {'Rule 9(b):':<30} {lead.rule_9b_sufficiency}")
        print(f"  {'DOJ Intervention:':<30} {lead.doj_intervention_likelihood}")
        if lead.sol_expiry:
            print(f"  {'SOL Expiry:':<30} {lead.sol_expiry}")
        print()

        print(f"  SIGNALS DETECTED ({len(sigs)})")
        for sig in sigs:
            marker = "!!" if sig.signal_type == "RULE_VIOLATION" else ">>"
            print(f"    {marker} [{sig.signal_code}] {sig.severity} (wt:{sig.weight}) — {sig.description}")
        print()

    # Cluster summary
    from db.models import CaseCluster
    clusters = db.query(CaseCluster).all()
    if clusters:
        print(f"{'=' * 70}")
        print("CASE CLUSTERS (related entities that form a single case)")
        print(f"{'=' * 70}")
        for cluster in clusters:
            entity_ids = json.loads(cluster.entity_ids)
            print(f"\n  {cluster.cluster_name}")
            print(f"  Type: {cluster.cluster_type}")
            print(f"  Combined Loss: {format_currency(cluster.combined_govt_loss)}")
            print(f"  Entities:")
            for eid in entity_ids:
                e = db.query(Entity).filter(Entity.id == eid).first()
                if e:
                    print(f"    - {e.name} ({e.address})")

    db.close()


def _parse_date(s):
    if not s or s == "None":
        return None
    for fmt in ["%Y-%m-%d", "%m/%d/%Y"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    run_demo()
