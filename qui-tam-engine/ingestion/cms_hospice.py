"""
CMS Hospice Compare data ingester.

Two datasets:
  1. Hospice - General Information (dataset ID: yc9t-dgbk)
  2. Hospice - Provider Data (dataset ID: 252m-zfp9) — quality measures in LONG format

Access via CMS Provider Data Catalog: https://data.cms.gov/provider-data/
"""

import httpx
import pandas as pd
import io
import json
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus
from config import EXPECTED_MEASURE_CODES


# CMS Provider Data Catalog API
CATALOG_URL = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items"

# Direct Socrata API endpoints (alternative if catalog fails)
HOSPICE_GENERAL_SOCRATA = "https://data.cms.gov/provider-data/dataset/yc9t-dgbk"
HOSPICE_MEASURES_SOCRATA = "https://data.cms.gov/provider-data/dataset/252m-zfp9"

# Known download patterns (CMS sometimes changes these)
HOSPICE_GENERAL_CSV_PATTERNS = [
    "https://data.cms.gov/provider-data/sites/default/files/resources/hospice_general_information.csv",
    "https://data.cms.gov/provider-data/api/1/datastore/query/yc9t-dgbk/0?limit=50000&offset=0",
]
HOSPICE_MEASURES_CSV_PATTERNS = [
    "https://data.cms.gov/provider-data/sites/default/files/resources/hospice_provider_data.csv",
    "https://data.cms.gov/provider-data/api/1/datastore/query/252m-zfp9/0?limit=500000&offset=0",
]


def find_measure_code(actual_codes: list, measure_key: str) -> str | None:
    """
    Find the actual measure code in the dataset for a given measure.
    Try exact match first, then partial search.
    """
    config = EXPECTED_MEASURE_CODES.get(measure_key)
    if not config:
        return None

    for code in config["exact"]:
        if code in actual_codes:
            return code

    for partial in config["partial_search"]:
        matches = [c for c in actual_codes if partial.upper() in c.upper()]
        if matches:
            print(
                f"WARNING: Measure '{measure_key}' not found at expected code. "
                f"Using partial match: {matches[0]}"
            )
            return matches[0]

    print(
        f"ERROR: Could not find measure '{measure_key}' ({config['description']}). "
        f"Available codes: {actual_codes[:20]}..."
    )
    return None


