"""
Geographic analysis and heat map data for hospice fraud detection.

Generates state- and city-level statistics, risk rankings, and market
concentration metrics for visualization dashboards.
"""

import json
from collections import defaultdict

from db.models import Entity, CaseLeadRecord, SignalRecord, SourceRecord
from db.database import SessionLocal


def generate_geographic_data(db_session) -> dict:
    """
    Generate geographic analysis data for visualization.

    Returns:
    - state_stats: dict of state -> {entity_count, signal_count, total_loss,
                                      avg_score, top_entity}
    - hotspot_cities: list of {city, state, entity_count, signal_count, total_loss}
    - state_rankings: sorted list of (state, risk_score)
    """
    # ------------------------------------------------------------------
    # Gather all entities that have case leads
    # ------------------------------------------------------------------
    leads = db_session.query(CaseLeadRecord).all()
    lead_by_entity = defaultdict(list)
    for lead in leads:
        if lead.entity_id is not None:
            lead_by_entity[lead.entity_id].append(lead)

    entity_ids = set(lead_by_entity.keys())
    if not entity_ids:
        return {
            "state_stats": {},
            "hotspot_cities": [],
            "state_rankings": [],
        }

    entities = (
        db_session.query(Entity)
        .filter(Entity.id.in_(entity_ids))
        .all()
    )
    entity_map = {e.id: e for e in entities}

    # Signal counts per entity
    signals = (
        db_session.query(SignalRecord)
        .filter(SignalRecord.entity_id.in_(entity_ids))
        .all()
    )
    signals_by_entity = defaultdict(list)
    for sig in signals:
        signals_by_entity[sig.entity_id].append(sig)

    # ------------------------------------------------------------------
    # Build state-level stats
    # ------------------------------------------------------------------
    state_entities = defaultdict(list)
    for eid, ent in entity_map.items():
        st = (ent.state or "UNKNOWN").upper().strip()
        state_entities[st].append(eid)

    state_stats = {}
    for st, eids in state_entities.items():
        sig_count = sum(len(signals_by_entity.get(eid, [])) for eid in eids)
        total_loss = 0.0
        scores = []
        best_entity = None
        best_score = -1.0
        for eid in eids:
            for lead in lead_by_entity.get(eid, []):
                total_loss += lead.estimated_govt_loss or 0.0
                score = lead.case_score or 0.0
                scores.append(score)
                if score > best_score:
                    best_score = score
                    best_entity = entity_map.get(eid)
        avg_score = sum(scores) / len(scores) if scores else 0.0
        state_stats[st] = {
            "entity_count": len(eids),
            "signal_count": sig_count,
            "total_loss": round(total_loss, 2),
            "avg_score": round(avg_score, 2),
            "top_entity": {
                "id": best_entity.id,
                "name": best_entity.name or "",
                "score": round(best_score, 2),
            } if best_entity else None,
        }

    # ------------------------------------------------------------------
    # Build city-level hotspots
    # ------------------------------------------------------------------
    city_key_data = defaultdict(lambda: {
        "entity_ids": set(),
        "city": "",
        "state": "",
    })
    for eid, ent in entity_map.items():
        city = (ent.city or "").strip()
        st = (ent.state or "").strip().upper()
        if not city:
            continue
        key = (city.lower(), st)
        city_key_data[key]["entity_ids"].add(eid)
        city_key_data[key]["city"] = city.title()
        city_key_data[key]["state"] = st

    hotspot_cities = []
    for key, cdata in city_key_data.items():
        eids = cdata["entity_ids"]
        sig_count = sum(len(signals_by_entity.get(eid, [])) for eid in eids)
        total_loss = 0.0
        for eid in eids:
            for lead in lead_by_entity.get(eid, []):
                total_loss += lead.estimated_govt_loss or 0.0
        hotspot_cities.append({
            "city": cdata["city"],
            "state": cdata["state"],
            "entity_count": len(eids),
            "signal_count": sig_count,
            "total_loss": round(total_loss, 2),
        })

    # Sort by total_loss descending
    hotspot_cities.sort(key=lambda c: c["total_loss"], reverse=True)

    # ------------------------------------------------------------------
    # State risk rankings
    # ------------------------------------------------------------------
    # Risk score = weighted combination of avg case score, loss density,
    # and signal density.
    state_rankings = []
    for st, stats in state_stats.items():
        ent_count = stats["entity_count"] or 1
        risk_score = (
            stats["avg_score"] * 0.5
            + min(stats["total_loss"] / (ent_count * 100_000), 1.0) * 100 * 0.3
            + min(stats["signal_count"] / ent_count, 10.0) * 10 * 0.2
        )
        state_rankings.append((st, round(risk_score, 2)))

    state_rankings.sort(key=lambda x: x[1], reverse=True)

    return {
        "state_stats": state_stats,
        "hotspot_cities": hotspot_cities,
        "state_rankings": state_rankings,
    }


