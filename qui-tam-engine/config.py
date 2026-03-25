"""
Configuration constants, thresholds, and API keys for the Qui Tam Case Engine.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──
SAM_API_KEY = os.getenv("SAM_API_KEY", "")
FEC_API_KEY = os.getenv("FEC_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
COURTLISTENER_API_KEY = os.getenv("COURTLISTENER_API_KEY", "")
GSA_API_KEY = os.getenv("GSA_API_KEY", "")

# ── Database ──
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qui_tam_engine.db")

# ── Per-claim civil penalties (2024 statutory range, updated annually for inflation) ──
PENALTY_PER_CLAIM_LOW = 13_946
PENALTY_PER_CLAIM_HIGH = 27_894

# ── Minimum government loss thresholds ──
MIN_GOVT_LOSS = 500_000        # $500K minimum — attorneys won't take smaller cases
PRIORITY_GOVT_LOSS = 1_000_000  # $1M+ = priority tier

# ── Hospice estimation constants ──
AVG_HOSPICE_DAILY_RATE = 195.00  # Routine home care per diem (most common level)
NATIONAL_MEAN_LOS = 92           # days (mean, skewed by long-stay outliers)
NATIONAL_MEDIAN_LOS = 18         # days (median)

# ── OIG-aligned hospice fraud detection thresholds ──
# Source: OIG reports OEI-02-16-00570, DOJ settlements, CMS hospice data
HOSPICE_THRESHOLDS = {
    # Average length of stay (mean ALOS in days)
    "alos_medium": 60,       # Above national mean — warrants review
    "alos_high": 100,        # Well above mean — strong anomaly
    "alos_critical": 180,    # OIG investigation trigger
    # Live discharge rate (%)
    "live_discharge_flag": 40,    # OIG flags at ~2x national avg (17-19%)
    "live_discharge_extreme": 60, # Confirmed fraud cases show 60-80%
    # Mortality rate (%) — inverse of live discharge
    "mortality_low": 60,          # Legitimate hospices: 75-85%
    "mortality_critical": 40,     # Strong indicator of non-terminal enrollment
    # Cancer diagnosis rate (%)
    "cancer_pct_low": 10,         # Fraudulent hospices often <10%
    "cancer_pct_normal_low": 20,  # National norm ~25-30%
    # New entity velocity
    "new_entity_months": 24,      # Flag if < 24 months old (was 12)
    "new_entity_min_episodes": 50, # With > 50 episodes (was 100)
    # Address clustering
    "address_cluster_min": 2,     # 2+ other entities at same address (3+ total)
    # Revenue per beneficiary approaching Medicare cap
    "revenue_per_beneficiary_flag": 28_000,  # Medicare cap ~$32-34K
    # Same owner threshold
    "same_owner_min_entities": 2, # Flag if owner controls 2+ hospices
}

# ── Known fraud hotspot MSAs ──
FRAUD_HOTSPOT_MSAS = {
    "Miami-Fort Lauderdale-Pompano Beach, FL": 0.05,
    "Los Angeles-Long Beach-Anaheim, CA": 0.05,
    "Dallas-Fort Worth-Arlington, TX": 0.03,
    "Houston-The Woodlands-Sugar Land, TX": 0.03,
    "Minneapolis-St. Paul-Bloomington, MN-WI": 0.03,
    "Detroit-Warren-Dearborn, MI": 0.02,
    "Brooklyn-Queens-Bronx, NY": 0.03,
    "Chicago-Naperville-Elgin, IL": 0.02,
}

# ── OIG Work Plan priority areas ──
OIG_WORK_PLAN_PRIORITIES = [
    "hospice_fraud", "home_health_fraud", "medicare_advantage_fraud",
    "telehealth_fraud", "behavioral_health_fraud", "lab_fraud",
    "dme_fraud", "pharma_kickback", "nursing_snf_fraud",
]

# ── Virtual office / PO Box detection ──
KNOWN_VIRTUAL_CHAINS = [
    "UPS STORE", "MAILBOXES ETC", "POSTAL CONNECTIONS", "POSTNET",
    "PAK MAIL", "REGUS", "WEWORK", "IWG", "SPACES", "DAVINCI",
    "INTELLIGENT OFFICE", "PREMIER BUSINESS",
]

PO_BOX_PATTERNS = [
    r"\bP\.?O\.?\s*BOX\b", r"\bPOB\b", r"\bPMB\b",
]

# ── CMS Hospice Measure Codes (defensive matching) ──
EXPECTED_MEASURE_CODES = {
    "alos": {
        "exact": ["H_ALOS_OBSERVED"],
        "partial_search": ["ALOS", "AVG_LOS", "AVERAGE_LENGTH", "LENGTH_STAY"],
        "description": "Average length of stay in days",
    },
    "live_discharge": {
        "exact": ["H_LIVE_DISCHARGE_OBSERVED"],
        "partial_search": ["LIVE_DISCH", "DISCHARGE", "LIVE_DC"],
        "description": "Live discharge rate as percentage",
    },
    "cancer_pct": {
        "exact": ["H_CANCER_PCT"],
        "partial_search": ["CANCER"],
        "description": "Percent of patients with cancer diagnosis",
    },
}

# ── Hospice taxonomy codes for NPPES filtering ──
HOSPICE_TAXONOMY_CODES = {"251G00000X"}
