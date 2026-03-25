"""
SEC EDGAR filings ingester for publicly traded hospice companies.

Fetches SEC filings (10-K, 10-Q, 8-K, DEF 14A) for hospice and home health
companies to extract revenue data, legal proceedings disclosures, risk factors
mentioning government investigations, and segment financial data.

Sources:
  - EDGAR full-text search: https://efts.sec.gov/LATEST/search-index
  - Company submissions: https://data.sec.gov/submissions/CIK{number}.json
  - Company facts (XBRL): https://data.sec.gov/api/xbrl/companyfacts/CIK{number}.json
"""

import json
import requests
import re
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus


# SEC EDGAR full-text search endpoint
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"

# Company submissions endpoint (filing history)
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# XBRL company facts endpoint (structured financial data)
EDGAR_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# SEC requires a User-Agent header with contact info
SEC_HEADERS = {
    "User-Agent": "QuiTamEngine/1.0 research@example.com",
    "Accept": "application/json",
}

# Known hospice/home health publicly traded companies with CIK numbers
HOSPICE_COMPANIES = [
    {
        "name": "Amedisys Inc.",
        "ticker": "AMED",
        "cik": "0000014846",
        "description": "One of the largest home health and hospice companies in the US",
    },
    {
        "name": "Enhabit Home Health & Hospice",
        "ticker": "EHAB",
        "cik": "0001903756",
        "description": "Spun off from Encompass Health in 2022; home health and hospice",
    },
    {
        "name": "Addus HomeCare Corporation",
        "ticker": "ADUS",
        "cik": "0001313275",
        "description": "Personal care, hospice, and home health services",
    },
    {
        "name": "LHC Group Inc.",
        "ticker": "LHCG",
        "cik": "0001303313",
        "description": "Home health, hospice, community-based services; acquired by UnitedHealth/Optum 2023",
    },
    {
        "name": "BrightSpring Health Services",
        "ticker": "BTSG",
        "cik": "0001996136",
        "description": "Pharmacy and provider services including hospice; IPO 2024; formerly PharMerica/BrightSpring",
    },
    {
        "name": "Chemed Corporation",
        "ticker": "CHE",
        "cik": "0000019584",
        "description": "Parent company of VITAS Healthcare (largest US hospice provider)",
    },
    {
        "name": "Kindred Healthcare LLC",
        "ticker": "KND",
        "cik": "0001060349",
        "description": "Formerly public; acquired by Humana; major hospice/home health operator",
    },
    {
        "name": "Encompass Health Corporation",
        "ticker": "EHC",
        "cik": "0000785557",
        "description": "Rehabilitation and home health; spun off Enhabit; prior hospice operations",
    },
    {
        "name": "National HealthCare Corporation",
        "ticker": "NHC",
        "cik": "0000800458",
        "description": "Skilled nursing, home health, and hospice services",
    },
    {
        "name": "Pennant Group Inc.",
        "ticker": "PNTG",
        "cik": "0001766400",
        "description": "Home health and hospice services; spun off from Ensign Group",
    },
]

# Keywords to search for in SEC filings that indicate legal/regulatory risk
LEGAL_RISK_KEYWORDS = [
    "False Claims Act",
    "qui tam",
    "government investigation",
    "Department of Justice",
    "DOJ",
    "Office of Inspector General",
    "OIG",
    "subpoena",
    "civil investigative demand",
    "corporate integrity agreement",
    "Medicare fraud",
    "hospice eligibility",
    "Anti-Kickback Statute",
    "Stark Law",
    "whistleblower",
    "settlement",
    "consent decree",
]


