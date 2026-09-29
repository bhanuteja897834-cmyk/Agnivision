"""
AGNIVISION-GIS: Unit and Integration Tests for NASA FIRMS Automatic Sync Scheduler (Stage 2C)
Covers:
1. Scheduler initialization & configuration (default and environment variables).
2. Disabled scheduler behavior (FIRMS_AUTO_SYNC_ENABLED=false).
3. Concurrency protection (mutual exclusion between simultaneous sync jobs).
4. Status tracking & reporting format (GET /api/v1/hotspots/sync/status).
5. Graceful handling of FIRMS API errors & network failures without crashing.
6. Successful synchronization & duplicate skipping metrics.
7. Manual sync endpoint (POST /api/v1/hotspots/sync) behavior and 409 on busy.
8. Preservation of historical data and existing query endpoint (GET /api/v1/hotspots).
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

try:
    from backend.data.firms import (
        FIRMSAutoSyncScheduler,
        FIRMSIngestionService,
        FIRMSDatabase,
        FIRMSClient
    )
    import backend.main as main_module
except ImportError:
    from data.firms import (
        FIRMSAutoSyncScheduler,
        FIRMSIngestionService,
        FIRMSDatabase,
        FIRMSClient
    )
    import main as main_module


class TestFIRMSAutoSync(unittest.TestCase):
    def setUp(self):
        self.mock_ingestion = MagicMock(spec=FIRMSIngestionService)
        self.scheduler = FIRMSAutoSyncScheduler(
            ingestion_service=self.mock_ingestion,
            enabled=True,
            interval_seconds=3600,
            sync_days=3
        )
        self.client = TestClient(main_module.app)

    def tearDown(self):
        self.scheduler.stop()

    def test_01_scheduler_configuration(self):
        """Test scheduler reads configuration correctly."""
        self.assertTrue(self.scheduler.enabled)
        self.assertEqual(self.scheduler.interval_seconds, 3600)
        self.assertEqual(self.scheduler.sync_days, 3)

        status = self.scheduler.get_status()
        self.assertEqual(status["status"], "success")
        self.assertTrue(status["enabled"])
        self.assertEqual(status["interval_seconds"], 3600)
        self.assertEqual(status["sync_days"], 3)
        self.assertFalse(status["is_syncing"])
        self.assertIsNone(status["last_sync_status"])

    def test_02_disabled_scheduler(self):
        """Test that disabled scheduler does not start thread."""
        disabled_sched = FIRMSAutoSyncScheduler(
            ingestion_service=self.mock_ingestion,
            enabled=False,
            interval_seconds=1800
        )
        self.assertFalse(disabled_sched.enabled)
        disabled_sched.start()
        self.assertIsNone(disabled_sched._thread)
        status = disabled_sched.get_status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["next_sync_at"])
        disabled_sched.stop()

    def test_03_successful_sync_execution(self):
        """Test successful sync updates metrics and status."""
        self.mock_ingestion.sync_recent_firms.return_value = {
            "status": "success",
            "downloaded": 100,
            "normalized": 100,
            "inserted": 45,
            "duplicates": 55,
            "rejected": 0,
            "errors": [],
            "duration_seconds": 1.25
        }

        res = self.scheduler.trigger_sync(is_manual=False, days=3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["inserted"], 45)
        self.assertEqual(res["duplicates"], 55)

        status = self.scheduler.get_status()
        self.assertEqual(status["last_sync_status"], "success")
        self.assertEqual(status["last_sync_inserted"], 45)
        self.assertEqual(status["last_sync_duplicates"], 55)
        self.assertIsNone(status["last_sync_error"])
        self.assertIsNotNone(status["last_sync_started_at"])
        self.assertIsNotNone(status["last_sync_completed_at"])
        self.assertEqual(status["sync_count"], 1)

    def test_04_graceful_sync_failure_handling(self):
        """Test that ingestion errors are captured gracefully without crashing."""
        self.mock_ingestion.sync_recent_firms.return_value = {
            "status": "error",
            "error": "NASA FIRMS API connection timed out."
        }

        res = self.scheduler.trigger_sync(is_manual=False, days=3)
        self.assertEqual(res["status"], "error")

        status = self.scheduler.get_status()
        self.assertEqual(status["last_sync_status"], "failed")
        self.assertIn("timed out", status["last_sync_error"])
        self.assertEqual(status["sync_count"], 1)

    def test_05_concurrency_protection(self):
        """Test mutual exclusion prevents overlapping sync jobs."""
        # Acquire lock to simulate a running sync
        self.scheduler._lock.acquire()

        try:
            res = self.scheduler.trigger_sync(is_manual=True)
            self.assertEqual(res["status"], "busy")
            self.assertIn("already in progress", res["message"])
        finally:
            self.scheduler._lock.release()

    def test_06_sync_status_endpoint(self):
        """Test GET /api/v1/hotspots/sync/status endpoint response schema."""
        resp = self.client.get("/api/v1/hotspots/sync/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("enabled", data)
        self.assertIn("interval_seconds", data)
        self.assertIn("is_syncing", data)
        self.assertIn("last_sync_inserted", data)
        self.assertIn("last_sync_duplicates", data)
        # Ensure MAP_KEY is not leaked
        self.assertNotIn("map_key", str(data).lower())
        self.assertNotIn("secret", str(data).lower())

    def test_07_manual_sync_endpoint_busy_handling(self):
        """Test POST /api/v1/hotspots/sync returns 409 when busy."""
        with patch.object(main_module.firms_sync_scheduler, "trigger_sync") as mock_trigger:
            mock_trigger.return_value = {
                "status": "busy",
                "message": "A FIRMS synchronization job is already in progress."
            }
            resp = self.client.post("/api/v1/hotspots/sync", json={"days": 3})
            self.assertEqual(resp.status_code, 409)
            self.assertIn("already in progress", resp.json()["detail"])

    def test_08_existing_hotspots_query_endpoint(self):
        """Test that existing GET /api/v1/hotspots remains unaffected and functional."""
        resp = self.client.get("/api/v1/hotspots?start_date=2026-09-20&end_date=2026-09-21&limit=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("total", data)
        self.assertIn("hotspots", data)
        self.assertEqual(data["start_date"], "2026-09-20")
        self.assertEqual(data["end_date"], "2026-09-21")


if __name__ == "__main__":
    unittest.main()
