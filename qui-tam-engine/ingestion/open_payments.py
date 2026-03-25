"""
CMS Open Payments data ingester.

Downloads physician-industry financial relationship data from the CMS
Open Payments program, focusing on payments to physicians with hospice-related
specialties or those who serve as authorized officials for hospice entities.

Sources:
  - CMS Open Payments Socrata API: https://openpaymentsdata.cms.gov/api/1/datastore/sql
  - Bulk download: https://download.cms.gov/openpayments/
"""

import json
import requests
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus


# Socrata SQL-based API endpoint for Open Payments
OPEN_PAYMENTS_API = "https://openpaymentsdata.cms.gov/api/1/datastore/sql"

# Alternative: direct dataset query endpoints (general payments dataset IDs change yearly)
OPEN_PAYMENTS_DATASETS = [
    # 2022 General Payments
    "https://openpaymentsdata.cms.gov/api/1/datastore/query/56dg-3nbi/0",
    # 2021 General Payments
    "https://openpaymentsdata.cms.gov/api/1/datastore/query/2yev-bkey/0",
]

# Hospice-related physician specialties to filter on
HOSPICE_SPECIALTIES = [
    "Hospice and Palliative Medicine",
    "Hospice/Palliative Care",
    "Internal Medicine: Hospice and Palliative Medicine",
    "Family Medicine: Hospice and Palliative Medicine",
    "Geriatric Medicine",
    "Palliative Medicine",
    "Internal Medicine",
    "Family Medicine",
    "General Practice",
]

# Payment categories that may suggest kickback arrangements
SUSPICIOUS_PAYMENT_CATEGORIES = [
    "Consulting Fee",
    "Compensation for services other than consulting",
    "Food and Beverage",
    "Travel and Lodging",
    "Speaking Fee - Compensation",
    "Speaking Fee - Services other than consulting",
    "Honoraria",
    "Gift",
    "Grant",
    "Royalty or License",
    "Charitable Contribution",
    "Entertainment",
    "Current or prospective ownership or investment interest",
    "Education",
]

# Known hospice-related companies that appear as payers in Open Payments
KNOWN_HOSPICE_PAYERS = [
    "Vitas Healthcare",
    "Amedisys",
    "Kindred Healthcare",
    "LHC Group",
    "Gentiva Health Services",
    "BrightSpring Health Services",
    "Enhabit Home Health & Hospice",
    "AccordantHealth",
    "CURO Health Services",
    "Addus HomeCare",
]


