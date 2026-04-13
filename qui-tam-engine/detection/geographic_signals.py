"""
Geographic & Market-Level Fraud Signals (GEO01–GEO03).

Detects market saturation anomalies, geographic clustering with known fraud,
and cross-state operators.
"""

from datetime import date
from detection.base import Signal
from db.models import Entity, SourceRecord, CaseLeadRecord
from config import HIGH_FRAUD_STATES

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


def detect_geographic_signals(entity, hospice_measures: dict, db_session) -> list[Signal]:
    """Run geographic fraud detection signals."""
    signals = []

    signals.extend(_geo01_market_saturation(entity, db_session))
    signals.extend(_geo02_fraud_cluster_proximity(entity, db_session))
    signals.extend(_geo03_high_fraud_state(entity, db_session))

    return signals


def _geo01_market_saturation(entity, db_session) -> list[Signal]:
    """GEO01: Unusually high hospice density in entity's city."""
    signals = []

    if not entity.city or not entity.state:
        return signals

    city_upper = entity.city.upper().strip()
    state = entity.state.upper().strip()

    # Count hospices in same city
    same_city_count = (
        db_session.query(Entity)
        .filter(
            Entity.state == entity.state,
        )
        .count()
    )

    same_city_exact = (
        db_session.query(Entity)
        .filter(
            Entity.city == entity.city,
            Entity.state == entity.state,
        )
        .count()
    )

    # State average: total entities / estimated cities with hospices
    # Rough estimate: most states have hospices in 20-50 cities
    avg_per_city = max(same_city_count / 30, 1)

    if same_city_exact > avg_per_city * 3 and same_city_exact >= 10:
        signals.append(Signal(
            signal_code="GEO01",
            signal_category="geographic_fraud",
            severity="MEDIUM",
            type="STATISTICAL",
            weight=5,
            description=(
                f"{same_city_exact} hospices in {city_upper}, {state} — "
                f"high market concentration (state avg ~{avg_per_city:.0f} per city)"
            ),
            evidence={
                "city": city_upper,
                "state": state,
                "hospices_in_city": same_city_exact,
                "state_total": same_city_count,
                "est_avg_per_city": round(avg_per_city, 1),
                "ratio": round(same_city_exact / avg_per_city, 1),
            },
            data_source="cms_hospice_general",
            fca_provision="31 USC §3729 — geographic fraud clustering indicator",
        ))

    return signals


def _geo02_fraud_cluster_proximity(entity, db_session) -> list[Signal]:
    """GEO02: Entity in same city as a known DOJ settlement target."""
    signals = []

    if not entity.city or not entity.state:
        return signals

    city_upper = entity.city.upper().strip()
    state = entity.state.upper().strip()

    doj_records = (
        db_session.query(SourceRecord)
        .filter(SourceRecord.source_name == "doj_settlement")
        .all()
    )

    nearby_settlements = []
    for record in doj_records:
        data = record.get_data()
        doj_state = (data.get("state", data.get("location", "")) or "").upper().strip()
        doj_city = (data.get("city", "") or "").upper().strip()

        # Match on state (city matching is less reliable due to naming variations)
        if doj_state == state or state in doj_state:
            nearby_settlements.append({
                "entity_name": data.get("entity_name", data.get("defendant", "")),
                "settlement_amount": data.get("settlement_amount", ""),
                "date": data.get("settlement_date", data.get("date", "")),
                "city": doj_city,
            })

    if len(nearby_settlements) >= 2:
        signals.append(Signal(
            signal_code="GEO02",
            signal_category="geographic_fraud",
            severity="MEDIUM",
            type="STATISTICAL",
            weight=6,
            description=(
                f"Entity in {state} where {len(nearby_settlements)} prior DOJ hospice fraud "
                f"settlements occurred — geographic fraud cluster"
            ),
            evidence={
                "state": state,
                "city": city_upper,
                "nearby_settlements": nearby_settlements[:5],
            },
            data_source="doj_settlement + cms_hospice_general",
            fca_provision="31 USC §3729 — operating in known fraud cluster",
        ))

    return signals


def _geo03_high_fraud_state(entity, db_session) -> list[Signal]:
    """GEO03: Entity in a state with disproportionately high hospice fraud rates."""
    signals = []

    state = (entity.state or "").upper().strip()
    if not state:
        return signals

    if state in HIGH_FRAUD_STATES:
        bonus = HIGH_FRAUD_STATES[state]
        signals.append(Signal(
            signal_code="GEO03",
            signal_category="geographic_fraud",
            severity="LOW",
            type="STATISTICAL",
            weight=3,
            description=(
                f"Entity located in {state} — state with disproportionately high "
                f"hospice fraud enforcement activity ({bonus*100:.0f}% risk premium)"
            ),
            evidence={
                "state": state,
                "risk_premium": bonus,
                "source": "DOJ enforcement data, OIG Work Plan",
            },
            data_source="doj_settlement + cms_hospice_general",
            fca_provision="31 USC §3729 — geographic risk factor",
        ))

    return signals
