"""
Entity Resolution Engine.

Resolves records from multiple data sources into canonical entities.
Phase 1: CMS Hospice Compare (anchor) + NPPES (enrichment).

Resolution priority:
  1. Exact identifier match (NPI, CCN)
  2. Fuzzy name + address match (Jaro-Winkler >= 0.88)
  3. Officer overlap
  4. Phone/fax match
  5. No match → create new entity
"""

import re
from datetime import datetime

from rapidfuzz import fuzz

from db.models import Entity, SourceRecord


def normalize_name(name: str) -> str:
    """Normalize an entity name for matching."""
    if not name:
        return ""
    suffixes = [
        "LLC", "INC", "CORP", "LTD", "LP", "LLP", "PC", "PA", "PLLC",
        "CO", "COMPANY", "GROUP", "HOLDINGS", "ENTERPRISES", "SERVICES",
        "ASSOCIATES", "PARTNERS", "INTERNATIONAL", "DBA",
    ]
    name = name.upper().strip()
    name = re.sub(r'[.,\-\'\"()&]', " ", name)
    for suffix in suffixes:
        name = re.sub(rf"\b{suffix}\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def normalize_address(address: str) -> str:
    """Normalize an address for matching."""
    if not address:
        return ""
    addr = address.upper().strip()
    replacements = {
        r"\bSTREET\b": "ST",
        r"\bAVENUE\b": "AVE",
        r"\bBOULEVARD\b": "BLVD",
        r"\bDRIVE\b": "DR",
        r"\bLANE\b": "LN",
        r"\bROAD\b": "RD",
        r"\bSUITE\b": "STE",
        r"\bAPARTMENT\b": "APT",
    }
    for pattern, replacement in replacements.items():
        addr = re.sub(pattern, replacement, addr)
    addr = re.sub(r"[.,#]", "", addr)
    addr = re.sub(r"\s+", " ", addr).strip()
    return addr


def safe_int(val) -> int:
    """Safely convert a value to int."""
    if val is None or val == "" or str(val).strip().lower() in ("not available", "nan", "none"):
        return 0
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0


class EntityResolver:
    """Resolves records across data sources into canonical entities."""

    def resolve_hospice_entities(self, db_session) -> dict:
        """
        Phase 1 resolution:
        1. Create canonical entities from CMS Hospice Compare (anchor)
        2. Match NPPES bulk records by name + state (fuzzy)
        3. Store authorized official info for LEIE cross-reference
        """
        stats = {"entities_created": 0, "nppes_matched": 0}

        # Step 1: Create entities from Hospice Compare
        hospice_records = (
            db_session.query(SourceRecord)
            .filter(SourceRecord.source_name == "cms_hospice_general")
            .all()
        )

        for record in hospice_records:
            data = record.get_data()
            name = data.get("Facility Name", "").strip()
            ccn = data.get("CMS Certification Number (CCN)", "").strip()
            address = data.get("Address Line 1", "").strip()
            city = data.get("City/Town", "").strip()
            state = data.get("State", "").strip()

            if not name or not ccn:
                continue

            # Check if entity already exists (by CCN)
            existing = db_session.query(Entity).filter(Entity.ccn == ccn).first()
            if existing:
                continue

            episodes = safe_int(
                data.get("# of Total Episodes")
                or data.get("Total Number Of Episodes (unduplicated)")
                or data.get("total_episodes")
            )
            patients = safe_int(
                data.get("# of Total Patients")
                or data.get("Total Number Of Patients (unduplicated)")
                or data.get("total_patients")
            )

            # Get authorized official from CMS data (if available)
            auth_first = (
                data.get("Authorized Official First Name", "")
                or data.get("auth_first", "")
            ).strip()
            auth_last = (
                data.get("Authorized Official Last Name", "")
                or data.get("auth_last", "")
            ).strip()

            entity = Entity(
                name=name,
                name_normalized=normalize_name(name),
                entity_type="healthcare_provider",
                ccn=ccn,
                state=state,
                city=city,
                address=address,
                address_normalized=normalize_address(address),
                telephone=data.get("Telephone Number", "").strip(),
                certification_date=data.get("Certification Date", ""),
                total_episodes=episodes,
                total_patients=patients,
                authorized_official_first_name=auth_first or None,
                authorized_official_last_name=auth_last or None,
                # Estimate: episodes x median_LOS x daily_rate (conservative)
                estimated_annual_medicare_payments=float(episodes) * 18 * 195.0,
                created_at=datetime.now().isoformat(),
            )

            db_session.add(entity)
            stats["entities_created"] += 1

        db_session.flush()  # Generate IDs

        # Set entity_ids on source records
        for record in hospice_records:
            data = record.get_data()
            ccn = data.get("CMS Certification Number (CCN)", "").strip()
            entity = db_session.query(Entity).filter(Entity.ccn == ccn).first()
            if entity:
                record.entity_id = entity.id

        db_session.commit()

        # Step 2: Match NPPES records to entities by organization name + state
        nppes_records = (
            db_session.query(SourceRecord)
            .filter(SourceRecord.source_name == "nppes_bulk")
            .all()
        )

        # Build lookup by state for faster matching
        entities_by_state: dict[str, list[Entity]] = {}
        for entity in db_session.query(Entity).all():
            entities_by_state.setdefault(entity.state, []).append(entity)

        for record in nppes_records:
            data = record.get_data()
            npi = data.get("NPI", "").strip()
            org_name = data.get(
                "Provider Organization Name (Legal Business Name)", ""
            ).strip()
            state = data.get(
                "Provider Business Practice Location Address State Name", ""
            ).strip()
            auth_last = data.get("Authorized Official Last Name", "").strip()
            auth_first = data.get("Authorized Official First Name", "").strip()

            if not org_name or not state:
                continue

            candidates = entities_by_state.get(state, [])
            name_norm = normalize_name(org_name)

            best_match = None
            best_score = 0
            for candidate in candidates:
                score = fuzz.token_sort_ratio(name_norm, candidate.name_normalized)
                if score > best_score and score >= 85:
                    best_score = score
                    best_match = candidate

            if best_match:
                record.entity_id = best_match.id

                if npi and not best_match.npi:
                    best_match.npi = npi
                if auth_last and not best_match.authorized_official_last_name:
                    best_match.authorized_official_last_name = auth_last
                    best_match.authorized_official_first_name = auth_first

                stats["nppes_matched"] += 1

        db_session.commit()
        return stats
