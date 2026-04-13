"""
SAM.gov exclusion records ingester.

Downloads entity exclusion data from the System for Award Management (SAM.gov),
focusing on healthcare-related exclusions. Entities excluded from federal
procurement are a strong signal for fraud investigations.

Sources:
  - SAM.gov Exclusions API: https://api.sam.gov/entity-information/v3/exclusions
  - SAM.gov Exclusions Extract: https://sam.gov/data-services/Exclusions/Public%20V2
"""

import json
import csv
import io
import requests
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus


# SAM.gov Exclusions API endpoint
SAM_EXCLUSIONS_API = "https://api.sam.gov/entity-information/v3/exclusions"

# SAM.gov bulk exclusion extract (public download)
SAM_EXCLUSIONS_EXTRACT_URL = (
    "https://sam.gov/data-services/Exclusions/Public%20V2?privacy=Public"
)

# Alternative direct download URL for exclusions CSV
SAM_EXCLUSIONS_CSV_URL = (
    "https://sam.gov/api/prod/fileextractservices/v2/downloadFile"
)

# Healthcare-related NAICS codes for filtering
HEALTHCARE_NAICS_PREFIXES = [
    "621",   # Ambulatory health care services
    "622",   # Hospitals
    "623",   # Nursing and residential care facilities
    "6216",  # Home health care services
    "62161", # Home health care services (more specific)
]

# Healthcare-related classification codes in SAM exclusions
HEALTHCARE_CLASSIFICATIONS = [
    "Individual",
    "Firm",
    "Special Entity Designation",
]

# Exclusion types
EXCLUSION_TYPES = {
    "Ineligible (Proceedings Pending)": "proceedings_pending",
    "Ineligible (Proceedings Completed)": "proceedings_completed",
    "Prohibited": "prohibited",
    "Reciprocal": "reciprocal",
    "Voluntary Exclusion": "voluntary",
}

# Agencies whose exclusions are most relevant to healthcare fraud
RELEVANT_AGENCIES = [
    "HHS",                    # Department of Health and Human Services
    "OIG",                    # Office of Inspector General
    "HHS-OIG",               # HHS Office of Inspector General
    "CMS",                    # Centers for Medicare & Medicaid Services
    "DOJ",                    # Department of Justice
    "VA",                     # Department of Veterans Affairs
    "GSA",                    # General Services Administration (government-wide)
    "DHHS",                   # Alternative abbreviation for HHS
    "FDA",                    # Food and Drug Administration
    "DEA",                    # Drug Enforcement Administration
]

# Healthcare-related keywords to look for in entity names
HEALTHCARE_NAME_KEYWORDS = [
    "hospice",
    "home health",
    "homehealth",
    "medical",
    "health",
    "healthcare",
    "nursing",
    "care",
    "clinical",
    "therapy",
    "pharmaceutical",
    "pharma",
    "hospital",
    "physician",
    "doctor",
    "diagnostic",
    "rehabilitation",
    "rehab",
    "wellness",
    "palliative",
]


