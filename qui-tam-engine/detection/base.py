"""
Base detection classes and core data structures.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
import json


@dataclass
class Signal:
    """A single fraud signal detected for an entity."""

    signal_code: str              # e.g., "HF01"
    signal_category: str          # e.g., "hospice_fraud"
    severity: str                 # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    type: str                     # "RULE_VIOLATION" or "STATISTICAL"
    weight: int                   # 1-10
    description: str              # Human-readable explanation
    evidence: dict                # Structured evidence
    data_source: str              # Which data source(s) produced this signal
    fca_provision: str            # e.g., "31 USC Section 3729(a)(1)(A)"
    violation_date_start: Optional[date] = None  # When conduct BEGAN
    violation_date_end: Optional[date] = None    # When last observed

    def evidence_json(self) -> str:
        """Serialize evidence dict to JSON string for SQLite storage."""
        return json.dumps(self.evidence, default=str)


@dataclass
class CaseScore:
    """Scoring output for a case lead."""

    score: float                  # 0-100
    confidence: float             # 0.00-1.00
    govt_loss: float
    estimated_claim_count: int
    treble_damages: float
    double_damages: float
    penalties_low: float          # At $13,946/claim
    penalties_high: float         # At $27,894/claim
    total_recovery_low: float     # double_damages + penalties_low
    total_recovery_high: float    # treble_damages + penalties_high
    relator_share_low: float      # 15% of total_recovery_low
    relator_share_high: float     # 30% of total_recovery_high
    doj_intervention_likelihood: str  # "HIGH", "MEDIUM", "LOW"
