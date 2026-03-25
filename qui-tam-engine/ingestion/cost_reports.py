"""
Medicare Hospice Cost Reports ingester.

Downloads and processes Medicare hospice cost report data from CMS,
extracting financial metrics per provider and flagging those with
abnormally high profit margins (potential indicator of billing fraud).

Sources:
  - CMS Cost Reports: https://data.cms.gov/provider-compliance/cost-report
  - HCRIS (Healthcare Cost Report Information System): https://downloads.cms.gov/files/hcris/
  - Hospice cost reports use form CMS-1984-14

Industry context:
  - National average hospice profit margin: ~8-12%
  - Margins above 30% are statistically anomalous and warrant review
  - For-profit hospices typically have higher margins than nonprofits
"""

import json
import csv
import io
import requests
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus


# CMS HCRIS hospice cost report data files
HCRIS_HOSPICE_URLS = [
    # Alpha (current period) and Omega (final settled) datasets
    "https://downloads.cms.gov/files/hcris/HOSP10-ALPHA-REPORTS.CSV",
    "https://downloads.cms.gov/files/hcris/HOSP10-OMEGA-REPORTS.CSV",
    # Numeric data file (contains the actual financial figures)
    "https://downloads.cms.gov/files/hcris/HOSP10-ALPHA-NMRC.CSV",
    "https://downloads.cms.gov/files/hcris/HOSP10-OMEGA-NMRC.CSV",
]

# Socrata-based CMS data endpoint (alternative)
CMS_COST_REPORT_SOCRATA = (
    "https://data.cms.gov/provider-compliance/cost-report/"
    "cost-report-hospice/api/1/datastore/query/a016-nfbb/0"
)

# HCRIS worksheet/line/column references for key financial fields
# These map to specific cells on form CMS-1984-14
HCRIS_FIELD_MAP = {
    "total_revenue": {"worksheet": "G-2", "line": "28", "column": "1"},
    "total_costs": {"worksheet": "G-2", "line": "28", "column": "2"},
    "net_patient_revenue": {"worksheet": "G-2", "line": "26", "column": "1"},
    "medicare_revenue": {"worksheet": "G-2", "line": "1", "column": "1"},
    "total_patient_days": {"worksheet": "S-1", "line": "12", "column": "6"},
    "total_patients": {"worksheet": "S-1", "line": "12", "column": "7"},
    "total_discharges": {"worksheet": "S-1", "line": "12", "column": "8"},
}

# Profit margin threshold for flagging suspicious providers
HIGH_PROFIT_MARGIN_THRESHOLD = 0.30


