"""
Base ingester abstract class.
All data source ingesters inherit from this.
"""

from abc import ABC, abstractmethod


class BaseIngester(ABC):
    """Abstract base class for data source ingesters."""

    @abstractmethod
    async def ingest(self, db_session, progress_callback=None) -> dict:
        """
        Ingest data from the source and store as SourceRecords.

        Args:
            db_session: SQLAlchemy session
            progress_callback: Optional callable(message, percent) for SSE updates

        Returns:
            dict with ingestion statistics
        """
        ...
