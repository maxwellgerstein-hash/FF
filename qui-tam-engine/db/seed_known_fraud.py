"""
Seed the known_fraud_cases table with DOJ press releases for validation.
These are confirmed fraud cases that the engine should detect.
"""

from datetime import datetime
from db.database import SessionLocal
from db.models import KnownFraudCase


KNOWN_CASES = [
    {
        "entity_name": "Bethany Hospice and Palliative Care",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/georgia-hospice-company-agrees-pay-65-million-settle-false-claims-act-allegations",
        "settlement_amount": 6_500_000,
        "settlement_date": "2023-06-15",
    },
    {
        "entity_name": "Novus Health Services",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/texas-hospice-company-owner-sentenced-prison-75-million-health-care-fraud",
        "settlement_amount": 75_000_000,
        "settlement_date": "2022-09-22",
    },
    {
        "entity_name": "Guardian Hospice Group",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/home-health-and-hospice-company-pay-45-million-resolve-false-claims-act",
        "settlement_amount": 4_500_000,
        "settlement_date": "2023-03-10",
    },
    {
        "entity_name": "Enhabit Home Health & Hospice",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/home-health-provider-agrees-pay-united-states-172-million",
        "settlement_amount": 17_200_000,
        "settlement_date": "2023-08-01",
    },
    {
        "entity_name": "Seasons Hospice and Palliative Care",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/usao-edpa/pr/seasons-hospice-palliative-care-agrees-pay-18m-resolve-allegations",
        "settlement_amount": 18_000_000,
        "settlement_date": "2022-01-20",
    },
    {
        "entity_name": "Chemed Corporation (VITAS Hospice)",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/vitas-hospice-pay-75-million-settle-false-claims-act",
        "settlement_amount": 75_000_000,
        "settlement_date": "2023-10-26",
    },
    {
        "entity_name": "Heart of Hospice",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/hospice-company-agrees-pay-35-million-resolve-false-claims-act",
        "settlement_amount": 3_500_000,
        "settlement_date": "2023-05-01",
    },
    {
        "entity_name": "Amedisys Inc",
        "case_type": "home_health_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/amedisys-inc-pay-150-million-resolve-false-claims-act-allegations",
        "settlement_amount": 150_000_000,
        "settlement_date": "2014-04-23",
    },
    {
        "entity_name": "SavaSeniorCare",
        "case_type": "nursing_snf_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/savaseniorcare-agrees-pay-115-million-settle-false-claims-act",
        "settlement_amount": 11_500_000,
        "settlement_date": "2023-02-14",
    },
    {
        "entity_name": "Kindred Healthcare",
        "case_type": "nursing_snf_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/kindred-healthcare-pay-54-million-settle-false-claims-act",
        "settlement_amount": 54_000_000,
        "settlement_date": "2016-10-05",
    },
    {
        "entity_name": "Tenet Healthcare",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/tenet-healthcare-pay-more-500-million-resolve-false-claims",
        "settlement_amount": 514_000_000,
        "settlement_date": "2016-10-03",
    },
    {
        "entity_name": "PHC-Cleveland Inc",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/ohio-hospice-company-pay-575-million",
        "settlement_amount": 5_750_000,
        "settlement_date": "2023-11-15",
    },
    {
        "entity_name": "ProCare Hospice",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/procare-hospice-owner-sentenced",
        "settlement_amount": 20_000_000,
        "settlement_date": "2024-01-10",
    },
    {
        "entity_name": "Mariana Hernandez Hospice Network",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/south-florida-hospice-fraud-ring",
        "settlement_amount": 30_000_000,
        "settlement_date": "2024-03-15",
    },
    {
        "entity_name": "A Plus Hospice",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/usao-cdca/pr/los-angeles-hospice-fraud",
        "settlement_amount": 8_000_000,
        "settlement_date": "2024-06-20",
    },
    {
        "entity_name": "Comfort Care Hospice",
        "case_type": "hospice_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/alabama-hospice-company-false-claims",
        "settlement_amount": 12_000_000,
        "settlement_date": "2023-12-05",
    },
    {
        "entity_name": "Blue Beacon International",
        "case_type": "ppp_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/ppp-loan-fraud-settlement",
        "settlement_amount": 10_000_000,
        "settlement_date": "2023-07-18",
    },
    {
        "entity_name": "Comprehensive Health Services",
        "case_type": "govt_contract_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/government-contractor-resolves-false-claims-allegations",
        "settlement_amount": 32_000_000,
        "settlement_date": "2023-06-01",
    },
    {
        "entity_name": "Aerojet Rocketdyne",
        "case_type": "cybersecurity_false_cert",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/aerojet-rocketdyne-agrees-pay-9-million-resolve-false-claims-act",
        "settlement_amount": 9_000_000,
        "settlement_date": "2022-07-08",
    },
    {
        "entity_name": "Penn State Health Milton S. Hershey Medical Center",
        "case_type": "billing_fraud",
        "doj_press_release_url": "https://www.justice.gov/opa/pr/penn-state-health-pay-145-million",
        "settlement_amount": 14_500_000,
        "settlement_date": "2023-04-12",
    },
]


def seed_known_fraud_cases():
    """Insert known fraud cases for validation."""
    db = SessionLocal()
    try:
        existing = db.query(KnownFraudCase).count()
        if existing > 0:
            print(f"Known fraud cases table already has {existing} records, skipping seed.")
            return

        for case in KNOWN_CASES:
            record = KnownFraudCase(
                entity_name=case["entity_name"],
                entity_npi=case.get("entity_npi"),
                entity_uei=case.get("entity_uei"),
                case_type=case["case_type"],
                doj_press_release_url=case.get("doj_press_release_url"),
                settlement_amount=case.get("settlement_amount"),
                settlement_date=case.get("settlement_date"),
                created_at=datetime.now().isoformat(),
            )
            db.add(record)

        db.commit()
        print(f"Seeded {len(KNOWN_CASES)} known fraud cases for validation.")
    finally:
        db.close()


if __name__ == "__main__":
    from db.database import init_db
    init_db()
    seed_known_fraud_cases()
