"""
Case Clustering Engine.

Groups related entity leads into unified case packages.
E.g., 14 hospices at the same address = 1 case, not 14.

Clustering criteria:
  1. Shared address (>=3 entities at same address)
  2. Shared officers/owners (common authorized official)
  3. Network relationships (graph communities)
"""

import json
from datetime import datetime
from db.models import Entity, CaseLeadRecord, CaseCluster, EntityRelationship


def cluster_case_leads(db_session) -> dict:
    """
    Group related case leads into clusters.

    Phase 1 focuses on:
      - Shared address clustering
      - Shared authorized official clustering
    """
    stats = {"clusters_created": 0, "leads_clustered": 0}

    # Get all case leads with entities
    leads = db_session.query(CaseLeadRecord).filter(
        CaseLeadRecord.entity_id.isnot(None)
    ).all()

    if not leads:
        return stats

    lead_entity_ids = {lead.entity_id for lead in leads}

    # ── Strategy 1: Shared address clustering ──
    entities = db_session.query(Entity).filter(
        Entity.id.in_(lead_entity_ids)
    ).all()

    # Group by normalized address
    addr_groups: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.address_normalized:
            addr_groups.setdefault(entity.address_normalized, []).append(entity)

    for addr, group_entities in addr_groups.items():
        if len(group_entities) < 2:
            continue

        entity_ids = [e.id for e in group_entities]
        combined_loss = sum(
            lead.estimated_govt_loss or 0
            for lead in leads
            if lead.entity_id in entity_ids
        )

        cluster = CaseCluster(
            cluster_name=(
                f"{group_entities[0].address} \u2014 "
                f"{len(group_entities)} entities"
            ),
            cluster_type="shared_address",
            entity_ids=json.dumps(entity_ids),
            combined_govt_loss=combined_loss,
            created_at=datetime.now().isoformat(),
        )
        db_session.add(cluster)
        db_session.flush()

        # Link leads to cluster
        for lead in leads:
            if lead.entity_id in entity_ids:
                lead.cluster_id = cluster.id
                stats["leads_clustered"] += 1

        # Create entity relationships
        for i, e1 in enumerate(group_entities):
            for e2 in group_entities[i + 1:]:
                rel = EntityRelationship(
                    entity_id_a=e1.id,
                    entity_id_b=e2.id,
                    relationship_type="shared_address",
                    strength=1.0,
                    evidence=json.dumps({
                        "address": e1.address,
                        "address_normalized": e1.address_normalized,
                    }),
                    detected_at=datetime.now().isoformat(),
                )
                db_session.add(rel)

        stats["clusters_created"] += 1

    # ── Strategy 2: Shared authorized official clustering ──
    official_groups: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.authorized_official_last_name:
            key = (
                f"{(entity.authorized_official_first_name or '').upper().strip()} "
                f"{entity.authorized_official_last_name.upper().strip()}"
            )
            if len(key.strip()) > 2:
                official_groups.setdefault(key, []).append(entity)

    for official, group_entities in official_groups.items():
        if len(group_entities) < 2:
            continue

        entity_ids = [e.id for e in group_entities]

        # Skip if already clustered by address
        already_clustered = all(
            any(
                lead.cluster_id is not None
                for lead in leads
                if lead.entity_id == eid
            )
            for eid in entity_ids
        )
        if already_clustered:
            continue

        combined_loss = sum(
            lead.estimated_govt_loss or 0
            for lead in leads
            if lead.entity_id in entity_ids
        )

        cluster = CaseCluster(
            cluster_name=f"Shared Official: {official} \u2014 {len(group_entities)} entities",
            cluster_type="shared_owner",
            entity_ids=json.dumps(entity_ids),
            combined_govt_loss=combined_loss,
            created_at=datetime.now().isoformat(),
        )
        db_session.add(cluster)
        db_session.flush()

        for lead in leads:
            if lead.entity_id in entity_ids and lead.cluster_id is None:
                lead.cluster_id = cluster.id
                stats["leads_clustered"] += 1

        for i, e1 in enumerate(group_entities):
            for e2 in group_entities[i + 1:]:
                rel = EntityRelationship(
                    entity_id_a=e1.id,
                    entity_id_b=e2.id,
                    relationship_type="shared_officer",
                    strength=0.9,
                    evidence=json.dumps({"shared_official": official}),
                    detected_at=datetime.now().isoformat(),
                )
                db_session.add(rel)

        stats["clusters_created"] += 1

    db_session.commit()
    return stats
