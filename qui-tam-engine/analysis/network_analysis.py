"""
Network analysis for hospice fraud detection.

Builds entity relationship graphs, detects communities of related entities,
and identifies referral concentration patterns that may indicate coordinated fraud.
"""

import json
from collections import defaultdict, deque

from db.models import Entity, EntityRelationship, CaseLeadRecord, SignalRecord, SourceRecord
from db.database import SessionLocal


def _normalize_for_comparison(text: str) -> str:
    """Lowercase, strip whitespace, remove common suffixes for name comparison."""
    if not text:
        return ""
    t = text.strip().lower()
    for suffix in [" llc", " inc", " corp", " ltd", " hospice", " home health",
                   " health services", " healthcare", " health care", ",", "."]:
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return t


def _names_similar(name_a: str, name_b: str) -> bool:
    """Check if two entity names are similar (share significant tokens)."""
    a_tokens = set(_normalize_for_comparison(name_a).split())
    b_tokens = set(_normalize_for_comparison(name_b).split())
    # Remove very common stop-words
    stop = {"of", "the", "and", "a", "an", "in", "at", "for", "to"}
    a_tokens -= stop
    b_tokens -= stop
    if not a_tokens or not b_tokens:
        return False
    overlap = a_tokens & b_tokens
    shorter = min(len(a_tokens), len(b_tokens))
    return shorter > 0 and len(overlap) / shorter >= 0.5


# ---------------------------------------------------------------------------
# Union-Find for community detection
# ---------------------------------------------------------------------------


class _UnionFind:
    """Simple union-find (disjoint set) data structure."""

    def __init__(self, elements):
        self.parent = {e: e for e in elements}
        self.rank = {e: 0 for e in elements}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def components(self):
        groups = defaultdict(list)
        for e in self.parent:
            groups[self.find(e)].append(e)
        return list(groups.values())


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def build_entity_network(db_session) -> dict:
    """
    Build a network graph of entity relationships.

    Returns a dict with:
    - nodes: list of {id, name, state, score, signals, node_type}
    - edges: list of {source, target, relationship_type, strength}
    - communities: list of lists (entity IDs grouped by community)
    - stats: {total_nodes, total_edges, communities_found, largest_community}
    """
    # ------------------------------------------------------------------
    # 1. Query entities that have case leads
    # ------------------------------------------------------------------
    lead_entity_ids = {
        row[0]
        for row in db_session.query(CaseLeadRecord.entity_id).distinct().all()
        if row[0] is not None
    }

    if not lead_entity_ids:
        return {
            "nodes": [],
            "edges": [],
            "communities": [],
            "stats": {
                "total_nodes": 0,
                "total_edges": 0,
                "communities_found": 0,
                "largest_community": 0,
            },
        }

    entities = (
        db_session.query(Entity)
        .filter(Entity.id.in_(lead_entity_ids))
        .all()
    )
    entity_map = {e.id: e for e in entities}

    # Gather per-entity signal counts and best case score
    signal_counts = defaultdict(int)
    for row in (
        db_session.query(SignalRecord.entity_id)
        .filter(SignalRecord.entity_id.in_(lead_entity_ids))
        .all()
    ):
        signal_counts[row[0]] += 1

    lead_scores = {}
    for lead in (
        db_session.query(CaseLeadRecord)
        .filter(CaseLeadRecord.entity_id.in_(lead_entity_ids))
        .all()
    ):
        eid = lead.entity_id
        if eid not in lead_scores or (lead.case_score or 0) > lead_scores[eid]:
            lead_scores[eid] = lead.case_score or 0.0

    # ------------------------------------------------------------------
    # 2. Build nodes
    # ------------------------------------------------------------------
    nodes = []
    for eid, ent in entity_map.items():
        nodes.append({
            "id": eid,
            "name": ent.name or "",
            "state": ent.state or "",
            "score": lead_scores.get(eid, 0.0),
            "signals": signal_counts.get(eid, 0),
            "node_type": ent.entity_type or "healthcare_provider",
        })

    # ------------------------------------------------------------------
    # 3. Build edges from stored EntityRelationships
    # ------------------------------------------------------------------
    edges = []
    seen_edges = set()

    relationships = (
        db_session.query(EntityRelationship)
        .filter(
            EntityRelationship.entity_id_a.in_(lead_entity_ids)
            | EntityRelationship.entity_id_b.in_(lead_entity_ids)
        )
        .all()
    )

    for rel in relationships:
        a, b = rel.entity_id_a, rel.entity_id_b
        if a not in entity_map or b not in entity_map:
            continue
        edge_key = (min(a, b), max(a, b), rel.relationship_type or "")
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edges.append({
            "source": a,
            "target": b,
            "relationship_type": rel.relationship_type or "unknown",
            "strength": rel.strength if rel.strength is not None else 0.5,
        })

    # ------------------------------------------------------------------
    # 4. Add implied relationships
    # ------------------------------------------------------------------
    entity_list = list(entity_map.values())

    # Pre-index by authorized official last name
    by_auth_last = defaultdict(list)
    for ent in entity_list:
        last = (ent.authorized_official_last_name or "").strip().lower()
        if last:
            by_auth_last[last].append(ent.id)

    for last, ids in by_auth_last.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                edge_key = (min(ids[i], ids[j]), max(ids[i], ids[j]), "same_authorized_official")
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "source": ids[i],
                        "target": ids[j],
                        "relationship_type": "same_authorized_official",
                        "strength": 0.9,
                    })

    # Pre-index by normalized address
    by_address = defaultdict(list)
    for ent in entity_list:
        addr = (ent.address_normalized or "").strip().lower()
        if addr:
            by_address[addr].append(ent.id)

    for addr, ids in by_address.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                edge_key = (min(ids[i], ids[j]), max(ids[i], ids[j]), "same_address")
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "source": ids[i],
                        "target": ids[j],
                        "relationship_type": "same_address",
                        "strength": 1.0,
                    })

    # Same city + similar name
    by_city = defaultdict(list)
    for ent in entity_list:
        city = (ent.city or "").strip().lower()
        if city:
            by_city[city].append(ent)

    for city, ents in by_city.items():
        if len(ents) < 2:
            continue
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                if _names_similar(ents[i].name, ents[j].name):
                    a_id, b_id = ents[i].id, ents[j].id
                    edge_key = (min(a_id, b_id), max(a_id, b_id), "same_city_similar_name")
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({
                            "source": a_id,
                            "target": b_id,
                            "relationship_type": "same_city_similar_name",
                            "strength": 0.5,
                        })

    # ------------------------------------------------------------------
    # 5. Community detection via union-find (connected components)
    # ------------------------------------------------------------------
    uf = _UnionFind(entity_map.keys())
    for edge in edges:
        uf.union(edge["source"], edge["target"])
    communities = uf.components()
    # Sort communities largest-first
    communities.sort(key=len, reverse=True)

    # ------------------------------------------------------------------
    # 6. Return graph data
    # ------------------------------------------------------------------
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": communities,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "communities_found": len(communities),
            "largest_community": len(communities[0]) if communities else 0,
        },
    }


