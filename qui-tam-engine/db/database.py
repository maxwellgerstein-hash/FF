"""
SQLAlchemy engine and session factory.
Uses synchronous SQLAlchemy with SQLite for Phase 1.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    """Get a database session. Use in a with statement or try/finally."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from db.models import (  # noqa: F401 — ensure models are registered
        Entity, SourceRecord, SignalRecord, CaseLeadRecord,
        DataSourceStatus, LEIEIndex, EntityRelationship,
        CaseCluster, KnownFraudCase, AuditLog,
    )
    Base.metadata.create_all(bind=engine)