class SAMGovIngester(BaseIngester):
    """
    Ingests SAM.gov exclusion records relevant to healthcare entities.

    Entities excluded from federal procurement or receiving federal
    awards are strong signals for fraud detection. This ingester
    focuses on healthcare-related exclusions, particularly those
    from HHS/OIG.
    """

    SOURCE_NAME = "sam_exclusions"

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest SAM.gov exclusion data into SourceRecords.

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
            "extract_records": 0,
            "healthcare_related": 0,
            "hospice_related": 0,
            "errors": [],
        }

        all_exclusions = []

        # ── Attempt 1: SAM.gov Exclusions API ──
        if progress_callback:
            progress_callback("Querying SAM.gov Exclusions API for healthcare exclusions...", None)

        api_results = self._fetch_via_api()
        if api_results:
            all_exclusions.extend(api_results)
            stats["api_records"] = len(api_results)

        # ── Attempt 2: SAM.gov Exclusions Extract (bulk download) ──
        if not all_exclusions:
            if progress_callback:
                progress_callback("Downloading SAM.gov Exclusions bulk extract...", None)

            extract_results = self._fetch_via_extract()
            if extract_results:
                all_exclusions.extend(extract_results)
                stats["extract_records"] = len(extract_results)

        # ── Classify and store records ──
        if progress_callback:
            progress_callback(
                f"Processing {len(all_exclusions)} SAM.gov exclusion records...", None
            )

        for exclusion in all_exclusions:
            is_healthcare = self._is_healthcare_related(exclusion)
            is_hospice = self._is_hospice_related(exclusion)

            if is_healthcare:
                stats["healthcare_related"] += 1
            if is_hospice:
                stats["hospice_related"] += 1

            enriched = {
                **exclusion,
                "is_healthcare_related": is_healthcare,
                "is_hospice_related": is_hospice,
            }

            identifier = (
                exclusion.get("uei")
                or exclusion.get("cage_code")
                or exclusion.get("entity_name", "unknown")
            )

            source_record = SourceRecord(
                entity_id=None,
                source_name=self.SOURCE_NAME,
                source_identifier=str(identifier),
                raw_data=json.dumps(enriched, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        stats["records_pulled"] = len(all_exclusions)

        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            stats["errors"].append(f"Database commit failed: {str(e)}")

        # ── Update DataSourceStatus ──
        self._update_source_status(db_session, stats)

        return stats

    def _fetch_via_api(self) -> list[dict]:
        """
        Fetch exclusion records from the SAM.gov Exclusions API.

        Queries for healthcare-related exclusions using multiple
        search strategies (by agency, by classification, by keyword).

        Returns:
            list of exclusion record dicts, or empty list on failure
        """
        results = []

        # Strategy 1: Query by excluding agency (HHS, OIG)
        for agency in ["HHS", "DOJ", "VA"]:
            try:
                resp = requests.get(
                    SAM_EXCLUSIONS_API,
                    params={
                        "api_key": "DEMO_KEY",
                        "excludingAgencyCode": agency,
                        "limit": 500,
                        "offset": 0,
                    },
                    timeout=60,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                )

                if resp.status_code == 429:
                    # Rate limited - stop querying the API
                    break

                if resp.status_code != 200:
                    continue

                data = resp.json()
                records = data.get("results", data.get("entityData", []))

                for record in records:
                    parsed = self._parse_api_record(record)
                    if parsed:
                        results.append(parsed)

            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue
            except (ValueError, KeyError):
                continue

        # Strategy 2: Query by keyword for hospice-specific exclusions
        for keyword in ["hospice", "home health", "healthcare fraud"]:
            try:
                resp = requests.get(
                    SAM_EXCLUSIONS_API,
                    params={
                        "api_key": "DEMO_KEY",
                        "q": keyword,
                        "limit": 100,
                        "offset": 0,
                    },
                    timeout=60,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                )

                if resp.status_code == 429:
                    break

                if resp.status_code != 200:
                    continue

                data = resp.json()
                records = data.get("results", data.get("entityData", []))

                for record in records:
                    parsed = self._parse_api_record(record)
                    if parsed:
                        # Deduplicate by UEI or entity name
                        existing_ids = {r.get("uei") or r.get("entity_name") for r in results}
                        record_id = parsed.get("uei") or parsed.get("entity_name")
                        if record_id not in existing_ids:
                            results.append(parsed)

            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue
            except (ValueError, KeyError):
                continue

        return results

    def _parse_api_record(self, record: dict) -> dict:
        """
        Parse a single record from the SAM.gov API response.

        The API response structure varies; this handles multiple formats.

        Returns:
            dict with standardized exclusion fields, or None if unparseable
        """
        try:
            # Handle nested entity structure
            entity_info = record.get("entityInformation", record)
            exclusion_info = record.get("exclusionDetails", record)

            entity_name = (
                entity_info.get("entityName")
                or entity_info.get("name")
                or record.get("firm", "")
                or f"{record.get('first', '')} {record.get('last', '')}".strip()
            )

            if not entity_name:
                return None

            return {
                "entity_name": entity_name,
                "uei": entity_info.get("ueiSAM", entity_info.get("uei", "")),
                "cage_code": entity_info.get("cageCode", entity_info.get("cage", "")),
                "duns": entity_info.get("duns", ""),
                "exclusion_type": (
                    exclusion_info.get("exclusionType")
                    or exclusion_info.get("classification", "")
                ),
                "exclusion_program": exclusion_info.get("exclusionProgram", ""),
                "excluding_agency": (
                    exclusion_info.get("excludingAgencyCode")
                    or exclusion_info.get("agency", "")
                ),
                "exclusion_date": (
                    exclusion_info.get("activeDateFrom")
                    or exclusion_info.get("exclusionDate", "")
                ),
                "termination_date": (
                    exclusion_info.get("activeDateTo")
                    or exclusion_info.get("terminationDate", "")
                ),
                "classification": exclusion_info.get("classification", ""),
                "state": (
                    entity_info.get("stateProvince")
                    or entity_info.get("state", "")
                ),
                "city": entity_info.get("city", ""),
                "country": entity_info.get("country", "USA"),
                "cross_reference": exclusion_info.get("crossReference", ""),
                "description": exclusion_info.get("description", ""),
            }

        except (KeyError, TypeError, AttributeError):
            return None

    def _fetch_via_extract(self) -> list[dict]:
        """
        Download and parse the SAM.gov Exclusions bulk extract file.

        The extract is a pipe-delimited or CSV file containing all
        current exclusion records.

        Returns:
            list of exclusion record dicts, or empty list on failure
        """
        results = []

        # Try multiple download approaches
        urls_to_try = [
            SAM_EXCLUSIONS_EXTRACT_URL,
            "https://sam.gov/api/prod/fileextractservices/v2/downloadFile?fileName=SAM_Exclusions_Public_Extract_V2.CSV&fileType=csv",
            "https://sam.gov/api/prod/fileextractservices/v2/downloadFile?fileName=SAM_Exclusions_Public_Extract.CSV&fileType=csv",
        ]

        csv_text = None
        for url in urls_to_try:
            try:
                resp = requests.get(
                    url,
                    timeout=120,
                    headers={"User-Agent": "QuiTamEngine/1.0 (research)"},
                    stream=True,
                )

                if resp.status_code == 200 and len(resp.text) > 1000:
                    csv_text = resp.text
                    break

            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue

        if not csv_text:
            return results

        # Parse the CSV/pipe-delimited file
        try:
            # Detect delimiter
            first_line = csv_text.split("\n")[0]
            delimiter = "|" if "|" in first_line else ","

            reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)

            for row in reader:
                entity_name = (
                    row.get("Firm", "")
                    or row.get("Name", "")
                    or f"{row.get('First', '')} {row.get('Last', '')}".strip()
                )

                if not entity_name:
                    continue

                # Filter for healthcare-related exclusions
                agency = row.get("Agency", row.get("Excluding Agency", ""))
                classification = row.get("Classification", row.get("CT Code", ""))
                name_lower = entity_name.lower()

                is_relevant = (
                    agency in RELEVANT_AGENCIES
                    or any(kw in name_lower for kw in HEALTHCARE_NAME_KEYWORDS)
                )

                if not is_relevant:
                    continue

                parsed = {
                    "entity_name": entity_name,
                    "uei": row.get("UEI", row.get("Unique Entity ID", "")),
                    "cage_code": row.get("CAGE", row.get("CAGE Code", "")),
                    "duns": row.get("DUNS", ""),
                    "exclusion_type": row.get("Exclusion Type", row.get("CT Code", "")),
                    "exclusion_program": row.get("Exclusion Program", ""),
                    "excluding_agency": agency,
                    "exclusion_date": row.get("Active Date", row.get("Exclusion Date", "")),
                    "termination_date": row.get("Termination Date", ""),
                    "classification": classification,
                    "state": row.get("State", row.get("State / Province", "")),
                    "city": row.get("City", ""),
                    "country": row.get("Country", "USA"),
                    "cross_reference": row.get("Cross-Reference", ""),
                    "description": row.get("Description", row.get("Additional Comments", "")),
                    "npi": row.get("NPI", ""),
                }

                results.append(parsed)

        except Exception:
            pass

        return results

    def _is_healthcare_related(self, exclusion: dict) -> bool:
        """Check if an exclusion record is healthcare-related."""
        agency = (exclusion.get("excluding_agency") or "").upper()
        if agency in ("HHS", "HHS-OIG", "OIG", "CMS", "DHHS", "FDA", "DEA"):
            return True

        name_lower = (exclusion.get("entity_name") or "").lower()
        return any(kw in name_lower for kw in HEALTHCARE_NAME_KEYWORDS)

    def _is_hospice_related(self, exclusion: dict) -> bool:
        """Check if an exclusion record is specifically hospice-related."""
        name_lower = (exclusion.get("entity_name") or "").lower()
        desc_lower = (exclusion.get("description") or "").lower()
        combined = f"{name_lower} {desc_lower}"

        hospice_keywords = ["hospice", "palliative", "home health", "homehealth", "end of life"]
        return any(kw in combined for kw in hospice_keywords)

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
