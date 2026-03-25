"""
OIG LEIE (List of Excluded Individuals and Entities) ingester.

Download URL: https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv
No API exists. Download the entire file.

CSV columns: LASTNAME, FIRSTNAME, MIDNAME, BUSNAME, GENERAL, SPECIALTY,
UPIN, NPI, DOB, ADDRESS, CITY, STATE, ZIP, EXCLTYPE, EXCLDATE, REINDATE,
WAIVERDATE, WAIVERSTATE

Date format: YYYYMMDD
"""

import httpx
import pandas as pd
import io
import re
import json
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, LEIEIndex, DataSourceStatus


DOWNLOAD_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"


def normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    if not name:
        return ""
    name = name.upper().strip()
    name = re.sub(r'[.,\-\'\"()&]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def check_leie_match(name: str, state: str, db_session) -> dict | None:
    """
    Check if a name matches any LEIE entry.
    Uses the pre-built LEIEIndex table — only searches within the same state
    plus nationwide entries (state="").

    This is O(state_records) instead of O(82,000).
    """
    from rapidfuzz import fuzz

    name_normalized = normalize_name(name)
    if not name_normalized or len(name_normalized) < 3:
        return None

    # Only search LEIE records in the same state (or no state listed)
    candidates = db_session.query(LEIEIndex).filter(
        (LEIEIndex.state == state) | (LEIEIndex.state == "")
    ).all()

    best_match = None
    best_score = 0

    for candidate in candidates:
        score = fuzz.token_sort_ratio(name_normalized, candidate.full_name_normalized)
        if score > best_score and score >= 90:
            best_score = score
            best_match = candidate

    if best_match:
        raw = json.loads(best_match.raw_record)
        excl_date_parsed = None
        if best_match.exclusion_date and len(best_match.exclusion_date) == 8:
            try:
                excl_date_parsed = datetime.strptime(
                    best_match.exclusion_date, "%Y%m%d"
                ).date()
            except ValueError:
                pass

        return {
            "name": (
                raw.get("BUSNAME")
                or f"{raw.get('FIRSTNAME', '')} {raw.get('LASTNAME', '')}".strip()
            ),
            "excltype": best_match.exclusion_type,
            "excldate": best_match.exclusion_date,
            "excldate_parsed": excl_date_parsed,
            "match_score": best_score,
            "npi": best_match.npi,
        }

    return None


class OIGLEIEIngester(BaseIngester):
    """Downloads and indexes the OIG LEIE exclusion list."""

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """Download LEIE and build the fast-match index."""
        stats = {
            "source": "oig_leie",
            "records_pulled": 0,
            "records_with_npi": 0,
            "index_entries_created": 0,
        }

        if progress_callback:
            progress_callback("Connecting to OIG servers...", None)

        # Stream download so we can report progress
        chunks = []
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", DOWNLOAD_URL) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0 and downloaded % (512 * 1024) < 65536:
                        pct = downloaded / total * 100
                        progress_callback(
                            f"Downloading LEIE CSV... {downloaded // 1024:,} KB / {total // 1024:,} KB ({pct:.0f}%)",
                            None,
                        )

        csv_text = b"".join(chunks).decode("utf-8", errors="replace")

        if progress_callback:
            progress_callback("Parsing exclusion records...", None)

        df = pd.read_csv(
            io.StringIO(csv_text), dtype=str, keep_default_na=False
        )

        stats["records_pulled"] = len(df)

        if progress_callback:
            progress_callback(f"Indexing {len(df):,} exclusion records...", None)

        # Clear existing LEIE index
        db_session.query(LEIEIndex).delete()

        for idx, (_, row) in enumerate(df.iterrows()):
            if progress_callback and idx > 0 and idx % 10000 == 0:
                progress_callback(
                    f"Indexed {idx:,} / {len(df):,} LEIE records...",
                    None,
                )
            lastname = row.get("LASTNAME", "").strip()
            firstname = row.get("FIRSTNAME", "").strip()
            busname = row.get("BUSNAME", "").strip()
            npi = row.get("NPI", "").strip()
            state = row.get("STATE", "").strip()
            excltype = row.get("EXCLTYPE", "").strip()
            excldate = row.get("EXCLDATE", "").strip()

            if npi:
                stats["records_with_npi"] += 1

            # Build normalized name for the index
            if busname:
                full_name = busname
            elif lastname:
                full_name = f"{firstname} {lastname}".strip()
            else:
                continue  # Skip records with no usable name

            index_entry = LEIEIndex(
                full_name_normalized=normalize_name(full_name),
                state=state,
                npi=npi,
                exclusion_type=excltype,
                exclusion_date=excldate,
                raw_record=json.dumps(row.to_dict(), default=str),
            )
            db_session.add(index_entry)
            stats["index_entries_created"] += 1

            # Also save as source record
            source_record = SourceRecord(
                source_name="oig_leie",
                source_identifier=npi if npi else f"LEIE_{lastname}_{firstname}",
                raw_data=json.dumps(row.to_dict(), default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        db_session.commit()

        # Update data source status
        existing = db_session.query(DataSourceStatus).filter(
            DataSourceStatus.source_name == "oig_leie"
        ).first()
        if existing:
            existing.last_successful_pull = datetime.now().isoformat()
            existing.records_pulled = stats["records_pulled"]
            existing.pull_status = "SUCCESS"
        else:
            db_session.add(DataSourceStatus(
                source_name="oig_leie",
                last_successful_pull=datetime.now().isoformat(),
                records_pulled=stats["records_pulled"],
                pull_status="SUCCESS",
            ))
        db_session.commit()

        return stats
