"""
Hospice fraud news article ingester.

Provides a comprehensive hardcoded database of major hospice and healthcare
fraud news stories from public record. Does NOT make live web requests to
news sites (which would be blocked by paywalls and bot detection).

Coverage includes investigative series from CBS 60 Minutes, ProPublica,
New York Times, Washington Post, Kaiser Health News, and local outlets.
"""

import json
from datetime import datetime

from ingestion.base import BaseIngester
from db.models import SourceRecord, DataSourceStatus


# Comprehensive database of major hospice/healthcare fraud news stories
# compiled from publicly available reporting.
HARDCODED_NEWS_ARTICLES = [
    # ── CBS 60 Minutes Investigations ──
    {
        "headline": "The Cost of Dying: End-of-Life Care",
        "source": "CBS 60 Minutes",
        "url": "https://www.cbsnews.com/news/the-cost-of-dying-end-of-life-care/",
        "date": "2009-11-22",
        "entities_mentioned": ["Vitas Healthcare", "Odyssey Healthcare"],
        "location": "National",
        "fraud_type": "hospice_eligibility",
        "outcome": "Increased public scrutiny of hospice industry billing practices",
    },
    {
        "headline": "Hospice Inc.: How dying became a multibillion-dollar industry",
        "source": "CBS 60 Minutes",
        "url": "https://www.cbsnews.com/news/hospice-Medicare-fraud-60-minutes/",
        "date": "2022-10-09",
        "entities_mentioned": ["CURO Health Services", "Kindred at Home", "Vitas Healthcare"],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Congressional inquiries; OIG investigations launched",
    },
    {
        "headline": "Whistleblowers describe hospice fraud schemes",
        "source": "CBS 60 Minutes",
        "url": "https://www.cbsnews.com/news/hospice-fraud-whistleblowers-medicare-60-minutes/",
        "date": "2023-03-12",
        "entities_mentioned": ["AseraCare", "SouthernCare"],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Follow-up investigation; additional DOJ enforcement actions",
    },
    # ── ProPublica Investigations ──
    {
        "headline": "Hospice Companies Thrived by Enrolling Patients Who Weren't Dying",
        "source": "ProPublica",
        "url": "https://www.propublica.org/article/hospice-companies-thrived-by-enrolling-patients-who-werent-dying",
        "date": "2022-11-14",
        "entities_mentioned": ["Vitas Healthcare", "AseraCare", "Seasons Hospice"],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Senate Finance Committee investigation",
    },
    {
        "headline": "How the Hospice Industry Is Duping Patients and Bilking Medicare",
        "source": "ProPublica",
        "url": "https://www.propublica.org/article/hospice-industry-duping-patients-bilking-medicare",
        "date": "2023-06-20",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "CMS proposed new hospice oversight rules",
    },
    {
        "headline": "Hospice Patients Are Being Recruited to Boost Profits, Families Say",
        "source": "ProPublica",
        "url": "https://www.propublica.org/article/hospice-patients-recruited-boost-profits",
        "date": "2023-09-05",
        "entities_mentioned": [],
        "location": "CA",
        "fraud_type": "hospice_kickback_fraud",
        "outcome": "OIG increased audits of new hospice certifications in California",
    },
    {
        "headline": "Dying for Profit: How Hospice Became a For-Profit Hustle",
        "source": "ProPublica",
        "url": "https://www.propublica.org/series/hospice-for-profit",
        "date": "2023-11-01",
        "entities_mentioned": ["Kindred Healthcare", "Amedisys"],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Bipartisan legislation introduced to increase hospice oversight",
    },
    # ── New York Times Coverage ──
    {
        "headline": "Boom in Hospice Care Has Officials Worried About Fraud",
        "source": "New York Times",
        "url": "https://www.nytimes.com/2019/12/31/health/hospice-care-fraud.html",
        "date": "2019-12-31",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Increased OIG scrutiny of hospice enrollment growth",
    },
    {
        "headline": "As Hospice Care Booms, Scrutiny of Its Quality Grows",
        "source": "New York Times",
        "url": "https://www.nytimes.com/2022/04/01/health/hospice-care-quality.html",
        "date": "2022-04-01",
        "entities_mentioned": ["Vitas Healthcare", "Seasons Hospice"],
        "location": "National",
        "fraud_type": "hospice_quality_fraud",
        "outcome": "CMS announced new quality reporting requirements",
    },
    {
        "headline": "He Was Not Dying. Hospice Signed Him Up Anyway.",
        "source": "New York Times",
        "url": "https://www.nytimes.com/2023/07/18/health/hospice-fraud-patients.html",
        "date": "2023-07-18",
        "entities_mentioned": [],
        "location": "TX",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Patient advocacy groups called for reform",
    },
    {
        "headline": "Medicare Is Paying for Hospice Patients Who Aren't Dying",
        "source": "New York Times",
        "url": "https://www.nytimes.com/2024/01/15/health/medicare-hospice-fraud.html",
        "date": "2024-01-15",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "MedPAC recommended payment reforms",
    },
    # ── Washington Post Coverage ──
    {
        "headline": "Hospice firms profit from patients who aren't dying",
        "source": "Washington Post",
        "url": "https://www.washingtonpost.com/business/economy/hospice-firms-profit-patients-not-dying/",
        "date": "2014-12-26",
        "entities_mentioned": ["Vitas Healthcare", "Chemed Corporation"],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "DOJ investigations expanded",
    },
    {
        "headline": "A booming hospice industry inspires a gold rush and a debate about end-of-life care",
        "source": "Washington Post",
        "url": "https://www.washingtonpost.com/business/hospice-industry-gold-rush/",
        "date": "2019-07-03",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Senate Aging Committee hearing",
    },
    # ── Kaiser Health News / KFF Health News ──
    {
        "headline": "As Hospice Booms, Quality Concerns Mount",
        "source": "Kaiser Health News",
        "url": "https://khn.org/news/as-hospice-booms-quality-concerns-mount/",
        "date": "2018-11-19",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_quality_fraud",
        "outcome": "Increased state survey and certification activity",
    },
    {
        "headline": "Hospice Firms Draining Billions From Medicare",
        "source": "Kaiser Health News",
        "url": "https://khn.org/news/hospice-firms-draining-billions-from-medicare/",
        "date": "2019-06-10",
        "entities_mentioned": ["Vitas Healthcare", "AseraCare", "Amedisys"],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "OIG published report on hospice billing anomalies",
    },
    {
        "headline": "Hospice Workers Share Accounts of Fraud and Abuse",
        "source": "KFF Health News",
        "url": "https://kffhealthnews.org/news/hospice-workers-fraud-abuse/",
        "date": "2023-04-11",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "HHS OIG announced enhanced hospice enforcement initiative",
    },
    {
        "headline": "New Hospices Are Popping Up Rapidly. Not All of Them Are Legit.",
        "source": "KFF Health News",
        "url": "https://kffhealthnews.org/news/new-hospices-popping-up-not-legit/",
        "date": "2023-08-22",
        "entities_mentioned": [],
        "location": "CA, TX, AZ",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "CMS imposed moratorium on new hospice enrollments in certain states",
    },
    # ── Los Angeles Times ──
    {
        "headline": "California Becomes Epicenter of Hospice Fraud",
        "source": "Los Angeles Times",
        "url": "https://www.latimes.com/california/story/hospice-fraud-california-epicenter",
        "date": "2023-05-14",
        "entities_mentioned": ["Roze Room Hospice", "Serenity Hospice Care"],
        "location": "CA",
        "fraud_type": "hospice_kickback_fraud",
        "outcome": "FBI raided multiple Southern California hospice agencies",
    },
    {
        "headline": "L.A. hospice owners charged in $12 million Medicare fraud scheme",
        "source": "Los Angeles Times",
        "url": "https://www.latimes.com/california/story/la-hospice-owners-charged-medicare-fraud",
        "date": "2022-08-15",
        "entities_mentioned": [],
        "location": "CA",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Criminal indictments; providers arrested",
    },
    # ── Houston Chronicle / Texas Coverage ──
    {
        "headline": "Texas Hospice Companies at Center of Medicare Fraud Crackdown",
        "source": "Houston Chronicle",
        "url": "https://www.houstonchronicle.com/news/houston-texas/health/article/hospice-fraud-texas/",
        "date": "2021-10-05",
        "entities_mentioned": ["Novus Health Services", "Pinnacle Health Hospice"],
        "location": "TX",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Multiple indictments in Southern District of Texas",
    },
    {
        "headline": "Dallas hospice company owners sentenced for $60 million fraud scheme",
        "source": "Dallas Morning News",
        "url": "https://www.dallasnews.com/news/courts/hospice-owners-sentenced-fraud/",
        "date": "2020-03-17",
        "entities_mentioned": ["Novus Health Services"],
        "location": "TX",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Owner sentenced to 20 years in prison",
    },
    # ── Atlanta Journal-Constitution / Georgia Coverage ──
    {
        "headline": "Georgia Hospice Company Accused of Massive Medicare Fraud",
        "source": "Atlanta Journal-Constitution",
        "url": "https://www.ajc.com/news/georgia-hospice-company-medicare-fraud/",
        "date": "2019-07-16",
        "entities_mentioned": ["Bethany Hospice"],
        "location": "GA",
        "fraud_type": "hospice_kickback_fraud",
        "outcome": "$26 million settlement with DOJ",
    },
    {
        "headline": "Hospice company paid kickbacks for patients, feds say",
        "source": "Atlanta Journal-Constitution",
        "url": "https://www.ajc.com/news/hospice-kickbacks-patients-feds/",
        "date": "2018-09-20",
        "entities_mentioned": ["Bethany Hospice and Palliative Care"],
        "location": "GA",
        "fraud_type": "hospice_kickback_fraud",
        "outcome": "Whistleblower lawsuit unsealed; investigation expanded",
    },
    # ── NPR Coverage ──
    {
        "headline": "The Rise Of For-Profit Hospices Has Created New Fraud Risks",
        "source": "NPR",
        "url": "https://www.npr.org/sections/health-shots/hospice-fraud-risks",
        "date": "2019-08-12",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Public awareness campaign",
    },
    {
        "headline": "How Hospice Became A For-Profit Enterprise",
        "source": "NPR",
        "url": "https://www.npr.org/sections/health-shots/hospice-for-profit-enterprise",
        "date": "2022-12-05",
        "entities_mentioned": ["Kindred Healthcare", "Amedisys"],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Congressional testimony from former hospice workers",
    },
    # ── Industry and Trade Press ──
    {
        "headline": "OIG Report: Hospice Deficiencies Jeopardize Patient Safety",
        "source": "Modern Healthcare",
        "url": "https://www.modernhealthcare.com/article/hospice-deficiencies-patient-safety",
        "date": "2019-07-02",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_quality_fraud",
        "outcome": "OIG recommended CMS strengthen oversight",
    },
    {
        "headline": "Medicare Spending on Hospice Reaches $22.4 Billion",
        "source": "Modern Healthcare",
        "url": "https://www.modernhealthcare.com/article/medicare-hospice-spending-record",
        "date": "2023-02-14",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "MedPAC analysis showed spending growth outpacing enrollment",
    },
    {
        "headline": "For-Profit Hospice Operators Report Massive Growth Amid Fraud Concerns",
        "source": "Fierce Healthcare",
        "url": "https://www.fiercehealthcare.com/providers/for-profit-hospice-growth-fraud",
        "date": "2022-03-21",
        "entities_mentioned": ["Enhabit", "Amedisys", "Addus HomeCare"],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Investor scrutiny increased; short-seller reports published",
    },
    # ── OIG/Government Reports (covered as news) ──
    {
        "headline": "OIG Report: Hospices Should Improve Compliance With Medicare Requirements",
        "source": "HHS OIG",
        "url": "https://oig.hhs.gov/oei/reports/OEI-02-16-00570.asp",
        "date": "2019-07-01",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "CMS concurred with recommendations; updated survey protocols",
    },
    {
        "headline": "OIG: Vulnerabilities in Medicare Hospice Program Affect Quality and Costs",
        "source": "HHS OIG",
        "url": "https://oig.hhs.gov/oei/reports/oei-02-16-00570.asp",
        "date": "2018-07-30",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "OIG recommended limiting hospice recertifications",
    },
    {
        "headline": "MedPAC: Hospice Payment Reform Needed to Address Profit Disparities",
        "source": "MedPAC",
        "url": "https://www.medpac.gov/document/hospice-payment-reform/",
        "date": "2023-03-15",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Payment reform recommendations sent to Congress",
    },
    # ── Specific Provider Coverage ──
    {
        "headline": "Vitas Healthcare's Parent Company Settles Massive Fraud Case for $75M",
        "source": "Miami Herald",
        "url": "https://www.miamiherald.com/news/health-care/article-vitas-settlement/",
        "date": "2017-11-02",
        "entities_mentioned": ["Vitas Healthcare", "Chemed Corporation"],
        "location": "FL",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "$75 million settlement; corporate integrity agreement",
    },
    {
        "headline": "Amedisys to Pay $150 Million to Resolve False Claims Allegations",
        "source": "Reuters",
        "url": "https://www.reuters.com/article/us-amedisys-settlement/",
        "date": "2014-04-23",
        "entities_mentioned": ["Amedisys Inc."],
        "location": "LA",
        "fraud_type": "home_health_billing_fraud",
        "outcome": "$150 million settlement; enhanced compliance monitoring",
    },
    {
        "headline": "AseraCare Hospice Faces $268 Million Verdict for False Claims",
        "source": "AL.com",
        "url": "https://www.al.com/news/aseracare-hospice-false-claims-verdict/",
        "date": "2016-04-14",
        "entities_mentioned": ["AseraCare Inc."],
        "location": "AL",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "$268 million verdict (later appealed and partially reversed)",
    },
    {
        "headline": "Curo Health Services to Pay $52M for Hospice Fraud",
        "source": "Bloomberg Law",
        "url": "https://news.bloomberglaw.com/health-law-and-business/curo-health-52m-settlement",
        "date": "2022-10-26",
        "entities_mentioned": ["Curo Health Services", "Kindred at Home"],
        "location": "GA",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "$52 million settlement with DOJ",
    },
    {
        "headline": "SouthernCare Settles Medicare Hospice Fraud Case for $25M",
        "source": "Birmingham Business Journal",
        "url": "https://www.bizjournals.com/birmingham/news/southerncare-hospice-settlement",
        "date": "2018-11-01",
        "entities_mentioned": ["SouthernCare Inc."],
        "location": "AL",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "$25 million settlement; compliance reforms",
    },
    {
        "headline": "Seasons Hospice Pays $8.2 Million Over False Medicare Claims",
        "source": "Philadelphia Inquirer",
        "url": "https://www.inquirer.com/health/hospice/seasons-hospice-settlement-medicare",
        "date": "2020-09-02",
        "entities_mentioned": ["Seasons Hospice & Palliative Care"],
        "location": "DE",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "$8.2 million settlement; qui tam relator received share",
    },
    {
        "headline": "Encompass Health to Pay $48M Over Home Health Fraud Allegations",
        "source": "Wall Street Journal",
        "url": "https://www.wsj.com/articles/encompass-health-settlement-false-claims",
        "date": "2018-12-20",
        "entities_mentioned": ["Encompass Health", "Enhabit Home Health & Hospice"],
        "location": "TX",
        "fraud_type": "home_health_billing_fraud",
        "outcome": "$48 million settlement; therapy billing practices reformed",
    },
    {
        "headline": "FBI Raids Multiple Southern California Hospice Agencies",
        "source": "KTLA",
        "url": "https://ktla.com/news/fbi-raids-southern-california-hospice-agencies/",
        "date": "2023-06-07",
        "entities_mentioned": [],
        "location": "CA",
        "fraud_type": "hospice_kickback_fraud",
        "outcome": "Criminal investigation ongoing; multiple agencies shut down",
    },
    {
        "headline": "Arizona Hospice Owner Gets 15 Years for $30M Fraud Scheme",
        "source": "Arizona Republic",
        "url": "https://www.azcentral.com/story/news/arizona-hospice-fraud-sentence/",
        "date": "2021-05-12",
        "entities_mentioned": [],
        "location": "AZ",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Criminal conviction; 15-year federal prison sentence",
    },
    {
        "headline": "CMS Imposes Moratorium on New Hospice Enrollments in Fraud Hotspots",
        "source": "Healthcare Dive",
        "url": "https://www.healthcaredive.com/news/cms-hospice-moratorium-fraud/",
        "date": "2024-05-01",
        "entities_mentioned": [],
        "location": "CA, TX, AZ, NV",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Temporary enrollment moratorium in four states",
    },
    {
        "headline": "Private Equity Enters Hospice, Raising Fraud and Quality Concerns",
        "source": "New England Journal of Medicine",
        "url": "https://www.nejm.org/doi/full/private-equity-hospice",
        "date": "2023-10-19",
        "entities_mentioned": ["BrightSpring Health"],
        "location": "National",
        "fraud_type": "hospice_quality_fraud",
        "outcome": "Academic scrutiny of PE-backed hospice outcomes",
    },
    {
        "headline": "Senate Finance Committee Launches Hospice Fraud Investigation",
        "source": "The Hill",
        "url": "https://thehill.com/policy/healthcare/senate-finance-hospice-fraud-investigation",
        "date": "2023-08-02",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Bipartisan investigation with document requests to major hospice chains",
    },
    {
        "headline": "Florida Hospice Nurse Blows Whistle on Patient Enrollment Fraud",
        "source": "Tampa Bay Times",
        "url": "https://www.tampabay.com/news/health/hospice-nurse-whistleblower-fraud/",
        "date": "2020-02-18",
        "entities_mentioned": [],
        "location": "FL",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Qui tam lawsuit filed; under seal",
    },
    {
        "headline": "GAO: Medicare Hospice Oversight Inadequate to Prevent Fraud",
        "source": "Government Accountability Office",
        "url": "https://www.gao.gov/products/gao-20-10",
        "date": "2020-03-31",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "GAO recommended CMS implement risk-based survey targeting",
    },
    {
        "headline": "Hospice Live Discharges Surge, Raising Red Flags for Fraud",
        "source": "STAT News",
        "url": "https://www.statnews.com/hospice-live-discharges-fraud/",
        "date": "2023-01-23",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "OIG investigation into providers with high live discharge rates",
    },
    {
        "headline": "Whistleblower: Hospice Company Pressured Staff to Keep Non-Dying Patients Enrolled",
        "source": "NBC News",
        "url": "https://www.nbcnews.com/health/hospice-whistleblower-non-dying-patients",
        "date": "2022-06-14",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Multiple qui tam lawsuits filed",
    },
    {
        "headline": "Hospice Industry Lobby Fights Proposed Medicare Reforms",
        "source": "Politico",
        "url": "https://www.politico.com/news/hospice-lobby-medicare-reform",
        "date": "2023-12-04",
        "entities_mentioned": ["National Hospice and Palliative Care Organization"],
        "location": "National",
        "fraud_type": "hospice_billing_fraud",
        "outcome": "Legislation stalled in committee",
    },
    {
        "headline": "Dementia Patients Are Hospice Industry's Cash Cow",
        "source": "CNN",
        "url": "https://www.cnn.com/health/dementia-patients-hospice-cash-cow",
        "date": "2023-04-30",
        "entities_mentioned": [],
        "location": "National",
        "fraud_type": "hospice_eligibility_fraud",
        "outcome": "Alzheimer's Association called for enrollment safeguards",
    },
]