class OpenPaymentsIngester(BaseIngester):
    """
    Ingests CMS Open Payments data for hospice-related physician payments.

    Focuses on general payments to physicians whose specialties overlap
    with hospice care, and on payment types that may indicate improper
    financial relationships (potential Anti-Kickback Statute violations).
    """

    SOURCE_NAME = "open_payments"

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest Open Payments data into SourceRecords.

        Args:
            db_session: SQLAlchemy session
            progress_callback: Optional callable(message, percent) for SSE updates

        Returns:
            dict with ingestion statistics
        """
        stats = {
            "source": self.SOURCE_NAME,
            "records_pulled": 0,
            "api_records": 0,
            "hospice_specialty_records": 0,
            "suspicious_payment_records": 0,
            "errors": [],
        }

        all_records = []

        # ── Attempt 1: Socrata SQL API ──
        if progress_callback:
            progress_callback("Querying CMS Open Payments API for hospice-related payments...", None)

        sql_results = self._fetch_via_sql_api()
        if sql_results:
            all_records.extend(sql_results)
            stats["api_records"] += len(sql_results)

        # ── Attempt 2: Direct dataset query ──
        if not all_records:
            if progress_callback:
                progress_callback("Trying Open Payments direct dataset endpoints...", None)

            dataset_results = self._fetch_via_dataset_api()
            if dataset_results:
                all_records.extend(dataset_results)
                stats["api_records"] += len(dataset_results)

        # ── Classify records ──
        for record in all_records:
            specialty = record.get("covered_recipient_specialty_1", "")
            if any(hs.lower() in specialty.lower() for hs in HOSPICE_SPECIALTIES):
                stats["hospice_specialty_records"] += 1

            payment_nature = record.get("nature_of_payment_or_transfer_of_value", "")
            if any(cat.lower() in payment_nature.lower() for cat in SUSPICIOUS_PAYMENT_CATEGORIES):
                stats["suspicious_payment_records"] += 1

        # ── Store as SourceRecords ──
        if progress_callback:
            progress_callback(f"Storing {len(all_records)} Open Payments records...", None)

        for record in all_records:
            identifier = record.get("record_id", record.get("general_transaction_id", ""))
            if not identifier:
                identifier = (
                    f"{record.get('covered_recipient_last_name', 'unknown')}_"
                    f"{record.get('submitting_applicable_manufacturer_or_applicable_gpo_name', 'unknown')}"
                )

            source_record = SourceRecord(
                entity_id=None,
                source_name=self.SOURCE_NAME,
                source_identifier=str(identifier),
                raw_data=json.dumps(record, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        stats["records_pulled"] = len(all_records)

        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            stats["errors"].append(f"Database commit failed: {str(e)}")

        # ── Update DataSourceStatus ──
        self._update_source_status(db_session, stats)

        return stats

    def _fetch_via_sql_api(self) -> list[dict]:
        """
        Fetch Open Payments data using the Socrata SQL-style API.

        Queries for general payments to physicians in hospice-related
        specialties, filtered to payment categories suggestive of kickbacks.

        Returns:
            list of payment record dicts, or empty list on failure
        """
        results = []
        specialty_filters = [
            "Hospice and Palliative Medicine",
            "Geriatric Medicine",
            "Internal Medicine",
            "Family Medicine",
        ]

        for specialty in specialty_filters:
            try:
                sql_query = (
                    f"[SELECT covered_recipient_npi, covered_recipient_last_name, "
                    f"covered_recipient_first_name, covered_recipient_specialty_1, "
                    f"submitting_applicable_manufacturer_or_applicable_gpo_name, "
                    f"total_amount_of_payment_usdollars, "
                    f"nature_of_payment_or_transfer_of_value, "
                    f"date_of_payment, record_id "
                    f"FROM 56dg-3nbi "
                    f"WHERE covered_recipient_specialty_1 = '{specialty}' "
                    f"ORDER BY total_amount_of_payment_usdollars DESC "
                    f"LIMIT 500]"
                )

                resp = requests.get(
                    OPEN_PAYMENTS_API,
                    params={"sql": sql_query},
                    timeout=60,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                )

                if resp.status_code != 200:
                    continue

                data = resp.json()
                rows = data if isinstance(data, list) else data.get("results", [])
                results.extend(rows)

            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue
            except (ValueError, KeyError):
                continue

        return results

    def _fetch_via_dataset_api(self) -> list[dict]:
        """
        Fetch Open Payments data via direct dataset query endpoints.

        Tries multiple dataset IDs (they change annually) and filters
        for hospice-related specialties.

        Returns:
            list of payment record dicts, or empty list on failure
        """
        results = []

        for url in OPEN_PAYMENTS_DATASETS:
            try:
                resp = requests.get(
                    url,
                    params={
                        "limit": 1000,
                        "offset": 0,
                        "conditions[0][property]": "covered_recipient_specialty_1",
                        "conditions[0][value]": "Hospice and Palliative Medicine",
                        "conditions[0][operator]": "=",
                        "sort[0][property]": "total_amount_of_payment_usdollars",
                        "sort[0][order]": "desc",
                    },
                    timeout=60,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                )

                if resp.status_code != 200:
                    continue

                data = resp.json()
                rows = data.get("results", [])
                if rows:
                    results.extend(rows)
                    break  # Got data from one dataset, no need to try older ones

            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue
            except (ValueError, KeyError):
                continue

        return results

    def _update_source_status(self, db_session, stats: dict):
        """Update the DataSourceStatus table for this source."""
        existing = db_session.query(DataSourceStatus).filter(
            DataSourceStatus.source_name == self.SOURCE_NAME
        ).first()

        pull_status = "SUCCESS" if stats["records_pulled"] > 0 else "NO_DATA"
        error_msg = "; ".join(stats["errors"][:3]) if stats.get("errors") else None

        if existing:
            existing.last_successful_pull = datetime.now().isoformat()
            existing.records_pulled = stats["records_pulled"]
            existing.pull_status = pull_status
            existing.error_message = error_msg
        else:
            db_session.add(DataSourceStatus(
                source_name=self.SOURCE_NAME,
                last_successful_pull=datetime.now().isoformat(),
                records_pulled=stats["records_pulled"],
                pull_status=pull_status,
                error_message=error_msg,
            ))

        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
