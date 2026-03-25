"""
Full pipeline orchestrator with SSE progress events.

Executes:
  1. Data ingestion (CMS Hospice Compare, OIG LEIE, NPPES, DOJ, Open Payments, Cost Reports, SAM.gov, SEC, News)
  2. Entity resolution
  3. Fraud signal detection (25+ signal types across 5 detection modules)
  4. Case scoring and lead generation
  5. Case clustering
"""

import asyncio
import json
import time
from datetime import datetime, date

from db.database import SessionLocal, init_db
from db.models import Entity, SourceRecord, SignalRecord, CaseLeadRecord, DataSourceStatus
from db.seed_known_fraud import seed_known_fraud_cases
from ingestion.cms_hospice import CMSHospiceIngester, find_measure_code
from ingestion.oig_leie import OIGLEIEIngester
from ingestion.nppes import NPPESIngester
from resolution.entity_resolver import EntityResolver
from detection.base import Signal
from detection.hospice_fraud import detect_hospice_signals, _parse_date
from scoring.case_scorer import calculate_case_score
from scoring.loss_estimator import estimate_hospice_govt_loss
from scoring.legal_risk import assess_public_disclosure_risk, assess_rule_9b, calculate_sol
from clustering.case_clusterer import cluster_case_leads
from config import EXPECTED_MEASURE_CODES

# Pipeline steps with display names and estimated durations (seconds)
PIPELINE_STEPS = [
    {"id": "prepare", "name": "Preparing workspace", "est_seconds": 5},
    {"id": "ingest_cms", "name": "Downloading CMS Hospice Compare data", "est_seconds": 30},
    {"id": "ingest_leie", "name": "Downloading OIG LEIE exclusion list", "est_seconds": 20},
    {"id": "ingest_nppes", "name": "Downloading & scanning NPPES bulk file (~1 GB)", "est_seconds": 300},
    {"id": "ingest_extra", "name": "Ingesting DOJ, Open Payments, Cost Reports, SAM, SEC, News", "est_seconds": 30},
    {"id": "resolve", "name": "Resolving entities across data sources", "est_seconds": 30},
    {"id": "detect", "name": "Running fraud signal detection (25+ signal types)", "est_seconds": 60},
    {"id": "score", "name": "Scoring case leads & estimating recoveries", "est_seconds": 20},
    {"id": "cluster", "name": "Clustering related case leads", "est_seconds": 10},
]