class CMSHospiceIngester(BaseIngester):
    """Ingests CMS Hospice Compare general info and quality measures."""

    async def _try_download_csv(self, client: httpx.AsyncClient, urls: list[str]) -> str | None:
        """Try multiple URLs until one works. Returns CSV text or None."""
        for url in urls:
            try:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200 and len(resp.text) > 500:
                    return resp.text
            except httpx.HTTPError:
                continue
        return None

    async def _try_socrata_api(self, client: httpx.AsyncClient, dataset_id: str, limit: int = 50000) -> list[dict] | None:
        """Try Socrata open data API for CMS datasets."""
        base_url = f"https://data.cms.gov/provider-data/api/1/datastore/query/{dataset_id}/0"
        all_records = []
        offset = 0

        while True:
            try:
                resp = await client.get(
                    base_url,
                    params={"limit": limit, "offset": offset},
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break
                all_records.extend(results)
                offset += limit
                if len(results) < limit:
                    break
            except (httpx.HTTPError, json.JSONDecodeError):
                break

        return all_records if all_records else None

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """Download and ingest both hospice datasets."""
        stats = {
            "source": "cms_hospice",
            "records_pulled": 0,
            "measures_pulled": 0,
            "measure_codes_found": [],
        }

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            # ── General Information ──
            if progress_callback:
                progress_callback("Fetching CMS Hospice General Information...", None)

            general_df = await self._fetch_general_info(client, db_session)
            if general_df is not None:
                stats["records_pulled"] = len(general_df)

            # ── Provider Measures ──
            if progress_callback:
                progress_callback("Fetching CMS Hospice Provider Measures...", None)

            measures_stats = await self._fetch_measures(client, db_session)
            stats["measures_pulled"] = measures_stats.get("records", 0)
            stats["measure_codes_found"] = measures_stats.get("codes_found", [])

        # Update data source status
        self._update_source_status(db_session, stats)

        return stats

    async def _fetch_general_info(self, client: httpx.AsyncClient, db_session) -> pd.DataFrame | None:
        """Fetch hospice general information."""
        # Try Socrata API first (most reliable)
        records = await self._try_socrata_api(client, "yc9t-dgbk")
        if records:
            df = pd.DataFrame(records)
        else:
            # Fallback to CSV download
            csv_text = await self._try_download_csv(client, HOSPICE_GENERAL_CSV_PATTERNS)
            if csv_text:
                df = pd.read_csv(
                    io.StringIO(csv_text), dtype=str, keep_default_na=False
                )
            else:
                print("ERROR: Could not fetch CMS Hospice General Information from any source.")
                return None

        # Normalize column names — CMS sometimes uses different casing
        col_map = self._map_general_columns(df.columns.tolist())

        # Store each row as a source record
        for _, row in df.iterrows():
            ccn = str(row.get(col_map.get("ccn", ""), "")).strip()
            if not ccn:
                continue

            # Normalize the data into a standard dict
            record_data = {
                "CMS Certification Number (CCN)": ccn,
                "Facility Name": str(row.get(col_map.get("name", ""), "")).strip(),
                "Address Line 1": str(row.get(col_map.get("address", ""), "")).strip(),
                "City/Town": str(row.get(col_map.get("city", ""), "")).strip(),
                "State": str(row.get(col_map.get("state", ""), "")).strip(),
                "ZIP Code": str(row.get(col_map.get("zip", ""), "")).strip(),
                "Telephone Number": str(row.get(col_map.get("phone", ""), "")).strip(),
                "Ownership Type": str(row.get(col_map.get("ownership", ""), "")).strip(),
                "Certification Date": str(row.get(col_map.get("cert_date", ""), "")).strip(),
                "# of Total Episodes": str(row.get(col_map.get("episodes", ""), "")).strip(),
                "# of Total Patients": str(row.get(col_map.get("patients", ""), "")).strip(),
            }

            source_record = SourceRecord(
                source_name="cms_hospice_general",
                source_identifier=ccn,
                raw_data=json.dumps(record_data, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        db_session.commit()
        return df

    async def _fetch_measures(self, client: httpx.AsyncClient, db_session) -> dict:
        """Fetch hospice quality measures (LONG format, pivoted per CCN)."""
        stats = {"records": 0, "codes_found": []}

        # Try Socrata API
        records = await self._try_socrata_api(client, "252m-zfp9", limit=100000)
        if records:
            df = pd.DataFrame(records)
        else:
            csv_text = await self._try_download_csv(client, HOSPICE_MEASURES_CSV_PATTERNS)
            if csv_text:
                df = pd.read_csv(
                    io.StringIO(csv_text), dtype=str, keep_default_na=False
                )
            else:
                print("ERROR: Could not fetch CMS Hospice Measures from any source.")
                return stats

        # Identify column names (CMS varies casing)
        col_map = self._map_measures_columns(df.columns.tolist())
        ccn_col = col_map.get("ccn")
        measure_col = col_map.get("measure_code")
        score_col = col_map.get("score")
        start_col = col_map.get("start_date")
        end_col = col_map.get("end_date")

        if not all([ccn_col, measure_col, score_col]):
            print(f"ERROR: Could not identify required columns in measures data. "
                  f"Available: {df.columns.tolist()}")
            return stats

        # Log all unique measure codes
        unique_codes = df[measure_col].unique().tolist()
        stats["codes_found"] = unique_codes
        print(f"CMS Hospice Measures — unique codes found: {unique_codes}")

        # Pivot: group by CCN, create a dict of measure_code → score
        pivoted = {}
        for _, row in df.iterrows():
            ccn = str(row.get(ccn_col, "")).strip()
            code = str(row.get(measure_col, "")).strip()
            score = str(row.get(score_col, "")).strip()

            if not ccn or not code:
                continue

            if ccn not in pivoted:
                pivoted[ccn] = {
                    "CMS Certification Number (CCN)": ccn,
                }
                if start_col:
                    pivoted[ccn]["Start Date"] = str(row.get(start_col, "")).strip()
                if end_col:
                    pivoted[ccn]["End Date"] = str(row.get(end_col, "")).strip()

            pivoted[ccn][code] = score

        stats["records"] = len(pivoted)

        # Store pivoted data as source records
        for ccn, data in pivoted.items():
            source_record = SourceRecord(
                source_name="cms_hospice_measures",
                source_identifier=ccn,
                raw_data=json.dumps(data, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        db_session.commit()
        return stats

    def _map_general_columns(self, columns: list[str]) -> dict:
        """Map actual column names to standard keys using fuzzy matching."""
        col_lower = {c.lower().strip(): c for c in columns}
        mapping = {}

        patterns = {
            "ccn": ["cms certification number", "ccn", "provider_id", "cms_certification_number"],
            "name": ["facility name", "provider_name", "facility_name"],
            "address": ["address line 1", "address", "street_address", "address_line_1"],
            "city": ["city/town", "city", "city_town"],
            "state": ["state", "state_code"],
            "zip": ["zip code", "zip", "zip_code"],
            "phone": ["telephone number", "phone", "telephone_number"],
            "ownership": ["ownership type", "ownership", "ownership_type"],
            "cert_date": ["certification date", "certification_date", "cert_date"],
            "episodes": ["# of total episodes", "total_episodes", "total episodes", "number_of_total_episodes"],
            "patients": ["# of total patients", "total_patients", "total patients", "number_of_total_patients"],
        }

        for key, candidates in patterns.items():
            for candidate in candidates:
                if candidate.lower() in col_lower:
                    mapping[key] = col_lower[candidate.lower()]
                    break
            if key not in mapping:
                # Try substring match
                for col_l, col_orig in col_lower.items():
                    if any(c in col_l for c in candidates):
                        mapping[key] = col_orig
                        break

        return mapping

    def _map_measures_columns(self, columns: list[str]) -> dict:
        """Map measures column names."""
        col_lower = {c.lower().strip(): c for c in columns}
        mapping = {}

        patterns = {
            "ccn": ["cms certification number", "ccn", "cms_certification_number", "provider_id"],
            "measure_code": ["measure code", "measure_code", "measure name", "measure_name", "quality measure id"],
            "score": ["score", "measure_score", "value", "rate"],
            "start_date": ["start date", "start_date", "measure_start_date"],
            "end_date": ["end date", "end_date", "measure_end_date"],
        }

        for key, candidates in patterns.items():
            for candidate in candidates:
                if candidate.lower() in col_lower:
                    mapping[key] = col_lower[candidate.lower()]
                    break
            if key not in mapping:
                for col_l, col_orig in col_lower.items():
                    if any(c in col_l for c in [p.lower() for p in candidates]):
                        mapping[key] = col_orig
                        break

        return mapping

    def _update_source_status(self, db_session, stats: dict):
        """Update data_source_status table."""
        for source_name in ["cms_hospice_general", "cms_hospice_measures"]:
            count = (
                stats["records_pulled"] if "general" in source_name
                else stats["measures_pulled"]
            )
            existing = db_session.query(DataSourceStatus).filter(
                DataSourceStatus.source_name == source_name
            ).first()

            if existing:
                existing.last_successful_pull = datetime.now().isoformat()
                existing.records_pulled = count
                existing.pull_status = "SUCCESS" if count > 0 else "FAILED"
            else:
                status = DataSourceStatus(
                    source_name=source_name,
                    last_successful_pull=datetime.now().isoformat(),
                    records_pulled=count,
                    pull_status="SUCCESS" if count > 0 else "FAILED",
                )
                db_session.add(status)

        db_session.commit()
