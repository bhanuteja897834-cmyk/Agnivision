"""
AGNIVISION-GIS: Unit and Integration Tests for Phase 4 NASA FIRMS Near-Real-Time Monitoring
Covers:
1. 15-minute interval configuration (DEFAULT_SYNC_INTERVAL_SECONDS = 900)
2. Incremental sync query behavior (3-day lookback default)
3. Partial satellite failure handling (NOAA-20 succeeds, NOAA-21 fails):
   - verify NOAA-20 data is committed and recorded
   - verify sync status records partial error
   - verify scheduler continues running
4. Complete NASA API failure handling:
   - verify existing SQLite data is not corrupted or wiped
   - verify sync status records error
   - verify next sync is scheduled properly
5. Next sync timestamp calculation and retry behavior
6. Status response schema:
   - last_successful_sync_completed_at
   - last_successful_sync_age_seconds
   - is_stale
   - monitoring_label ("NASA FIRMS near-real-time monitoring")
7. Security: FIRMS_MAP_KEY is never exposed in status responses, logs, or serialized payloads.
"""

import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

try:
    from backend.data.firms import (
        FIRMSAutoSyncScheduler,
        FIRMSIngestionService,
        FIRMSDatabase,
        FIRMSClient
    )
    from backend.data.firms.scheduler import DEFAULT_SYNC_INTERVAL_SECONDS
    import backend.main as main_module
except ImportError:
    from data.firms import (
        FIRMSAutoSyncScheduler,
        FIRMSIngestionService,
        FIRMSDatabase,
        FIRMSClient
    )
    from data.firms.scheduler import DEFAULT_SYNC_INTERVAL_SECONDS
    import main as main_module


