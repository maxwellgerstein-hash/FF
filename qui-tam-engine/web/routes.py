"""
FastAPI routes for the Qui Tam Case Engine dashboard.
"""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db.database import SessionLocal
from db.models import (
    Entity, SignalRecord, CaseLeadRecord, CaseCluster, DataSourceStatus,
)
from output.case_docket import format_case_docket_entry, format_currency

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

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

        # Data freshness
        source_statuses = db.query(DataSourceStatus).all()

        # Summary stats
        total_entities = db.query(Entity).count()
        total_signals = db.query(SignalRecord).count()

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "leads": leads_with_entities,
            "source_statuses": source_statuses,
            "total_entities": total_entities,
            "total_signals": total_signals,
            "total_leads": len(case_leads),
        })
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

        return templates.TemplateResponse("case_detail.html", {
            "request": request,
            "lead": lead,
            "entity": entity,
            "signals": parsed_signals,
            "cluster": cluster,
            "cluster_entities": cluster_entities,
        })
    finally:
        db.close()
