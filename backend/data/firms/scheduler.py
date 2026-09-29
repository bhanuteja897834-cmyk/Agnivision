"""
AGNIVISION-GIS: Automatic NASA FIRMS Synchronization Scheduler (Stage 2C)
Provides periodic background synchronization of NASA FIRMS NRT hotspots,
thread-safe execution locks, graceful error recovery, and comprehensive status tracking.
"""

import os
import time
import logging
import threading
import datetime
from typing import Dict, Any, Optional, List, Union

from .ingestion import FIRMSIngestionService
from .client import DEFAULT_INDIA_BBOX, DEFAULT_NRT_SOURCES

logger = logging.getLogger("agnivision.firms.scheduler")

# Default environment configurations
DEFAULT_SYNC_INTERVAL_SECONDS = 900  # 15 minutes near-real-time
DEFAULT_SYNC_DAYS = 3  # Recent 3 days window


class FIRMSAutoSyncScheduler:
    """
    Manages periodic synchronization of NASA FIRMS NRT data in a background daemon thread.
    Features:
    - Configurable interval via FIRMS_AUTO_SYNC_INTERVAL_SECONDS (default: 15m / 900s near-real-time).
    - Toggle via FIRMS_AUTO_SYNC_ENABLED (default: true).
    - Mutual exclusion lock to prevent concurrent auto and manual sync jobs.
    - Graceful error recovery: failure to reach NASA FIRMS never crashes FastAPI.
    - Zero historical data deletion: relies on SHA-256 deduplication in SQLite.
    - Comprehensive status reporting for GET /api/v1/hotspots/sync/status.
    """

    def __init__(
        self,
        ingestion_service: Optional[FIRMSIngestionService] = None,
        enabled: Optional[bool] = None,
        interval_seconds: Optional[int] = None,
        sync_days: Optional[int] = None
    ):
        self.ingestion_service = ingestion_service or FIRMSIngestionService()

        # Configuration from arguments or environment variables
        env_enabled = os.environ.get("FIRMS_AUTO_SYNC_ENABLED", "true").strip().lower()
        self.enabled = (
            enabled if enabled is not None
            else env_enabled in ("true", "1", "yes", "on")
        )

        env_interval = os.environ.get("FIRMS_AUTO_SYNC_INTERVAL_SECONDS")
        try:
            self.interval_seconds = (
                int(interval_seconds) if interval_seconds is not None
                else int(env_interval) if env_interval
                else DEFAULT_SYNC_INTERVAL_SECONDS
            )
        except ValueError:
            self.interval_seconds = DEFAULT_SYNC_INTERVAL_SECONDS

        env_days = os.environ.get("FIRMS_AUTO_SYNC_DAYS")
        try:
            self.sync_days = (
                int(sync_days) if sync_days is not None
                else int(env_days) if env_days
                else DEFAULT_SYNC_DAYS
            )
        except ValueError:
            self.sync_days = DEFAULT_SYNC_DAYS

        # Synchronization lock & lifecycle primitives
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Status tracking metrics
        self.is_syncing: bool = False
        self.last_sync_started_at: Optional[str] = None
        self.last_sync_completed_at: Optional[str] = None
        self.last_successful_sync_completed_at: Optional[str] = None
        self.last_sync_status: Optional[str] = None
        self.last_sync_inserted: int = 0
        self.last_sync_duplicates: int = 0
        self.last_sync_error: Optional[str] = None
        self.next_sync_at: Optional[str] = None
        self.sync_count: int = 0

    def _update_next_sync_time(self) -> None:
        """Computes the expected next synchronization time."""
        if self.enabled:
            next_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                seconds=self.interval_seconds
            )
            self.next_sync_at = next_time.isoformat()
        else:
            self.next_sync_at = None

    def trigger_sync(
        self,
        is_manual: bool = False,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sources: Optional[List[str]] = None,
        bbox: Optional[Union[Dict[str, float], str]] = None
    ) -> Dict[str, Any]:
        """
        Executes a synchronization job with concurrency protection.
        Guarantees that overlapping requests return a 'busy' status rather than running concurrently.
        """
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            logger.warning("[FIRMS_SYNC] Concurrency guard: A synchronization job is already running.")
            return {
                "status": "busy",
                "message": "A FIRMS synchronization job is already in progress.",
                "sync_in_progress": True
            }

        try:
            self.is_syncing = True
            started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.last_sync_started_at = started_at
            self.last_sync_status = "running"
            self.last_sync_error = None

            logger.info(
                f"[FIRMS_SYNC] Starting {'manual' if is_manual else 'automatic'} sync "
                f"(window: {start_date} -> {end_date} or days={days or self.sync_days})..."
            )

            # Ingest observations
            if start_date and end_date:
                res = self.ingestion_service.ingest_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    sources=sources or DEFAULT_NRT_SOURCES,
                    bbox=bbox or DEFAULT_INDIA_BBOX
                )
            else:
                target_days = days or self.sync_days
                res = self.ingestion_service.sync_recent_firms(
                    days=target_days,
                    sources=sources or DEFAULT_NRT_SOURCES,
                    bbox=bbox or DEFAULT_INDIA_BBOX
                )

            completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.last_sync_completed_at = completed_at
            self.sync_count += 1

            if res.get("status") in ("success", "partial_error"):
                self.last_sync_status = "success" if res.get("status") == "success" else "partial_error"
                self.last_sync_inserted = res.get("inserted", 0)
                self.last_sync_duplicates = res.get("duplicates", 0)
                self.last_successful_sync_completed_at = completed_at
                if res.get("errors"):
                    self.last_sync_error = "; ".join(res["errors"])
                else:
                    self.last_sync_error = None
            else:
                self.last_sync_status = "failed"
                self.last_sync_error = res.get("error") or "Ingestion failed"

            logger.info(
                f"[FIRMS_SYNC] Finished sync: status={self.last_sync_status}, "
                f"inserted={self.last_sync_inserted}, duplicates={self.last_sync_duplicates}"
            )
            return res

        except Exception as e:
            completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.last_sync_completed_at = completed_at
            self.last_sync_status = "failed"
            self.last_sync_error = str(e)
            logger.error(f"[FIRMS_SYNC] Exception during sync: {e}")
            return {
                "status": "error",
                "error": f"Internal sync failure: {str(e)}"
            }
        finally:
            self.is_syncing = False
            self._update_next_sync_time()
            self._lock.release()

    def _worker_loop(self) -> None:
        """Background thread loop that executes periodic synchronization."""
        logger.info(
            f"[FIRMS_SYNC] Background worker thread started. "
            f"Interval: {self.interval_seconds}s, AutoSync: {self.enabled}"
        )
        self._update_next_sync_time()

        # Grace period before initial startup sync to ensure full application initialization
        if not self._stop_event.wait(timeout=10.0):
            try:
                logger.info("[FIRMS_SYNC] Executing initial startup synchronization...")
                self.trigger_sync(is_manual=False)
            except Exception as e:
                logger.warning(f"[FIRMS_SYNC] Initial startup sync encountered error: {e}")

        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=float(self.interval_seconds)):
                break

            try:
                logger.info("[FIRMS_SYNC] Interval elapsed. Executing scheduled synchronization...")
                self.trigger_sync(is_manual=False)
            except Exception as e:
                logger.error(f"[FIRMS_SYNC] Scheduled synchronization exception: {e}")

        logger.info("[FIRMS_SYNC] Background worker thread terminated cleanly.")

    def start(self) -> None:
        """Starts the automatic background sync scheduler thread if enabled."""
        if not self.enabled:
            logger.info("[FIRMS_SYNC] Automatic sync scheduler is DISABLED via configuration.")
            return

        if self._thread and self._thread.is_alive():
            logger.warning("[FIRMS_SYNC] Scheduler worker thread is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="agnivision-firms-autosync",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[FIRMS_SYNC] Automatic scheduler started successfully "
            f"(interval: {self.interval_seconds} seconds)."
        )

    def stop(self) -> None:
        """Signals the background worker thread to stop cleanly and waits for termination."""
        if self._thread and self._thread.is_alive():
            logger.info("[FIRMS_SYNC] Stopping background sync scheduler...")
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
            logger.info("[FIRMS_SYNC] Background sync scheduler stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Returns the current synchronization status dictionary."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        sync_age_seconds = None
        if self.last_successful_sync_completed_at:
            try:
                last_dt = datetime.datetime.fromisoformat(self.last_successful_sync_completed_at)
                sync_age_seconds = max(0, int((now_utc - last_dt).total_seconds()))
            except Exception:
                sync_age_seconds = None

        # Stale threshold: 2 * interval_seconds (e.g. > 1800s for 15-min interval)
        is_stale = False
        if sync_age_seconds is not None and self.enabled:
            is_stale = sync_age_seconds > (self.interval_seconds * 2)

        return {
            "status": "success",
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "sync_days": self.sync_days,
            "is_syncing": self.is_syncing,
            "last_sync_started_at": self.last_sync_started_at,
            "last_sync_completed_at": self.last_sync_completed_at,
            "last_successful_sync_completed_at": self.last_successful_sync_completed_at,
            "last_successful_sync_age_seconds": sync_age_seconds,
            "is_stale": is_stale,
            "monitoring_label": "NASA FIRMS near-real-time monitoring",
            "last_sync_status": self.last_sync_status,
            "last_sync_inserted": self.last_sync_inserted,
            "last_sync_duplicates": self.last_sync_duplicates,
            "last_sync_error": self.last_sync_error,
            "next_sync_at": self.next_sync_at if self.enabled else None,
            "sync_count": self.sync_count
        }
