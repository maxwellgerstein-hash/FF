"""
Central registry of all signal codes.
Maps signal codes to their metadata for reference and validation.
"""

SIGNAL_REGISTRY = {
    # ── Category A: Hospice Fraud ──
    "HF01": {"category": "hospice_fraud", "name": "Ghost hospice — no physical location", "type": "RULE_VIOLATION", "default_weight": 10},
    "HF02": {"category": "hospice_fraud", "name": "Abnormal average length of stay", "type": "STATISTICAL", "default_weight": 6},
    "HF03": {"category": "hospice_fraud", "name": "Abnormally low mortality rate", "type": "STATISTICAL", "default_weight": 7},
    "HF04": {"category": "hospice_fraud", "name": "High live discharge rate", "type": "STATISTICAL", "default_weight": 7},
    "HF05": {"category": "hospice_fraud", "name": "Billing exceeds reasonable capacity", "type": "STATISTICAL", "default_weight": 7},
    "HF06": {"category": "hospice_fraud", "name": "Provider on OIG exclusion list", "type": "RULE_VIOLATION", "default_weight": 10},
    "HF07": {"category": "hospice_fraud", "name": "New entity, immediate high billing", "type": "STATISTICAL", "default_weight": 6},
    "HF08": {"category": "hospice_fraud", "name": "Clustering of hospices at same address", "type": "STATISTICAL", "default_weight": 8},
    "HF09": {"category": "hospice_fraud", "name": "Physician certifying impossibly many patients", "type": "RULE_VIOLATION", "default_weight": 9},
    "HF10": {"category": "hospice_fraud", "name": "Geographic impossibility", "type": "STATISTICAL", "default_weight": 7},
    "HF11": {"category": "hospice_fraud", "name": "No associated referring physicians", "type": "STATISTICAL", "default_weight": 5},
    "HF12": {"category": "hospice_fraud", "name": "Owner/operator linked to prior fraud", "type": "RULE_VIOLATION", "default_weight": 10},
}

# Codes implemented in Phase 1 (data available from Hospice Compare + LEIE + NPPES)
PHASE_1_SIGNALS = {"HF01", "HF02", "HF03", "HF04", "HF06", "HF07", "HF08"}

# Codes requiring additional data sources (Phase 2+)
DEFERRED_SIGNALS = {
    "HF05": "Requires claims-level data (Phase 2)",
    "HF09": "Requires claims-level physician data (Phase 2)",
    "HF10": "Requires beneficiary geographic data (Phase 2)",
    "HF11": "Requires referring physician data (Phase 2)",
    "HF12": "Requires CourtListener integration (Phase 5)",
}
