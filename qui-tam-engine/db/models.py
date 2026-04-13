"""
SQLAlchemy ORM models for the Qui Tam Case Engine.

SQLite compatibility:
  - JSONB columns → TEXT (json.dumps on write, json.loads on read)
  - TEXT[] arrays → TEXT (json.dumps(list))
  - SERIAL → INTEGER PRIMARY KEY AUTOINCREMENT
  - DECIMAL → REAL
  - BOOLEAN → INTEGER (0/1)
  - TIMESTAMP → TEXT (ISO strings)
"""

from sqlalchemy import Column, Integer, Text, Float as Real
from db.database import Base
import json


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False, default="healthcare_provider")
    npi = Column(Text, index=True)
    uei = Column(Text, index=True)
    ein = Column(Text, index=True)
    cik = Column(Text, index=True)
    ccn = Column(Text, index=True)  # CMS Certification Number (hospice-specific)
    state = Column(Text)
    city = Column(Text)
    address = Column(Text)
    address_normalized = Column(Text, index=True)
    is_residential_address = Column(Integer, default=0)
    is_virtual_office = Column(Integer, default=0)
    telephone = Column(Text)
    first_seen_date = Column(Text)
    last_activity_date = Column(Text)
    certification_date = Column(Text)
    total_govt_payments = Column(Real, default=0.0)
    total_episodes = Column(Integer, default=0)
    total_patients = Column(Integer, default=0)
    estimated_annual_medicare_payments = Column(Real, default=0.0)
    authorized_official_first_name = Column(Text)
    authorized_official_last_name = Column(Text)
    fraud_hotspot_msa = Column(Text)
    is_dismissed = Column(Integer, default=0)
    dismissed_reason = Column(Text)
    dismissed_at = Column(Text)
    created_at = Column(Text)
    updated_at = Column(Text)


class SourceRecord(Base):
    __tablename__ = "source_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(Integer, index=True)
    source_name = Column(Text, nullable=False, index=True)
    source_identifier = Column(Text, index=True)
    raw_data = Column(Text, nullable=False)  # JSON string
    ingested_at = Column(Text)

    def get_data(self) -> dict:
        return json.loads(self.raw_data) if self.raw_data else {}

    def set_data(self, data: dict):
        self.raw_data = json.dumps(data, default=str)


class SignalRecord(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(Integer, nullable=False, index=True)
    signal_code = Column(Text, nullable=False)
    signal_category = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    signal_type = Column(Text, nullable=False)  # "RULE_VIOLATION" or "STATISTICAL"
    weight = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    evidence = Column(Text, nullable=False)  # JSON string
    data_source = Column(Text, nullable=False)
    fca_provision = Column(Text)
    violation_date_start = Column(Text)
    violation_date_end = Column(Text)
    detected_at = Column(Text)
    is_suppressed = Column(Integer, default=0)
    suppressed_reason = Column(Text)


class CaseLeadRecord(Base):
    __tablename__ = "case_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(Integer, index=True)
    cluster_id = Column(Integer)
    case_score = Column(Real, nullable=False)
    confidence = Column(Real, nullable=False)
    estimated_govt_loss = Column(Real)
    estimated_claim_count = Column(Integer)
    treble_damages = Column(Real)
    double_damages = Column(Real)
    penalties_low = Column(Real)
    penalties_high = Column(Real)
    total_recovery_low = Column(Real)
    total_recovery_high = Column(Real)
    relator_share_low = Column(Real)
    relator_share_high = Column(Real)
    legal_theory = Column(Text)
    fca_provisions = Column(Text)  # JSON array string
    fraud_category = Column(Text)
    public_disclosure_risk = Column(Text)
    first_to_file_risk = Column(Text)
    rule_9b_sufficiency = Column(Text)
    doj_intervention_likelihood = Column(Text)
    sol_expiry = Column(Text)
    recommended_counsel_type = Column(Text)
    llm_narrative = Column(Text)
    signal_ids = Column(Text)  # JSON array of signal IDs
    status = Column(Text, default="NEW")
    created_at = Column(Text)


class CaseCluster(Base):
    __tablename__ = "case_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_name = Column(Text, nullable=False)
    cluster_type = Column(Text, nullable=False)
    entity_ids = Column(Text, nullable=False)  # JSON array
    combined_govt_loss = Column(Real)
    created_at = Column(Text)


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(Text, nullable=False, unique=True)
    last_successful_pull = Column(Text)
    records_pulled = Column(Integer)
    records_updated = Column(Integer)
    data_vintage_date = Column(Text)
    pull_status = Column(Text, nullable=False)
    error_message = Column(Text)
    next_scheduled_pull = Column(Text)


class LEIEIndex(Base):
    """Pre-built index of LEIE names for fast fuzzy matching."""
    __tablename__ = "leie_index"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name_normalized = Column(Text, nullable=False, index=True)
    state = Column(Text, index=True)
    npi = Column(Text, index=True)
    exclusion_type = Column(Text)
    exclusion_date = Column(Text)
    raw_record = Column(Text)  # JSON string


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id_a = Column(Integer, index=True)
    entity_id_b = Column(Integer, index=True)
    relationship_type = Column(Text, nullable=False)
    strength = Column(Real)
    evidence = Column(Text)  # JSON string
    detected_at = Column(Text)


class KnownFraudCase(Base):
    __tablename__ = "known_fraud_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_name = Column(Text, nullable=False)
    entity_npi = Column(Text)
    entity_uei = Column(Text)
    case_type = Column(Text, nullable=False)
    doj_press_release_url = Column(Text)
    settlement_amount = Column(Real)
    settlement_date = Column(Text)
    would_engine_flag = Column(Integer)  # 0/1
    engine_score = Column(Real)
    created_at = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(Text, nullable=False)
    entity_id = Column(Integer)
    details = Column(Text)  # JSON string
    created_at = Column(Text)
