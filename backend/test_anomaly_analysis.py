"""
Unit tests for AGNIVISION-GIS Event-vs-Historical-Baseline Anomaly Analysis (Step 6).
Covers all required test conditions with mock data and test client.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from anomaly_analysis import (
    calculate_event_metrics,
    get_event_spatial_grid_cell,
    analyze_event_anomaly,
    ANOMALY_THRESHOLDS
)
import main


class TestAnomalyAnalysis(unittest.TestCase):

    def setUp(self):
        # Sample event with multiple observations
        self.sample_event_multi = {
            "event_id": "EVT-TEST-01",
            "first_detected": "2026-09-20 06:00 UTC",
            "last_detected": "2026-09-22 18:00 UTC",
            "persistence_days": 3,
            "centroid": {"latitude": 23.75, "longitude": 86.35},
            "observations": [
                {"bright_ti4": 320.0, "frp": 2.5, "acq_date": "2026-09-20", "acq_time": "0600"},
                {"bright_ti4": 330.0, "frp": 3.5, "acq_date": "2026-09-21", "acq_time": "0630"},
                {"bright_ti4": 340.0, "frp": 4.5, "acq_date": "2026-09-22", "acq_time": "1800"}
            ]
        }

        # Sample event with 1 observation
        self.sample_event_single = {
            "event_id": "EVT-TEST-02",
            "first_detected": "2026-09-20 06:00 UTC",
            "last_detected": "2026-09-20 06:00 UTC",
            "persistence_days": 1,
            "centroid": {"latitude": 23.75, "longitude": 86.35},
            "observations": [
                {"bright_ti4": 315.0, "frp": 1.8, "acq_date": "2026-09-20", "acq_time": "0600"}
            ]
        }

    # 1. Event metrics calculation
    def test_calculate_event_metrics(self):
        metrics = calculate_event_metrics(self.sample_event_multi)
        self.assertEqual(metrics["observation_count"], 3)
        self.assertEqual(metrics["mean_brightness"], 330.0)
        self.assertEqual(metrics["median_brightness"], 330.0)
        self.assertEqual(metrics["max_brightness"], 340.0)
        self.assertEqual(metrics["mean_frp"], 3.5)
        self.assertEqual(metrics["median_frp"], 3.5)
        self.assertEqual(metrics["max_frp"], 4.5)
        self.assertEqual(metrics["observation_days"], 3)
        self.assertEqual(metrics["persistence_days"], 3)

    # 2. Spatial grid lookup
    def test_spatial_grid_lookup(self):
        # 23.75N, 86.35E falls in grid_23.7_86.3
        cell_id, meta = get_event_spatial_grid_cell(23.75, 86.35)
        self.assertEqual(cell_id, "grid_23.7_86.3")
        self.assertEqual(meta["lat_min"], 23.7)
        self.assertEqual(meta["lat_max"], 23.8)
        self.assertEqual(meta["lon_min"], 86.3)
        self.assertEqual(meta["lon_max"], 86.4)

        # Coordinate outside monitoring region (e.g. lat 2.0 is below south bound)
        oob_lat = 2.0
        oob_cell_id, oob_meta = get_event_spatial_grid_cell(oob_lat, 86.35)
        self.assertIsNone(oob_cell_id)
        self.assertIsNone(oob_meta)

    # 3. Current-vs-baseline difference & percentage difference
    def test_differences_and_percent_difference(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        # Cell has 3 observations with mean bright = 300, mean frp = 2.0
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 290.0, "frp": 1.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 300.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 310.0, "frp": 3.0, "latitude": 23.75, "longitude": 86.35}
        ]

        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertFalse(result["is_fallback"])

        comps = result["comparisons"]
        # Current mean = 330.0, base mean = 300.0 -> diff = 30.0 K (+10.0%)
        self.assertEqual(comps["brightness_difference"], 30.0)
        self.assertEqual(comps["brightness_percent_difference"], 10.0)

        # Current mean FRP = 3.5, base mean FRP = 2.0 -> diff = 1.5 MW (+75.0%)
        self.assertEqual(comps["frp_difference"], 1.5)
        self.assertEqual(comps["frp_percent_difference"], 75.0)

    # 4. Zero historical denominator guard
    def test_zero_historical_denominator(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        # If FRP was 0
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 300.0, "frp": 0.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 300.0, "frp": 0.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 300.0, "frp": 0.0, "latitude": 23.75, "longitude": 86.35}
        ]
        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        self.assertIsNone(result["comparisons"]["frp_percent_difference"])

    # 5. Standard deviation & z-score calculation
    def test_z_score_calculation(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        # Baseline: [300, 310, 320] -> mean = 310, std = 10.0
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 300.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 310.0, "frp": 3.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 320.0, "frp": 4.0, "latitude": 23.75, "longitude": 86.35}
        ]
        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        std_dev = result["standardized_deviation"]
        self.assertTrue(std_dev["available"])
        self.assertEqual(std_dev["historical_brightness_std"], 10.0)
        # Current mean = 330.0 -> z = (330 - 310) / 10.0 = +2.0
        self.assertEqual(std_dev["brightness_z_score"], 2.0)

    # 6. Zero standard deviation guard
    def test_zero_standard_deviation(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        # All historical observations have identical values (std = 0)
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 310.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 310.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 310.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35}
        ]
        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        # Should not divide by zero; z-score must be None
        self.assertIsNone(result["standardized_deviation"]["brightness_z_score"])

    # 7. Missing baseline
    def test_missing_baseline(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = False
        mock_mgr.error_message = "Historical baseline not loaded"
        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["interpretation"], "INSUFFICIENT_BASELINE")

    # 8. Missing spatial cell (cell has 0 observations -> regional fallback)
    def test_missing_spatial_cell_fallback(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        mock_mgr.overall_statistics = {
            "observation_count": 5000,
            "brightness_ti4": {"mean": 320.0, "median": 318.0, "max": 360.0},
            "frp": {"mean": 3.5, "median": 2.5, "max": 40.0}
        }
        mock_mgr.get_valid_observations.return_value = [
            {"bright_ti4": 310.0, "frp": 2.5},
            {"bright_ti4": 320.0, "frp": 3.5},
            {"bright_ti4": 330.0, "frp": 4.5}
        ]
        # Cell has 0 observations
        mock_mgr.get_cell_observations.return_value = []

        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["baseline_scope"], "regional_fallback")
        self.assertIn("Regional fallback", result["fallback_label"])

    # 9. Insufficient historical observations (< 3 observations)
    def test_insufficient_historical_observations(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        # Cell has only 1 observation
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 310.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35}
        ]
        result = analyze_event_anomaly(self.sample_event_multi, mock_mgr)
        self.assertEqual(result["interpretation"], "INSUFFICIENT_BASELINE")
        self.assertIsNone(result["standardized_deviation"]["brightness_z_score"])

    # 10. Single observation event
    def test_single_observation_event(self):
        mock_mgr = MagicMock()
        mock_mgr.is_loaded = True
        mock_mgr.quality_summary = {"period_start": "2026-06-01", "period_end": "2026-06-30", "requested_days": 30}
        mock_mgr.get_cell_observations.return_value = [
            {"bright_ti4": 310.0, "frp": 2.0, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 315.0, "frp": 2.5, "latitude": 23.75, "longitude": 86.35},
            {"bright_ti4": 320.0, "frp": 3.0, "latitude": 23.75, "longitude": 86.35}
        ]
        result = analyze_event_anomaly(self.sample_event_single, mock_mgr)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["current_metrics"]["observation_count"], 1)
        self.assertEqual(result["current_metrics"]["mean_brightness"], 315.0)

    # 11. API endpoint GET /events/{event_id}/anomaly
    def test_api_endpoint(self):
        client = TestClient(main.app)
        res = client.get("/events/EVT-000029/anomaly")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["event_id"], "EVT-000029")
        self.assertIn("status", data)
        self.assertIn("interpretation", data)
        self.assertIn("comparisons", data)
        self.assertIn("standardized_deviation", data)
        self.assertIn("limitations", data)


if __name__ == "__main__":
    unittest.main()
