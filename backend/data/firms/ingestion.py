"""
AGNIVISION-GIS: NASA FIRMS Ingestion Service
Coordinates authentic NASA FIRMS observation ingestion, range chunking,
normalization, data quality validation, and transactional deduplication into SQLite.
"""

import time
import logging
import datetime
from typing import Dict, Any, List, Optional, Union

from .client import (
    FIRMSClient,
    generate_date_chunks,
    DEFAULT_INDIA_BBOX,
    DEFAULT_NRT_SOURCES,
    HISTORICAL_SP_SOURCES
)
from .normalizer import normalize_firms_record
from .models import FIRMSDatabase

logger = logging.getLogger("agnivision.firms.ingestion")


class FIRMSIngestionService:
    """
    Ingestion orchestrator for current NRT and historical NASA FIRMS hotspot datasets.
    Provides batch processing, deduplication, quality tracking, and comprehensive ingestion metrics.
    """

    def __init__(self, client: Optional[FIRMSClient] = None, db: Optional[FIRMSDatabase] = None):
        self.client = client or FIRMSClient()
        self.db = db or FIRMSDatabase()

    def ingest_date_range(
        self,
        start_date: str,
        end_date: str,
        sources: Optional[List[str]] = None,
        bbox: Optional[Union[Dict[str, float], str]] = None
    ) -> Dict[str, Any]:
        """
        Ingests FIRMS thermal observations across an inclusive date range [start_date, end_date].
        Automatically divides the period into <= 5-day chunks, validates records,
        and saves unique records into SQLite.
        """
        start_time = time.time()

        # 1. Date range validation
        try:
            d_start = datetime.datetime.strptime(str(start_date).strip(), "%Y-%m-%d").date()
            d_end = datetime.datetime.strptime(str(end_date).strip(), "%Y-%m-%d").date()
        except ValueError as e:
            return {
                "status": "error",
                "error": f"Invalid date format: must be YYYY-MM-DD ({e})"
            }

        if d_start > d_end:
            return {
                "status": "error",
                "error": f"start_date ({start_date}) must be prior or equal to end_date ({end_date})"
            }

        # 2. Source and BBox resolution
        target_sources = sources or DEFAULT_NRT_SOURCES
        target_bbox = bbox or DEFAULT_INDIA_BBOX

        # 3. Generate NASA FIRMS valid chunks (<= 5 days per chunk)
        chunks = generate_date_chunks(d_start, d_end, max_chunk_days=5)

        total_downloaded = 0
        total_normalized = 0
        total_inserted = 0
        total_duplicates = 0
        total_rejected = 0
        rejection_breakdown: Dict[str, int] = {}
        errors: List[str] = []

        logger.info(
            f"[FIRMS_INGESTION] Ingesting range {start_date} -> {end_date} "
            f"({len(chunks)} chunks, {len(target_sources)} sources)"
        )

        # 4. Iterate over chunks and sources
        for chunk in chunks:
            c_start = chunk["start_date"]
            c_days = chunk["day_range"]

            for source in target_sources:
                raw_rows, err = self.client.fetch_chunk_csv(
                    source=source,
                    bbox=target_bbox,
                    day_range=c_days,
                    start_date=c_start
                )

                if err:
                    logger.warning(f"[FIRMS_INGESTION] Chunk {c_start} ({source}) error: {err}")
                    errors.append(f"{source} [{c_start}]: {err}")
                    continue

                total_downloaded += len(raw_rows)
                valid_batch: List[Dict[str, Any]] = []

                for row in raw_rows:
                    normalized, reject_reason = normalize_firms_record(
                        row,
                        source=source,
                        source_request_date=c_start
                    )
                    if reject_reason:
                        total_rejected += 1
                        rejection_breakdown[reject_reason] = rejection_breakdown.get(reject_reason, 0) + 1
                    elif normalized:
                        valid_batch.append(normalized)

                total_normalized += len(valid_batch)

                # Batch insert into database with deterministic deduplication
                if valid_batch:
                    inserted, dupes = self.db.insert_hotspots(valid_batch)
                    total_inserted += inserted
                    total_duplicates += dupes

        elapsed = round(time.time() - start_time, 2)

        stats = {
            "status": "success" if not errors or total_inserted > 0 else "partial_error",
            "requested_start": start_date,
            "requested_end": end_date,
            "chunks_count": len(chunks),
            "sources": target_sources,
            "downloaded": total_downloaded,
            "normalized": total_normalized,
            "inserted": total_inserted,
            "duplicates": total_duplicates,
            "rejected": total_rejected,
            "rejection_breakdown": rejection_breakdown,
            "errors": errors,
            "duration_seconds": elapsed
        }

        logger.info(
            f"[FIRMS_INGESTION] Completed range {start_date} -> {end_date}: "
            f"{total_inserted} inserted, {total_duplicates} duplicates, {total_rejected} rejected in {elapsed}s"
        )
        return stats

    def sync_recent_firms(
        self,
        days: int = 3,
        sources: Optional[List[str]] = None,
        bbox: Optional[Union[Dict[str, float], str]] = None
    ) -> Dict[str, Any]:
        """
        Synchronizes recent N days of FIRMS observations up to current date.
        Re-fetching recent days guarantees delayed FIRMS processing passes are captured
        while deterministic deduplication prevents database pollution.
        """
        safe_days = max(1, min(int(days), 10))
        today = datetime.date.today()
        start = today - datetime.timedelta(days=safe_days - 1)
        return self.ingest_date_range(
            start_date=start.strftime("%Y-%m-%d"),
            end_date=today.strftime("%Y-%m-%d"),
            sources=sources or DEFAULT_NRT_SOURCES,
            bbox=bbox
        )

    def backfill_historical(
        self,
        start_date: str,
        end_date: str,
        sources: Optional[List[str]] = None,
        bbox: Optional[Union[Dict[str, float], str]] = None
    ) -> Dict[str, Any]:
        """
        Backfills historical observations using Standard Processing (SP) archive sources.
        """
        historical_sources = sources or HISTORICAL_SP_SOURCES
        return self.ingest_date_range(
            start_date=start_date,
            end_date=end_date,
            sources=historical_sources,
            bbox=bbox
        )