async def run_pipeline(progress_queue: asyncio.Queue | None = None):
    """
    Execute the full analysis pipeline.

    Args:
        progress_queue: If provided, put {message, percent, step, step_index,
                        total_steps, elapsed, eta} dicts for SSE streaming.
    """
    pipeline_start = time.monotonic()
    current_step_index = 0

    def emit(msg: str, pct: float, step_id: str | None = None):
        nonlocal current_step_index
        elapsed = time.monotonic() - pipeline_start

        # Update step index
        if step_id:
            for i, s in enumerate(PIPELINE_STEPS):
                if s["id"] == step_id:
                    current_step_index = i
                    break

        # Estimate remaining time based on step estimates
        remaining_est = sum(
            s["est_seconds"] for s in PIPELINE_STEPS[current_step_index:]
        )
        # Adjust estimate based on actual pace vs expected pace
        expected_elapsed = sum(
            s["est_seconds"] for s in PIPELINE_STEPS[:current_step_index]
        )
        if expected_elapsed > 0 and elapsed > 0:
            pace_ratio = elapsed / expected_elapsed
            remaining_est = remaining_est * pace_ratio

        event = {
            "message": msg,
            "percent": pct,
            "step": PIPELINE_STEPS[current_step_index]["name"] if current_step_index < len(PIPELINE_STEPS) else "Finishing",
            "step_index": current_step_index,
            "total_steps": len(PIPELINE_STEPS),
            "elapsed": round(elapsed),
            "eta": max(round(remaining_est), 0),
        }
        if progress_queue:
            progress_queue.put_nowait(event)
        print(f"[{pct:.0%}] {msg}")

    init_db()
    db = SessionLocal()

    try:
        # Clear stale data from any previous run so results don't accumulate
        emit("Clearing previous analysis data...", 0.02, "prepare")
        db.query(CaseLeadRecord).delete()
        db.query(SignalRecord).delete()
        db.query(Entity).delete()
        db.query(SourceRecord).delete()
        db.commit()

        # Seed known fraud cases for validation
        seed_known_fraud_cases()

        # ════════════════════════════════════════
        # DATA INGESTION — CORE SOURCES
        # ════════════════════════════════════════

        emit("Downloading CMS Hospice Compare data...", 0.05, "ingest_cms")
        try:
            hospice_stats = await CMSHospiceIngester().ingest(db)
            emit(
                f"Hospice Compare: {hospice_stats['records_pulled']} agencies, "
                f"{hospice_stats['measures_pulled']} measure sets loaded",
                0.10,
                "ingest_cms",
            )
        except Exception as e:
            emit(f"WARNING: CMS Hospice Compare failed: {e}", 0.10, "ingest_cms")
            hospice_stats = {"records_pulled": 0, "measures_pulled": 0}

        emit("Downloading OIG LEIE exclusion list...", 0.12, "ingest_leie")
        try:
            leie_stats = await OIGLEIEIngester().ingest(db)
            emit(
                f"OIG LEIE: {leie_stats['records_pulled']} exclusions indexed "
                f"({leie_stats['records_with_npi']} with NPI)",
                0.20,
                "ingest_leie",
            )
        except Exception as e:
            emit(f"WARNING: OIG LEIE failed: {e}", 0.20, "ingest_leie")
            leie_stats = {"records_pulled": 0, "records_with_npi": 0}

        emit("Downloading NPPES bulk file (~1 GB)...", 0.22, "ingest_nppes")
        try:
            nppes_stats = await NPPESIngester().ingest(
                db, progress_callback=lambda msg, _: emit(msg, 0.35, "ingest_nppes")
            )
            emit(
                f"NPPES: {nppes_stats['hospice_rows_found']} hospice providers extracted "
                f"from {nppes_stats['total_rows_scanned']:,} total records",
                0.40,
                "ingest_nppes",
            )
        except Exception as e:
            emit(f"WARNING: NPPES failed: {e}. Continuing without NPPES enrichment.", 0.40, "ingest_nppes")
            nppes_stats = {"hospice_rows_found": 0, "total_rows_scanned": 0}

        # ════════════════════════════════════════
        # DATA INGESTION — EXTENDED SOURCES
        # ════════════════════════════════════════

        emit("Ingesting extended data sources...", 0.42, "ingest_extra")
        extra_stats = {}

        # DOJ Settlements
        try:
            from ingestion.doj_settlements import DOJSettlementsIngester
            doj_stats = await DOJSettlementsIngester().ingest(db)
            extra_stats["doj"] = doj_stats
            emit(f"DOJ Settlements: {doj_stats.get('records_pulled', 0)} cases loaded", 0.44, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: DOJ Settlements failed: {e}", 0.44, "ingest_extra")

        # Open Payments
        try:
            from ingestion.open_payments import OpenPaymentsIngester
            op_stats = await OpenPaymentsIngester().ingest(db)
            extra_stats["open_payments"] = op_stats
            emit(f"Open Payments: {op_stats.get('records_pulled', 0)} records loaded", 0.46, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: Open Payments failed: {e}", 0.46, "ingest_extra")

        # Cost Reports
        try:
            from ingestion.cost_reports import CostReportsIngester
            cr_stats = await CostReportsIngester().ingest(db)
            extra_stats["cost_reports"] = cr_stats
            emit(f"Cost Reports: {cr_stats.get('records_pulled', 0)} records loaded", 0.47, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: Cost Reports failed: {e}", 0.47, "ingest_extra")

        # SAM.gov
        try:
            from ingestion.sam_gov import SAMGovIngester
            sam_stats = await SAMGovIngester().ingest(db)
            extra_stats["sam"] = sam_stats
            emit(f"SAM.gov: {sam_stats.get('records_pulled', 0)} exclusions loaded", 0.48, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: SAM.gov failed: {e}", 0.48, "ingest_extra")

        # SEC EDGAR
        try:
            from ingestion.sec_edgar import SECEdgarIngester
            sec_stats = await SECEdgarIngester().ingest(db)
            extra_stats["sec"] = sec_stats
            emit(f"SEC EDGAR: {sec_stats.get('records_pulled', 0)} filings loaded", 0.49, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: SEC EDGAR failed: {e}", 0.49, "ingest_extra")

        # News
        try:
            from ingestion.news_scraper import NewsIngester
            news_stats = await NewsIngester().ingest(db)
            extra_stats["news"] = news_stats
            emit(f"News: {news_stats.get('records_pulled', 0)} articles loaded", 0.50, "ingest_extra")
        except Exception as e:
            emit(f"WARNING: News failed: {e}", 0.50, "ingest_extra")

        total_extra = sum(s.get("records_pulled", 0) for s in extra_stats.values())
        emit(f"Extended sources: {total_extra} total records from {len(extra_stats)} sources", 0.50, "ingest_extra")

        # ════════════════════════════════════════
        # ENTITY RESOLUTION
        # ════════════════════════════════════════

        emit("Resolving entities across data sources...", 0.52, "resolve")
        resolver = EntityResolver()
        resolution_stats = resolver.resolve_hospice_entities(db)
        emit(
            f"Resolved {resolution_stats['entities_created']} entities, "
            f"{resolution_stats['nppes_matched']} NPPES matches",
            0.60,
            "resolve",
        )

        # ════════════════════════════════════════
        # FRAUD SIGNAL DETECTION
        # ════════════════════════════════════════

        emit("Building hospice quality measures lookup...", 0.62, "detect")
        measures_by_ccn = _build_measures_lookup(db)
        emit(f"Measures available for {len(measures_by_ccn)} hospices", 0.65, "detect")

        emit("Running fraud signal detection (25+ signal types)...", 0.68, "detect")

        entities = db.query(Entity).all()
        total_signals = 0
        entities_with_signals = 0

        # Load optional detection modules
        advanced_detect = None
        ownership_detect = None
        geographic_detect = None
        temporal_detect = None

        try:
            from detection.advanced_hospice import detect_advanced_hospice_signals
            advanced_detect = detect_advanced_hospice_signals
        except Exception as e:
            print(f"Advanced hospice detection not available: {e}")

        try:
            from detection.ownership_fraud import detect_ownership_signals
            ownership_detect = detect_ownership_signals
        except Exception as e:
            print(f"Ownership fraud detection not available: {e}")

        try:
            from detection.geographic_signals import detect_geographic_signals
            geographic_detect = detect_geographic_signals
        except Exception as e:
            print(f"Geographic detection not available: {e}")

        try:
            from detection.temporal_signals import detect_temporal_signals
            temporal_detect = detect_temporal_signals
        except Exception as e:
            print(f"Temporal detection not available: {e}")

        for i, entity in enumerate(entities):
            measures = measures_by_ccn.get(entity.ccn, {})

            # Run all detection modules
            all_signals = []

            # Core hospice fraud signals (HF01-HF11)
            signals = detect_hospice_signals(entity, measures, db)
            all_signals.extend(signals)

            # Advanced hospice signals (HF12-HF18)
            if advanced_detect:
                try:
                    adv_signals = advanced_detect(entity, measures, db)
                    all_signals.extend(adv_signals)
                except Exception:
                    pass

            # Ownership fraud signals (OF01-OF04)
            if ownership_detect:
                try:
                    own_signals = ownership_detect(entity, measures, db)
                    all_signals.extend(own_signals)
                except Exception:
                    pass

            # Geographic signals (GEO01-GEO03)
            if geographic_detect:
                try:
                    geo_signals = geographic_detect(entity, measures, db)
                    all_signals.extend(geo_signals)
                except Exception:
                    pass

            # Temporal signals (TP01-TP03)
            if temporal_detect:
                try:
                    tmp_signals = temporal_detect(entity, measures, db)
                    all_signals.extend(tmp_signals)
                except Exception:
                    pass

            if all_signals:
                entities_with_signals += 1
                for signal in all_signals:
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
                        violation_date_start=(
                            str(signal.violation_date_start)
                            if signal.violation_date_start else None
                        ),
                        violation_date_end=(
                            str(signal.violation_date_end)
                            if signal.violation_date_end else None
                        ),
                        detected_at=datetime.now().isoformat(),
                    )
                    db.add(sig_record)
                    total_signals += 1

            if (i + 1) % 500 == 0:
                db.commit()
                pct = 0.68 + (i / max(len(entities), 1)) * 0.15
                emit(
                    f"Scanned {i + 1}/{len(entities)} entities, "
                    f"{total_signals} signals detected...",
                    pct,
                    "detect",
                )

        db.commit()
        emit(
            f"Detection complete: {total_signals} signals across "
            f"{entities_with_signals} entities",
            0.85,
            "detect",
        )

        # ════════════════════════════════════════
        # CASE SCORING & RECOVERY ESTIMATION
        # ════════════════════════════════════════

        emit("Scoring case leads and estimating recoveries...", 0.88, "score")

        flagged_entity_ids = [
            eid[0]
            for eid in db.query(SignalRecord.entity_id).distinct().all()
        ]

        case_leads_generated = 0
        below_threshold = 0

        for entity_id in flagged_entity_ids:
            entity = db.query(Entity).filter(Entity.id == entity_id).first()
            sig_records = (
                db.query(SignalRecord)
                .filter(SignalRecord.entity_id == entity_id)
                .all()
            )

            # Convert SignalRecords to Signal dataclass for scoring
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
                    violation_date_start=_parse_date_str(sr.violation_date_start),
                    violation_date_end=_parse_date_str(sr.violation_date_end),
                ))

            # Estimate government loss
            govt_loss = estimate_hospice_govt_loss(entity, signals)

            if govt_loss < 500_000:
                below_threshold += 1
                continue

            # Score the case
            case_score = calculate_case_score(entity, signals, govt_loss)
            if case_score is None:
                continue

            # Legal risk assessments
            pd_risk, _ = assess_public_disclosure_risk(signals)
            rule_9b, _ = assess_rule_9b(signals)
            sol_expiry, _ = calculate_sol(signals)

            case_lead = CaseLeadRecord(
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
                legal_theory="FCA 31 USC \u00a73729(a)(1)(A) \u2014 knowingly presenting false claims",
                fca_provisions=json.dumps(["31 USC \u00a73729(a)(1)(A)"]),
                fraud_category="hospice_fraud",
                public_disclosure_risk=pd_risk,
                first_to_file_risk="UNKNOWN_CLEAR",
                rule_9b_sufficiency=rule_9b,
                doj_intervention_likelihood=case_score.doj_intervention_likelihood,
                sol_expiry=str(sol_expiry) if sol_expiry else None,
                recommended_counsel_type="healthcare_fca_specialist",
                signal_ids=json.dumps([sr.id for sr in sig_records]),
                status="NEW",
                created_at=datetime.now().isoformat(),
            )
            db.add(case_lead)
            case_leads_generated += 1

        db.commit()

        # ════════════════════════════════════════
        # CLUSTER RELATED LEADS
        # ════════════════════════════════════════

        emit("Clustering related case leads...", 0.93, "cluster")
        cluster_stats = cluster_case_leads(db)
        emit(
            f"Created {cluster_stats['clusters_created']} clusters, "
            f"{cluster_stats['leads_clustered']} leads grouped",
            0.96,
            "cluster",
        )

        emit(
            f"COMPLETE: {case_leads_generated} case leads above $500K threshold "
            f"({below_threshold} entities below threshold filtered out)",
            1.0,
        )

        return {
            "hospice_agencies_analyzed": hospice_stats.get("records_pulled", 0),
            "exclusions_checked": leie_stats.get("records_pulled", 0),
            "nppes_hospice_providers": nppes_stats.get("hospice_rows_found", 0),
            "extra_sources_loaded": total_extra,
            "entities_resolved": resolution_stats["entities_created"],
            "signals_detected": total_signals,
            "entities_flagged": entities_with_signals,
            "case_leads_generated": case_leads_generated,
            "below_threshold": below_threshold,
            "clusters_created": cluster_stats["clusters_created"],
        }

    finally:
        db.close()


def _build_measures_lookup(db) -> dict:
    """
    Build a CCN -> {measure_key: score} lookup from pivoted measures records.
    """
    measures_records = (
        db.query(SourceRecord)
        .filter(SourceRecord.source_name == "cms_hospice_measures")
        .all()
    )

    lookup = {}
    for record in measures_records:
        data = record.get_data()
        ccn = data.get("CMS Certification Number (CCN)", "").strip()
        if not ccn:
            continue

        all_codes = [
            k for k in data.keys()
            if k not in ("CMS Certification Number (CCN)", "Start Date", "End Date")
        ]

        measures = {}
        for key in EXPECTED_MEASURE_CODES:
            code = find_measure_code(all_codes, key)
            if code and code in data:
                measures[key] = data[code]

        measures["start_date"] = data.get("Start Date", "")
        measures["end_date"] = data.get("End Date", "")

        lookup[ccn] = measures

    return lookup


def _parse_date_str(s) -> date | None:
    """Parse an ISO date string back to a date object."""
    if not s or s == "None":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
