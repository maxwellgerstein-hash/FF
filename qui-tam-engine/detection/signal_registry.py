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

    # ── Category B: Home Health Fraud ──
    "HH01": {"category": "home_health_fraud", "name": "Ghost home health agency", "type": "RULE_VIOLATION", "default_weight": 10},
    "HH02": {"category": "home_health_fraud", "name": "Abnormal visit frequency", "type": "STATISTICAL", "default_weight": 7},
    "HH03": {"category": "home_health_fraud", "name": "Provider on OIG exclusion list", "type": "RULE_VIOLATION", "default_weight": 10},

    # ── Category C: Medicare/Medicaid Billing Fraud ──
    "BF01": {"category": "billing_fraud", "name": "Upcoding — billing higher-level services", "type": "STATISTICAL", "default_weight": 8},
    "BF02": {"category": "billing_fraud", "name": "Unbundling — splitting services for higher reimbursement", "type": "STATISTICAL", "default_weight": 7},
    "BF03": {"category": "billing_fraud", "name": "Phantom billing — services never rendered", "type": "RULE_VIOLATION", "default_weight": 10},

    # ── Category D: DME Fraud ──
    "DM01": {"category": "dme_fraud", "name": "DME supplier at residential/virtual address", "type": "RULE_VIOLATION", "default_weight": 9},
    "DM02": {"category": "dme_fraud", "name": "Excluded DME supplier still billing", "type": "RULE_VIOLATION", "default_weight": 10},

    # ── Category E: Kickback / Anti-Kickback Statute ──
    "KB01": {"category": "pharma_kickback", "name": "Suspected referral kickback pattern", "type": "STATISTICAL", "default_weight": 8},
    "KB02": {"category": "pharma_kickback", "name": "Abnormal prescribing concentration", "type": "STATISTICAL", "default_weight": 7},

    # ── Category F: Government Contract Fraud ──
    "GC01": {"category": "govt_contract_fraud", "name": "False certification on government contract", "type": "RULE_VIOLATION", "default_weight": 9},
    "GC02": {"category": "cybersecurity_false_cert", "name": "Cybersecurity compliance false certification", "type": "RULE_VIOLATION", "default_weight": 9},

    # ── Category G: Financial Program Fraud ──
    "FP01": {"category": "ppp_fraud", "name": "PPP loan fraud — false application", "type": "RULE_VIOLATION", "default_weight": 10},
    "FP02": {"category": "fha_fraud", "name": "FHA mortgage fraud", "type": "RULE_VIOLATION", "default_weight": 9},
    "FP03": {"category": "set_aside_fraud", "name": "Small business set-aside fraud", "type": "RULE_VIOLATION", "default_weight": 8},

    # ── Category H: Telehealth Fraud ──
    "TH01": {"category": "telehealth_fraud", "name": "Telehealth services billed without patient contact", "type": "RULE_VIOLATION", "default_weight": 9},
    "TH02": {"category": "telehealth_fraud", "name": "Abnormal telehealth volume", "type": "STATISTICAL", "default_weight": 7},
}

# Codes implemented (data available from current sources)
IMPLEMENTED_SIGNALS = {"HF01", "HF02", "HF03", "HF04", "HF06", "HF07", "HF08"}

# Codes requiring additional data sources
DEFERRED_SIGNALS = {
    "HF05": "Requires claims-level data",
    "HF09": "Requires claims-level physician data",
    "HF10": "Requires beneficiary geographic data",
    "HF11": "Requires referring physician data",
    "HF12": "Requires CourtListener integration",
    "HH01": "Requires home health CMS data",
    "HH02": "Requires home health claims data",
    "HH03": "Requires home health CMS data + LEIE cross-reference",
    "BF01": "Requires Medicare Part B claims data",
    "BF02": "Requires Medicare Part B claims data",
    "BF03": "Requires Medicare Part B claims data",
    "DM01": "Requires DME supplier CMS data",
    "DM02": "Requires DME supplier CMS data + LEIE cross-reference",
    "KB01": "Requires physician payment / Open Payments data",
    "KB02": "Requires prescriber-level CMS data",
    "GC01": "Requires SAM.gov + FPDS contract data",
    "GC02": "Requires SAM.gov + CMMC compliance data",
    "FP01": "Requires SBA PPP loan data",
    "FP02": "Requires HUD/FHA loan data",
    "FP03": "Requires SAM.gov small business certifications",
    "TH01": "Requires telehealth claims data",
    "TH02": "Requires telehealth claims data",
}

# All fraud categories the engine covers
FRAUD_CATEGORIES = {
    "hospice_fraud": "Hospice Fraud",
    "home_health_fraud": "Home Health Fraud",
    "billing_fraud": "Medicare/Medicaid Billing Fraud",
    "dme_fraud": "Durable Medical Equipment Fraud",
    "pharma_kickback": "Kickback / Anti-Kickback Statute",
    "govt_contract_fraud": "Government Contract Fraud",
    "cybersecurity_false_cert": "Cybersecurity False Certification",
    "ppp_fraud": "PPP Loan Fraud",
    "fha_fraud": "FHA Mortgage Fraud",
    "set_aside_fraud": "Small Business Set-Aside Fraud",
    "telehealth_fraud": "Telehealth Fraud",
    "behavioral_health_fraud": "Behavioral Health Fraud",
    "nursing_snf_fraud": "Nursing/SNF Fraud",
    "medicare_advantage_fraud": "Medicare Advantage Fraud",
    "lab_fraud": "Laboratory Fraud",
    "customs_fraud": "Customs Fraud",
    "bid_rigging": "Bid Rigging",
}