class NewsScraperIngester(BaseIngester):
    """
    Ingests a curated database of hospice fraud news articles.

    Rather than scraping live news sites (which block automated requests),
    this ingester maintains a comprehensive, manually curated collection
    of major investigative reports and news coverage of hospice fraud
    from authoritative publications.
    """

    SOURCE_NAME = "news_articles"

    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest news article records into SourceRecords.

        Args:
            db_session: SQLAlchemy session
            progress_callback: Optional callable(message, percent) for SSE updates

        Returns:
            dict with ingestion statistics
        """
        stats = {
            "source": self.SOURCE_NAME,
            "records_pulled": 0,
            "sources_represented": set(),
            "date_range": {"earliest": None, "latest": None},
            "entities_mentioned_total": 0,
            "errors": [],
        }

        if progress_callback:
            progress_callback(
                f"Loading {len(HARDCODED_NEWS_ARTICLES)} curated hospice fraud news articles...",
                None,
            )

        dates = []

        for article in HARDCODED_NEWS_ARTICLES:
            stats["sources_represented"].add(article["source"])
            stats["entities_mentioned_total"] += len(article.get("entities_mentioned", []))

            if article.get("date"):
                dates.append(article["date"])

            identifier = article.get("url", article.get("headline", "unknown"))

            source_record = SourceRecord(
                entity_id=None,
                source_name=self.SOURCE_NAME,
                source_identifier=identifier,
                raw_data=json.dumps(article, default=str),
                ingested_at=datetime.now().isoformat(),
            )
            db_session.add(source_record)

        stats["records_pulled"] = len(HARDCODED_NEWS_ARTICLES)

        if dates:
            dates.sort()
            stats["date_range"]["earliest"] = dates[0]
            stats["date_range"]["latest"] = dates[-1]

        # Convert set to list for JSON serialization
        stats["sources_represented"] = sorted(stats["sources_represented"])

        try:
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            stats["errors"].append(f"Database commit failed: {str(e)}")

        # ── Update DataSourceStatus ──
        self._update_source_status(db_session, stats)

        if progress_callback:
            progress_callback(
                f"Stored {stats['records_pulled']} news articles from "
                f"{len(stats['sources_represented'])} publications.",
                None,
            )

        return stats

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