class CostReportsIngester(BaseIngester):
    """
    Ingests Medicare hospice cost report data from CMS HCRIS.

    Extracts financial metrics per provider and calculates derived
    indicators such as profit margin and revenue per patient day.
    Providers with profit margins exceeding 30% are flagged.
    """

    SOURCE_NAME = "cost_reports"

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest hospice cost report data into SourceRecords.

        Args:
            db_session: SQLAlchemy session
            progress_callback: Optional callable(message, percent) for SSE updates

        Returns:
            dict with ingestion statistics
        """
        stats = {
            "source": self.SOURCE_NAME,
            "records_pulled": 0,
            "providers_with_high_margin": 0,
            "avg_profit_margin": 0.0,
            "errors": [],
        }

        provider_data = {}

        # ── Attempt 1: CMS Socrata API ──
        if progress_callback:
            progress_callback("Querying CMS Cost Reports Socrata API...", None)

        socrata_records = self._fetch_socrata_cost_reports()
        if socrata_records:
            provider_data = self._parse_socrata_records(socrata_records)
            if progress_callback:
                progress_callback(
                    f"Retrieved {len(provider_data)} providers from Socrata API.", None
                )

        # ── Attempt 2: HCRIS direct download ──
        if not provider_data:
            if progress_callback:
                progress_callback("Downloading HCRIS hospice cost report files...", None)

            hcris_data = self._fetch_hcris_data()
            if hcris_data:
                provider_data = self._parse_hcris_data(hcris_data)
                if progress_callback:
                    progress_callback(
                        f"Parsed {len(provider_data)} providers from HCRIS files.", None
                    )

        if not provider_data:
            stats["errors"].append(
                "Could not retrieve cost report data from any CMS source."
            )
            self._update_source_status(db_session, stats)
            return stats

        # ── Calculate derived metrics and store ──
        if progress_callback:
            progress_callback(
                f"Calculating financial metrics for {len(provider_data)} providers...",
                None,
            )

        margins = []

        for ccn, data in provider_data.items():
            total_revenue = self._safe_float(data.get("total_revenue", 0))
            total_costs = self._safe_float(data.get("total_costs", 0))
            patient_days = self._safe_float(data.get("total_patient_days", 0))
            total_patients = self._safe_float(data.get("total_patients", 0))

            # Calculate profit margin
            profit_margin = None
            if total_revenue and total_revenue > 0:
                profit_margin = (total_revenue - total_costs) / total_revenue
                margins.append(profit_margin)

            # Calculate revenue per patient day
            revenue_per_patient_day = None
            if patient_days and patient_days > 0:
                revenue_per_patient_day = total_revenue / patient_days

            # Flag high-margin providers
            is_high_margin = (
                profit_margin is not None
                and profit_margin > HIGH_PROFIT_MARGIN_THRESHOLD
            )
            if is_high_margin:
                stats["providers_with_high_margin"] += 1

            enriched_data = {
                **data,
                "ccn": ccn,
                "calculated_profit_margin": profit_margin,
                "calculated_revenue_per_patient_day": revenue_per_patient_day,
                "is_high_margin_flag": is_high_margin,
                "high_margin_threshold": HIGH_PROFIT_MARGIN_THRESHOLD,
            }

            source_record = SourceRecord(
                entity_id=None,
                source_name=self.SOURCE_NAME,
                source_identifier=ccn,
                raw_data=json.dumps(enriched_data, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        stats["records_pulled"] = len(provider_data)
        if margins:
            stats["avg_profit_margin"] = round(sum(margins) / len(margins), 4)

        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            stats["errors"].append(f"Database commit failed: {str(e)}")

        # ── Update DataSourceStatus ──
        self._update_source_status(db_session, stats)

        return stats

    def _fetch_socrata_cost_reports(self) -> list[dict]:
        """
        Fetch hospice cost report data via the CMS Socrata API.

        Returns:
            list of record dicts, or empty list on failure
        """
        all_records = []
        offset = 0
        page_size = 5000

        while True:
            try:
                resp = requests.get(
                    CMS_COST_REPORT_SOCRATA,
                    params={"limit": page_size, "offset": offset},
                    timeout=120,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                )

                if resp.status_code != 200:
                    break

                data = resp.json()
                rows = data.get("results", [])
                if not rows:
                    break

                all_records.extend(rows)
                offset += page_size

                if len(rows) < page_size:
                    break

            except requests.exceptions.ConnectionError:
                break
            except requests.exceptions.Timeout:
                break
            except requests.exceptions.RequestException:
                break
            except (ValueError, KeyError):
                break

        return all_records

    def _parse_socrata_records(self, records: list[dict]) -> dict:
        """
        Parse Socrata API records into a provider-keyed dict.

        The Socrata dataset typically has one row per provider per
        reporting period. We take the most recent report for each CCN.

        Returns:
            dict keyed by CCN with financial data
        """
        providers = {}

        for row in records:
            ccn = str(
                row.get("provider_ccn", row.get("prvdr_num", row.get("ccn", "")))
            ).strip()
            if not ccn:
                continue

            fiscal_year_end = row.get(
                "fy_end_dt", row.get("fiscal_year_end_date", "")
            )

            # Keep only the most recent report per CCN
            if ccn in providers:
                existing_fy = providers[ccn].get("fiscal_year_end", "")
                if fiscal_year_end and existing_fy and fiscal_year_end <= existing_fy:
                    continue

            providers[ccn] = {
                "provider_name": row.get(
                    "prvdr_name",
                    row.get("provider_name", row.get("facility_name", "")),
                ),
                "state": row.get("state_cd", row.get("state", "")),
                "city": row.get("city", ""),
                "fiscal_year_end": fiscal_year_end,
                "total_revenue": row.get(
                    "tot_rev", row.get("total_revenues", row.get("net_patient_revenue", 0))
                ),
                "total_costs": row.get(
                    "tot_cost", row.get("total_costs", row.get("total_operating_expenses", 0))
                ),
                "total_patient_days": row.get(
                    "total_days", row.get("total_patient_days", 0)
                ),
                "total_patients": row.get(
                    "total_patients", row.get("total_unduplicated_census", 0)
                ),
                "total_discharges": row.get("total_discharges", 0),
                "medicare_revenue": row.get(
                    "medicare_revenue", row.get("title_xviii_net_patient_revenue", 0)
                ),
                "ownership_type": row.get("ownership_type", row.get("own_type", "")),
            }

        return providers

    def _fetch_hcris_data(self) -> dict:
        """
        Download HCRIS hospice cost report CSV files directly from CMS.

        Downloads the report-level file (provider identifiers) and the
        numeric data file (financial figures), then joins them.

        Returns:
            dict with 'reports' and 'numeric' keys, or empty dict on failure
        """
        result = {}

        # Download reports file (provider info)
        for url_key, label in [
            ("https://downloads.cms.gov/files/hcris/HOSP10-ALPHA-REPORTS.CSV", "reports"),
            ("https://downloads.cms.gov/files/hcris/HOSP10-ALPHA-NMRC.CSV", "numeric"),
        ]:
            try:
                resp = requests.get(
                    url_key,
                    timeout=300,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                    stream=True,
                )
                if resp.status_code == 200:
                    result[label] = resp.text
            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue

        return result

    def _parse_hcris_data(self, hcris_data: dict) -> dict:
        """
        Parse raw HCRIS CSV data into a provider-keyed dict.

        The HCRIS reports file has columns:
            RPT_REC_NUM, PRVDR_CTRL_TYPE_CD, PRVDR_NUM, ...

        The numeric file has columns:
            RPT_REC_NUM, WKSHT_CD, LINE_NUM, CLMN_NUM, ITM_VAL_NUM

        We join on RPT_REC_NUM and extract specific worksheet/line/column
        combinations that correspond to financial fields.

        Returns:
            dict keyed by CCN with financial data
        """
        reports_text = hcris_data.get("reports", "")
        numeric_text = hcris_data.get("numeric", "")

        if not reports_text or not numeric_text:
            return {}

        # Parse reports file to get RPT_REC_NUM -> provider mapping
        rpt_to_provider = {}
        try:
            reader = csv.reader(io.StringIO(reports_text))
            for row in reader:
                if len(row) < 5:
                    continue
                rpt_rec_num = row[0].strip()
                prvdr_num = row[2].strip() if len(row) > 2 else ""
                prvdr_name = row[4].strip() if len(row) > 4 else ""
                fy_end = row[6].strip() if len(row) > 6 else ""
                state = row[8].strip() if len(row) > 8 else ""

                if prvdr_num:
                    rpt_to_provider[rpt_rec_num] = {
                        "ccn": prvdr_num,
                        "provider_name": prvdr_name,
                        "fiscal_year_end": fy_end,
                        "state": state,
                    }
        except Exception:
            return {}

        # Parse numeric file to extract financial fields
        providers = {}
        try:
            reader = csv.reader(io.StringIO(numeric_text))
            for row in reader:
                if len(row) < 5:
                    continue
                rpt_rec_num = row[0].strip()
                wksht_cd = row[1].strip()
                line_num = row[2].strip()
                clmn_num = row[3].strip()
                value = row[4].strip()

                if rpt_rec_num not in rpt_to_provider:
                    continue

                provider_info = rpt_to_provider[rpt_rec_num]
                ccn = provider_info["ccn"]

                if ccn not in providers:
                    providers[ccn] = {**provider_info}

                # Match against our field map
                for field_name, ref in HCRIS_FIELD_MAP.items():
                    if (
                        wksht_cd.replace(" ", "") == ref["worksheet"].replace(" ", "")
                        and line_num.lstrip("0") == ref["line"].lstrip("0")
                        and clmn_num.lstrip("0") == ref["column"].lstrip("0")
                    ):
                        providers[ccn][field_name] = value
        except Exception:
            pass

        return providers

    @staticmethod
    def _safe_float(val) -> float:
        """Safely convert a value to float, returning 0.0 on failure."""
        if val is None:
            return 0.0
        try:
            return float(str(val).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return 0.0

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