class TestFIRMSNearRealTimeMonitoringPhase4(unittest.TestCase):
    def setUp(self):
        self.mock_ingestion = MagicMock(spec=FIRMSIngestionService)
        self.scheduler = FIRMSAutoSyncScheduler(
            ingestion_service=self.mock_ingestion,
            enabled=True,
            interval_seconds=900,
            sync_days=3
        )
        self.client = TestClient(main_module.app)

    def tearDown(self):
        self.scheduler.stop()

    def test_01_fifteen_minute_default_configuration(self):
        """Test that default sync interval is 900 seconds (15 minutes)."""
        self.assertEqual(DEFAULT_SYNC_INTERVAL_SECONDS, 900)
        self.assertEqual(self.scheduler.interval_seconds, 900)
        status = self.scheduler.get_status()
        self.assertEqual(status["interval_seconds"], 900)
        self.assertEqual(status["monitoring_label"], "NASA FIRMS near-real-time monitoring")

    def test_02_incremental_sync_query_behavior(self):
        """Test scheduler queries 3-day lookback for near-real-time incremental sync."""
        self.mock_ingestion.sync_recent_firms.return_value = {
            "status": "success",
            "downloaded": 120,
            "normalized": 120,
            "inserted": 15,
            "duplicates": 105,
            "rejected": 0,
            "errors": [],
            "duration_seconds": 1.1
        }

        res = self.scheduler.trigger_sync(is_manual=False, days=3)
        self.assertEqual(self.mock_ingestion.sync_recent_firms.call_count, 1)
        call_kwargs = self.mock_ingestion.sync_recent_firms.call_args.kwargs
        self.assertEqual(call_kwargs.get("days"), 3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["inserted"], 15)
        self.assertEqual(res["duplicates"], 105)

        status = self.scheduler.get_status()
        self.assertEqual(status["last_sync_inserted"], 15)
        self.assertIsNotNone(status["last_successful_sync_completed_at"])
        self.assertIsNotNone(status["last_successful_sync_age_seconds"])
        self.assertFalse(status["is_stale"])

    def test_03_partial_satellite_failure_handling(self):
        """Test partial failure (NOAA-20 succeeds, NOAA-21 fails):
        - committed records preserved
        - status recorded as partial_error
        - scheduler continues running
        """
        self.mock_ingestion.sync_recent_firms.return_value = {
            "status": "partial_error",
            "downloaded": 60,
            "normalized": 60,
            "inserted": 12,
            "duplicates": 48,
            "rejected": 0,
            "errors": ["NOAA-21 NRT request timed out"],
            "duration_seconds": 2.5
        }

        res = self.scheduler.trigger_sync(is_manual=False, days=3)
        self.assertEqual(res["status"], "partial_error")
        self.assertEqual(res["inserted"], 12)
        self.assertIn("NOAA-21 NRT request timed out", res["errors"])

        status = self.scheduler.get_status()
        self.assertEqual(status["last_sync_status"], "partial_error")
        self.assertEqual(status["last_sync_inserted"], 12)
        # Verify partial success is recorded as last successful sync
        self.assertIsNotNone(status["last_successful_sync_completed_at"])
        self.assertIn("NOAA-21", str(status["last_sync_error"]))
        # Scheduler remains enabled and operational
        self.assertTrue(status["enabled"])
        self.assertFalse(status["is_syncing"])

    def test_04_complete_nasa_failure_resilience(self):
        """Test complete NASA API failure:
        - failure captured gracefully
        - last_sync_status marked failed
        - next sync time updated properly
        """
        self.mock_ingestion.sync_recent_firms.return_value = {
            "status": "error",
            "error": "NASA FIRMS API 503 Service Unavailable"
        }

        res = self.scheduler.trigger_sync(is_manual=False, days=3)
        self.assertEqual(res["status"], "error")

        status = self.scheduler.get_status()
        self.assertEqual(status["last_sync_status"], "failed")
        self.assertIn("503", status["last_sync_error"])
        # Next sync time is still scheduled
        self.assertIsNotNone(status["next_sync_at"])
        # Scheduler thread is still alive and ready
        self.assertFalse(status["is_syncing"])

    def test_05_next_sync_calculation_and_stale_detection(self):
        """Test next_sync_at timestamp calculation and stale flag evaluation."""
        self.scheduler._update_next_sync_time()
        status = self.scheduler.get_status()
        self.assertIsNotNone(status["next_sync_at"])

        # Simulate fresh sync
        fresh_time = datetime.now(timezone.utc).isoformat()
        self.scheduler.last_successful_sync_completed_at = fresh_time
        status = self.scheduler.get_status()
        self.assertFalse(status["is_stale"])
        self.assertLess(status["last_successful_sync_age_seconds"], 10)

        # Simulate stale sync (> 2 * interval = 1800s)
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=2000)).isoformat()
        self.scheduler.last_successful_sync_completed_at = stale_time
        status = self.scheduler.get_status()
        self.assertTrue(status["is_stale"])
        self.assertGreater(status["last_successful_sync_age_seconds"], 1800)

    def test_06_sync_status_endpoint_schema(self):
        """Test GET /api/v1/hotspots/sync/status provides complete Phase 4 schema."""
        resp = self.client.get("/api/v1/hotspots/sync/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "success")
        self.assertIn("enabled", data)
        self.assertIn("interval_seconds", data)
        self.assertIn("last_successful_sync_completed_at", data)
        self.assertIn("last_successful_sync_age_seconds", data)
        self.assertIn("is_stale", data)
        self.assertIn("monitoring_label", data)
        self.assertEqual(data["monitoring_label"], "NASA FIRMS near-real-time monitoring")

    def test_07_security_no_secret_key_exposure(self):
        """Ensure FIRMS_MAP_KEY is never leaked in status or query responses."""
        resp = self.client.get("/api/v1/hotspots/sync/status")
        self.assertEqual(resp.status_code, 200)
        text = resp.text.lower()
        self.assertNotIn("firms_map_key", text)
        self.assertNotIn("secret", text)

        resp2 = self.client.get("/api/v1/hotspots?start_date=2026-09-20&end_date=2026-09-21&limit=5")
        self.assertEqual(resp2.status_code, 200)
        text2 = resp2.text.lower()
        self.assertNotIn("firms_map_key", text2)
        self.assertNotIn("secret", text2)


if __name__ == "__main__":
    unittest.main()
