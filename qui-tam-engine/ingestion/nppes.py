"""
NPPES (National Plan and Provider Enumeration System) bulk file ingester.

Strategy:
  1. Download the NPPES bulk ZIP file (~1 GB compressed, ~5 GB uncompressed)
  2. Stream-parse row by row, extracting only hospice taxonomy code rows
  3. Store authorized official info for entity enrichment

Hospice taxonomy code: 251G00000X
"""

import httpx
import zipfile
import csv
import json
import os
import re
import tempfile
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus
from config import HOSPICE_TAXONOMY_CODES


DOWNLOAD_PAGE = "https://download.cms.gov/nppes/NPI_Files.html"

# Columns to extract from the 329-column NPPES CSV
NEEDED_COLUMNS = [
    "NPI",
    "Entity Type Code",
    "Provider Organization Name (Legal Business Name)",
    "Provider Last Name (Legal Name)",
    "Provider First Name",
    "Provider First Line Business Practice Location Address",
    "Provider Second Line Business Practice Location Address",
    "Provider Business Practice Location Address City Name",
    "Provider Business Practice Location Address State Name",
    "Provider Business Practice Location Address Postal Code",
    "Provider Business Practice Location Address Telephone Number",
    "Provider Business Practice Location Address Fax Number",
    "Authorized Official Last Name",
    "Authorized Official First Name",
    "Authorized Official Telephone Number",
    "Healthcare Provider Taxonomy Code_1",
    "Healthcare Provider Taxonomy Code_2",
    "Healthcare Provider Taxonomy Code_3",
    "NPI Deactivation Date",
]


class NPPESIngester(BaseIngester):
    """Downloads and filters NPPES bulk file for hospice providers."""

    async def discover_download_url(self) -> str:
        """
        Discover the current NPPES bulk file URL from the CMS download page.
        Falls back to known URL patterns if scraping fails.
        """
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            try:
                resp = await client.get(DOWNLOAD_PAGE)
                # Look for the data dissemination ZIP link
                matches = re.findall(
                    r'href=["\']([^"\']*NPPES_Data_Dissemination[^"\']*\.zip)["\']',
                    resp.text,
                    re.IGNORECASE,
                )
                if matches:
                    url = matches[0]
                    if not url.startswith("http"):
                        url = f"https://download.cms.gov/nppes/{url}"
                    return url
            except httpx.HTTPError:
                pass

        # Fallback: try common patterns
        from datetime import date
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        today = date.today()
        # Try current month, then previous months
        for delta in range(0, 4):
            m = (today.month - delta - 1) % 12
            y = today.year if (today.month - delta) > 0 else today.year - 1
            url = f"https://download.cms.gov/nppes/NPPES_Data_Dissemination_{months[m]}_{y}.zip"
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    resp = await client.head(url, follow_redirects=True)
                    if resp.status_code == 200:
                        return url
                except httpx.HTTPError:
                    continue

        raise RuntimeError(
            "Could not discover NPPES download URL. "
            "Check https://download.cms.gov/nppes/NPI_Files.html"
        )

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Download NPPES bulk file, extract hospice providers only.
        Stream-parses to avoid loading 5 GB into memory.
        """
        stats = {
            "source": "nppes_bulk",
            "total_rows_scanned": 0,
            "hospice_rows_found": 0,
            "authorized_officials_found": 0,
        }

        if progress_callback:
            progress_callback("Discovering NPPES download URL...", None)

        download_url = await self.discover_download_url()

        if progress_callback:
            progress_callback(f"Downloading NPPES bulk file (~1 GB)...", None)

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "nppes.zip")

            # Download with 10 min timeout
            async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    with open(zip_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)

            if progress_callback:
                progress_callback("Extracting NPPES data...", None)

            # Extract ZIP
            with zipfile.ZipFile(zip_path, "r") as z:
                csv_files = [
                    f for f in z.namelist()
                    if f.endswith(".csv") and "npidata" in f.lower()
                ]
                if not csv_files:
                    raise RuntimeError(
                        f"No npidata CSV found in ZIP. Contents: {z.namelist()[:20]}"
                    )

                data_file = csv_files[0]
                z.extract(data_file, tmpdir)
                csv_path = os.path.join(tmpdir, data_file)

            if progress_callback:
                progress_callback("Scanning NPPES for hospice providers...", None)

            # Stream-parse the CSV
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    stats["total_rows_scanned"] += 1

                    if stats["total_rows_scanned"] % 500000 == 0 and progress_callback:
                        progress_callback(
                            f"Scanned {stats['total_rows_scanned']:,} NPI records, "
                            f"found {stats['hospice_rows_found']} hospice providers...",
                            None,
                        )

                    # Check if any taxonomy code is hospice
                    is_hospice = False
                    for i in range(1, 16):
                        tax_col = f"Healthcare Provider Taxonomy Code_{i}"
                        tax_code = row.get(tax_col, "").strip()
                        if tax_code in HOSPICE_TAXONOMY_CODES:
                            is_hospice = True
                            break
                        if not tax_code:
                            break

                    if not is_hospice:
                        continue

                    stats["hospice_rows_found"] += 1

                    auth_last = row.get("Authorized Official Last Name", "").strip()
                    if auth_last:
                        stats["authorized_officials_found"] += 1

                    # Extract only needed columns
                    filtered_row = {
                        col: row.get(col, "").strip()
                        for col in NEEDED_COLUMNS
                        if col in row
                    }

                    npi = row.get("NPI", "").strip()
                    source_record = SourceRecord(
                        source_name="nppes_bulk",
                        source_identifier=npi,
                        raw_data=json.dumps(filtered_row, default=str),
                        ingested_at=datetime.now().isoformat(),
                    )
                    db_session.add(source_record)

                    if stats["hospice_rows_found"] % 1000 == 0:
                        db_session.commit()

            db_session.commit()

        # Update data source status
        existing = db_session.query(DataSourceStatus).filter(
            DataSourceStatus.source_name == "nppes_bulk"
        ).first()
        if existing:
            existing.last_successful_pull = datetime.now().isoformat()
            existing.records_pulled = stats["hospice_rows_found"]
            existing.pull_status = "SUCCESS"
        else:
            db_session.add(DataSourceStatus(
                source_name="nppes_bulk",
                last_successful_pull=datetime.now().isoformat(),
                records_pulled=stats["hospice_rows_found"],
                pull_status="SUCCESS",
            ))
        db_session.commit()

        return stats