def find_referral_concentration(db_session) -> list[dict]:
    """
    Find authorized officials who control multiple entities - potential referral mills.

    Returns a list of dicts sorted by entity count descending:
    {
        official_name: str,
        entity_count: int,
        entities: list[{id, name, state, ccn, score}],
        combined_govt_loss: float,
        combined_signals: int,
    }
    """
    # Gather entities with authorized officials
    entities = (
        db_session.query(Entity)
        .filter(Entity.authorized_official_last_name.isnot(None))
        .filter(Entity.authorized_official_last_name != "")
        .all()
    )

    # Group by normalized official name (last, first)
    by_official = defaultdict(list)
    for ent in entities:
        last = (ent.authorized_official_last_name or "").strip().lower()
        first = (ent.authorized_official_first_name or "").strip().lower()
        key = f"{last}, {first}" if first else last
        if key:
            by_official[key].append(ent)

    # Filter to officials with multiple entities
    results = []
    for official_key, ent_list in by_official.items():
        if len(ent_list) < 2:
            continue

        ent_ids = [e.id for e in ent_list]

        # Aggregate case lead scores and loss
        leads = (
            db_session.query(CaseLeadRecord)
            .filter(CaseLeadRecord.entity_id.in_(ent_ids))
            .all()
        )
        best_scores = {}
        total_loss = 0.0
        for lead in leads:
            eid = lead.entity_id
            if eid not in best_scores or (lead.case_score or 0) > best_scores[eid]:
                best_scores[eid] = lead.case_score or 0.0
            total_loss += lead.estimated_govt_loss or 0.0

        # Signal counts
        signal_total = (
            db_session.query(SignalRecord)
            .filter(SignalRecord.entity_id.in_(ent_ids))
            .count()
        )

        # Build display name
        parts = official_key.split(", ")
        if len(parts) == 2:
            display = f"{parts[1].title()} {parts[0].title()}"
        else:
            display = official_key.title()

        results.append({
            "official_name": display,
            "entity_count": len(ent_list),
            "entities": [
                {
                    "id": e.id,
                    "name": e.name or "",
                    "state": e.state or "",
                    "ccn": e.ccn or "",
                    "score": best_scores.get(e.id, 0.0),
                }
                for e in ent_list
            ],
            "combined_govt_loss": total_loss,
            "combined_signals": signal_total,
        })

    results.sort(key=lambda r: r["entity_count"], reverse=True)
    return results