def calculate_market_concentration(db_session) -> list[dict]:
    """
    Calculate hospice market concentration by geographic area.

    Uses estimated annual Medicare payments to compute HHI-like concentration
    metrics per state (or city where data is sufficient).

    Returns a list of dicts sorted by concentration descending:
    {
        area: str (state or "city, state"),
        area_type: "state" | "city",
        total_medicare_payments: float,
        entity_count: int,
        top_provider: {name, share_pct},
        hhi: float,  # Herfindahl-Hirschman Index (0-10000)
        concentration_level: "high" | "moderate" | "low",
    }
    """
    entities = db_session.query(Entity).all()

    # ------------------------------------------------------------------
    # Group by state
    # ------------------------------------------------------------------
    by_state = defaultdict(list)
    by_city = defaultdict(list)
    for ent in entities:
        st = (ent.state or "").strip().upper()
        if st:
            by_state[st].append(ent)
        city = (ent.city or "").strip()
        if city and st:
            by_city[(city.lower(), st)].append(ent)

    results = []

    for st, ents in by_state.items():
        total_payments = sum(ent.estimated_annual_medicare_payments or 0.0 for ent in ents)
        if total_payments <= 0:
            continue

        shares = []
        top_name = ""
        top_share = 0.0
        for ent in ents:
            pmt = ent.estimated_annual_medicare_payments or 0.0
            share = (pmt / total_payments) * 100.0 if total_payments > 0 else 0.0
            shares.append(share)
            if share > top_share:
                top_share = share
                top_name = ent.name or ""

        hhi = sum(s * s for s in shares)

        if hhi >= 2500:
            level = "high"
        elif hhi >= 1500:
            level = "moderate"
        else:
            level = "low"

        results.append({
            "area": st,
            "area_type": "state",
            "total_medicare_payments": round(total_payments, 2),
            "entity_count": len(ents),
            "top_provider": {
                "name": top_name,
                "share_pct": round(top_share, 2),
            },
            "hhi": round(hhi, 2),
            "concentration_level": level,
        })

    # ------------------------------------------------------------------
    # City-level for areas with enough providers
    # ------------------------------------------------------------------
    for (city, st), ents in by_city.items():
        if len(ents) < 3:
            continue  # Need at least 3 providers for meaningful concentration
        total_payments = sum(ent.estimated_annual_medicare_payments or 0.0 for ent in ents)
        if total_payments <= 0:
            continue

        shares = []
        top_name = ""
        top_share = 0.0
        for ent in ents:
            pmt = ent.estimated_annual_medicare_payments or 0.0
            share = (pmt / total_payments) * 100.0 if total_payments > 0 else 0.0
            shares.append(share)
            if share > top_share:
                top_share = share
                top_name = ent.name or ""

        hhi = sum(s * s for s in shares)

        if hhi >= 2500:
            level = "high"
        elif hhi >= 1500:
            level = "moderate"
        else:
            level = "low"

        results.append({
            "area": f"{city.title()}, {st}",
            "area_type": "city",
            "total_medicare_payments": round(total_payments, 2),
            "entity_count": len(ents),
            "top_provider": {
                "name": top_name,
                "share_pct": round(top_share, 2),
            },
            "hhi": round(hhi, 2),
            "concentration_level": level,
        })

    results.sort(key=lambda r: r["hhi"], reverse=True)
    return results
