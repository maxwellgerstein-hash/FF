"""
FastAPI routes for the Qui Tam Case Engine dashboard.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db.database import SessionLocal
from db.models import (
    Entity, SignalRecord, CaseLeadRecord, CaseCluster, DataSourceStatus,
)
from output.case_docket import format_case_docket_entry, format_currency

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Make format_currency available in templates
templates.env.globals["format_currency"] = format_currency


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard — ranked case docket."""
    db = SessionLocal()
    try:
        case_leads = (
            db.query(CaseLeadRecord)
            .order_by(CaseLeadRecord.case_score.desc())
            .all()
        )

        leads_with_entities = []
        total_govt_loss = 0
        total_recovery_low = 0
        total_recovery_high = 0
        total_relator_low = 0
        total_relator_high = 0

        for lead in case_leads:
            entity = db.query(Entity).filter(Entity.id == lead.entity_id).first()
            signal_count = (
                db.query(SignalRecord)
                .filter(SignalRecord.entity_id == lead.entity_id)
                .count()
            )
            cluster = None
            if lead.cluster_id:
                cluster = db.query(CaseCluster).filter(
                    CaseCluster.id == lead.cluster_id
                ).first()

            leads_with_entities.append({
                "lead": lead,
                "entity": entity,
                "signal_count": signal_count,
                "cluster": cluster,
            })

            total_govt_loss += lead.estimated_govt_loss or 0
            total_recovery_low += lead.total_recovery_low or 0
            total_recovery_high += lead.total_recovery_high or 0
            total_relator_low += lead.relator_share_low or 0
            total_relator_high += lead.relator_share_high or 0

        # Data freshness
        source_statuses = db.query(DataSourceStatus).all()

        # Summary stats
        total_entities = db.query(Entity).count()
        total_signals = db.query(SignalRecord).count()
        total_sources = len(source_statuses)

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "leads": leads_with_entities,
                "source_statuses": source_statuses,
                "total_entities": total_entities,
                "total_signals": total_signals,
                "total_leads": len(case_leads),
                "total_sources": total_sources,
                "total_govt_loss": total_govt_loss,
                "total_recovery_low": total_recovery_low,
                "total_recovery_high": total_recovery_high,
                "total_relator_low": total_relator_low,
                "total_relator_high": total_relator_high,
            },
        )
    finally:
        db.close()


@router.get("/case/{case_id}", response_class=HTMLResponse)
async def case_detail(request: Request, case_id: int):
    """View a single case lead with all signals and evidence."""
    db = SessionLocal()
    try:
        lead = db.query(CaseLeadRecord).filter(CaseLeadRecord.id == case_id).first()
        if not lead:
            return HTMLResponse("<h1>Case not found</h1>", status_code=404)

        entity = db.query(Entity).filter(Entity.id == lead.entity_id).first()
        signals = (
            db.query(SignalRecord)
            .filter(SignalRecord.entity_id == lead.entity_id)
            .order_by(SignalRecord.weight.desc())
            .all()
        )

        # Parse JSON evidence for display
        parsed_signals = []
        for sig in signals:
            parsed_signals.append({
                "record": sig,
                "evidence": json.loads(sig.evidence) if sig.evidence else {},
            })

        cluster = None
        cluster_entities = []
        if lead.cluster_id:
            cluster = db.query(CaseCluster).filter(
                CaseCluster.id == lead.cluster_id
            ).first()
            if cluster:
                entity_ids = json.loads(cluster.entity_ids)
                cluster_entities = (
                    db.query(Entity).filter(Entity.id.in_(entity_ids)).all()
                )

        # Generate FOIA request
        foia_text = ""
        try:
            from output.foia_generator import generate_foia_request
            foia_text = generate_foia_request(entity, lead, signals)
        except Exception as e:
            foia_text = f"Error generating FOIA request: {e}"

        # Generate complaint draft
        complaint_text = ""
        try:
            from output.complaint_drafter import generate_complaint_draft
            complaint_text = generate_complaint_draft(entity, lead, signals, cluster)
        except Exception as e:
            complaint_text = f"Error generating complaint draft: {e}"

        # Generate case summary
        case_summary = ""
        try:
            from output.complaint_drafter import generate_case_summary
            case_summary = generate_case_summary(entity, lead, signals)
        except Exception as e:
            case_summary = f"Error generating case summary: {e}"

        return templates.TemplateResponse(
            request=request,
            name="case_detail.html",
            context={
                "lead": lead,
                "entity": entity,
                "signals": parsed_signals,
                "cluster": cluster,
                "cluster_entities": cluster_entities,
                "foia_text": foia_text,
                "complaint_text": complaint_text,
                "case_summary": case_summary,
            },
        )
    finally:
        db.close()


@router.get("/network", response_class=HTMLResponse)
async def network_page(request: Request):
    """Network map showing entity relationships."""
    db = SessionLocal()
    try:
        network_data = {"nodes": [], "edges": [], "communities": [], "stats": {
            "total_nodes": 0, "total_edges": 0, "communities_found": 0, "largest_community": 0
        }}
        referral_data = []

        try:
            from analysis.network_analysis import build_entity_network, find_referral_concentration
            network_data = build_entity_network(db)
            referral_data = find_referral_concentration(db)
        except Exception as e:
            print(f"Network analysis error: {e}")

        return templates.TemplateResponse(
            request=request,
            name="network.html",
            context={
                "network_data": network_data,
                "referral_data": referral_data,
            },
        )
    finally:
        db.close()


@router.get("/geographic", response_class=HTMLResponse)
async def geographic_page(request: Request):
    """Geographic heat map of fraud hotspots."""
    db = SessionLocal()
    try:
        geo_data = {"state_stats": {}, "hotspot_cities": [], "state_rankings": []}

        try:
            from analysis.geographic_analysis import generate_geographic_data
            geo_data = generate_geographic_data(db)
        except Exception as e:
            print(f"Geographic analysis error: {e}")

        return templates.TemplateResponse(
            request=request,
            name="geographic.html",
            context={
                "geo_data": geo_data,
            },
        )
    finally:
        db.close()


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    """Data sources status page."""
    db = SessionLocal()
    try:
        source_statuses = db.query(DataSourceStatus).all()

        return templates.TemplateResponse(
            request=request,
            name="sources.html",
            context={
                "source_statuses": source_statuses,
            },
        )
    finally:
        db.close()