class SECEdgarIngester(BaseIngester):
    """
    Ingests SEC EDGAR filing data for publicly traded hospice companies.

    For each known hospice company, fetches:
    1. Recent filing list from the submissions endpoint
    2. XBRL financial facts (revenue, segments) from company facts API
    3. Full-text search results for hospice-related legal risk keywords
    """

    SOURCE_NAME = "sec_edgar"

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest SEC EDGAR data into SourceRecords.

        Args:
            db_session: SQLAlchemy session
            progress_callback: Optional callable(message, percent) for SSE updates

        Returns:
            dict with ingestion statistics
        """
        stats = {
            "source": self.SOURCE_NAME,
            "records_pulled": 0,
            "companies_queried": 0,
            "filings_found": 0,
            "legal_risk_mentions": 0,
            "errors": [],
        }

        total_companies = len(HOSPICE_COMPANIES)

        for idx, company in enumerate(HOSPICE_COMPANIES):
            if progress_callback:
                pct = int((idx / total_companies) * 100)
                progress_callback(
                    f"Fetching SEC filings for {company['name']} ({company['ticker']})...",
                    pct,
                )

            company_data = self._fetch_company_data(company)
            stats["companies_queried"] += 1

            if company_data.get("filings"):
                stats["filings_found"] += len(company_data["filings"])

            if company_data.get("legal_risk_count", 0) > 0:
                stats["legal_risk_mentions"] += company_data["legal_risk_count"]

            # Store as SourceRecord
            identifier = f"{company['ticker']}_{company['cik']}"
            source_record = SourceRecord(
                entity_id=None,
                source_name=self.SOURCE_NAME,
                source_identifier=identifier,
                raw_data=json.dumps(company_data, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)
            stats["records_pulled"] += 1

        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            stats["errors"].append(f"Database commit failed: {str(e)}")

        # ── Full-text search for hospice fraud keywords ──
        if progress_callback:
            progress_callback("Searching EDGAR full-text index for hospice fraud references...", None)

        search_results = self._search_edgar_fulltext()
        if search_results:
            for result in search_results:
                source_record = SourceRecord(
                    entity_id=None,
                    source_name=self.SOURCE_NAME,
                    source_identifier=f"search_{result.get('accession_number', 'unknown')}",
                    raw_data=json.dumps(result, default=str),
                    ingested_at=datetime.now().isoformat(),
                )
                db_session.add(source_record)
                stats["records_pulled"] += 1

            try:
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                stats["errors"].append(f"Search results commit failed: {str(e)}")

        # ── Update DataSourceStatus ──
        self._update_source_status(db_session, stats)

        return stats

    def _fetch_company_data(self, company: dict) -> dict:
        """
        Fetch filing history and financial facts for a single company.

        Args:
            company: dict with name, ticker, cik, description

        Returns:
            dict with company info, recent filings, financial facts,
            and legal risk keyword counts
        """
        cik = company["cik"]
        result = {
            "company_name": company["name"],
            "ticker": company["ticker"],
            "cik": cik,
            "description": company["description"],
            "filings": [],
            "financial_facts": {},
            "legal_risk_count": 0,
            "legal_risk_details": [],
            "fetch_errors": [],
        }

        # ── Fetch recent filings ──
        result["filings"] = self._fetch_submissions(cik, result["fetch_errors"])

        # ── Fetch XBRL financial facts ──
        result["financial_facts"] = self._fetch_company_facts(cik, result["fetch_errors"])

        # ── Scan filings for legal risk keywords ──
        risk_count, risk_details = self._scan_filings_for_risk(result["filings"])
        result["legal_risk_count"] = risk_count
        result["legal_risk_details"] = risk_details

        return result

    def _fetch_submissions(self, cik: str, errors: list) -> list[dict]:
        """
        Fetch the filing history for a company from EDGAR submissions endpoint.

        Returns:
            list of recent filing dicts (form type, date, accession number)
        """
        url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
        filings = []

        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if resp.status_code != 200:
                errors.append(f"Submissions API returned {resp.status_code} for CIK {cik}")
                return filings

            data = resp.json()
            recent = data.get("filings", {}).get("recent", {})

            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            descriptions = recent.get("primaryDocDescription", [])

            # Extract 10-K, 10-Q, 8-K filings from last few years
            target_forms = {"10-K", "10-Q", "8-K", "DEF 14A", "10-K/A", "10-Q/A"}

            for i in range(min(len(forms), len(dates), len(accessions))):
                form_type = forms[i] if i < len(forms) else ""
                filing_date = dates[i] if i < len(dates) else ""
                accession = accessions[i] if i < len(accessions) else ""
                desc = descriptions[i] if i < len(descriptions) else ""

                if form_type not in target_forms:
                    continue

                # Only include filings from 2020 onward
                if filing_date and filing_date < "2020-01-01":
                    continue

                filings.append({
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "accession_number": accession,
                    "description": desc,
                })

        except requests.exceptions.ConnectionError:
            errors.append(f"Connection error fetching submissions for CIK {cik}")
        except requests.exceptions.Timeout:
            errors.append(f"Timeout fetching submissions for CIK {cik}")
        except requests.exceptions.RequestException as e:
            errors.append(f"Request error for CIK {cik}: {str(e)}")
        except (ValueError, KeyError) as e:
            errors.append(f"Parse error for CIK {cik}: {str(e)}")

        return filings

    def _fetch_company_facts(self, cik: str, errors: list) -> dict:
        """
        Fetch XBRL company facts (structured financial data) from EDGAR.

        Extracts revenue, net income, and other key metrics.

        Returns:
            dict with extracted financial facts
        """
        url = EDGAR_COMPANY_FACTS_URL.format(cik=cik)
        facts = {}

        try:
            resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if resp.status_code != 200:
                errors.append(f"Company facts API returned {resp.status_code} for CIK {cik}")
                return facts

            data = resp.json()
            us_gaap = data.get("facts", {}).get("us-gaap", {})

            # Extract key financial metrics
            metrics_to_extract = {
                "Revenues": "total_revenue",
                "RevenueFromContractWithCustomerExcludingAssessedTax": "contract_revenue",
                "NetIncomeLoss": "net_income",
                "OperatingIncomeLoss": "operating_income",
                "CostOfRevenue": "cost_of_revenue",
                "CostOfGoodsAndServicesSold": "cogs",
                "Assets": "total_assets",
                "LongTermDebt": "long_term_debt",
                "LitigationSettlementAmountAwardedToOtherParty": "litigation_settlements",
                "LossContingencyEstimateOfPossibleLoss": "contingent_loss_estimate",
            }

            for gaap_concept, our_key in metrics_to_extract.items():
                concept_data = us_gaap.get(gaap_concept, {})
                units = concept_data.get("units", {})
                usd_values = units.get("USD", [])

                if usd_values:
                    # Get the most recent annual filing value
                    annual_values = [
                        v for v in usd_values
                        if v.get("form") == "10-K"
                    ]
                    if annual_values:
                        most_recent = sorted(
                            annual_values, key=lambda x: x.get("end", ""), reverse=True
                        )
                        if most_recent:
                            facts[our_key] = {
                                "value": most_recent[0].get("val"),
                                "period_end": most_recent[0].get("end"),
                                "form": most_recent[0].get("form"),
                                "filed": most_recent[0].get("filed"),
                            }

            # Calculate revenue per patient if data available
            revenue_val = facts.get("total_revenue", facts.get("contract_revenue", {}))
            if isinstance(revenue_val, dict) and revenue_val.get("value"):
                facts["latest_annual_revenue"] = revenue_val["value"]

        except requests.exceptions.ConnectionError:
            errors.append(f"Connection error fetching company facts for CIK {cik}")
        except requests.exceptions.Timeout:
            errors.append(f"Timeout fetching company facts for CIK {cik}")
        except requests.exceptions.RequestException as e:
            errors.append(f"Request error for company facts CIK {cik}: {str(e)}")
        except (ValueError, KeyError) as e:
            errors.append(f"Parse error for company facts CIK {cik}: {str(e)}")

        return facts

    def _scan_filings_for_risk(self, filings: list[dict]) -> tuple:
        """
        Scan filing descriptions for legal risk keywords.

        In a full implementation, this would fetch the actual filing
        documents and search their text. Here we check filing descriptions
        and flag 10-K filings which typically contain legal proceedings
        and risk factor sections.

        Returns:
            tuple of (risk_count, risk_details_list)
        """
        risk_count = 0
        risk_details = []

        for filing in filings:
            desc = (filing.get("description", "") or "").lower()
            form_type = filing.get("form_type", "")

            # 10-K filings always contain legal proceedings and risk factors
            if form_type in ("10-K", "10-K/A"):
                risk_details.append({
                    "filing": filing.get("accession_number"),
                    "form": form_type,
                    "date": filing.get("filing_date"),
                    "note": "Annual report contains Item 3 (Legal Proceedings) and Item 1A (Risk Factors) - manual review recommended",
                })

            # 8-K filings may disclose material legal events
            if form_type == "8-K":
                for keyword in LEGAL_RISK_KEYWORDS:
                    if keyword.lower() in desc:
                        risk_count += 1
                        risk_details.append({
                            "filing": filing.get("accession_number"),
                            "form": form_type,
                            "date": filing.get("filing_date"),
                            "keyword_matched": keyword,
                        })
                        break

        return risk_count, risk_details

    def _search_edgar_fulltext(self) -> list[dict]:
        """
        Search the EDGAR full-text search index for hospice fraud references.

        Queries for filings mentioning hospice in combination with
        False Claims Act, qui tam, or other legal risk terms.

        Returns:
            list of search result dicts, or empty list on failure
        """
        results = []

        search_queries = [
            '"hospice" AND "False Claims Act"',
            '"hospice" AND "qui tam"',
            '"hospice" AND "government investigation"',
            '"hospice" AND "Department of Justice" AND "settlement"',
        ]

        for query in search_queries:
            try:
                resp = requests.get(
                    "https://efts.sec.gov/LATEST/search-index",
                    params={
                        "q": query,
                        "dateRange": "custom",
                        "startdt": "2020-01-01",
                        "enddt": "2025-12-31",
                        "forms": "10-K,10-Q,8-K",
                    },
                    headers=SEC_HEADERS,
                    timeout=30,
                )

                if resp.status_code != 200:
                    continue

                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])

                for hit in hits[:20]:  # Limit to 20 per query
                    source = hit.get("_source", {})
                    results.append({
                        "query": query,
                        "company_name": source.get("display_names", [""])[0] if source.get("display_names") else "",
                        "form_type": source.get("form_type", ""),
                        "filing_date": source.get("file_date", ""),
                        "accession_number": source.get("file_num", ""),
                        "file_description": source.get("file_description", ""),
                    })

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
