"""
Unit tests for AGNIVISION-GIS Historical Baseline Foundation (Step 5).
Covers test cases A through S using isolated mock / test data only.
"""

import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import historical_baseline
from historical_baseline import (
    query_sp_availability,
    select_baseline_period,
    generate_request_batches,
    validate_and_normalize_record,
    compute_daily_baseline,
    compute_overall_baseline,
    compute_spatial_grid_baseline,
    HistoricalBaselineManager,
    MONITORING_REGION,
    TARGET_BASELINE_DAYS
)
import main


class TestHistoricalBaseline(unittest.TestCase):

    # A. Data availability response parsing
    @patch("requests.get")
    def test_a_data_availability_parsing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "data_id,min_date,max_date\nVIIRS_NOAA20_SP,2018-04-01,2026-06-30\n"
        mock_get.return_value = mock_resp

        result = query_sp_availability("test_key")
        self.assertEqual(result["data_id"], "VIIRS_NOAA20_SP")
        self.assertEqual(result["min_date"], "2018-04-01")
        self.assertEqual(result["max_date"], "2026-06-30")

    # B. Historical date selection
    def test_b_historical_date_selection(self):
        start, end = select_baseline_period("2018-04-01", "2026-06-30", target_days=30)
        self.assertEqual(end, datetime.date(2026, 6, 30))
        self.assertEqual(start, datetime.date(2026, 6, 1))
        self.assertEqual((end - start).days + 1, 30)

    # C. 5-day request batching
    def test_c_request_batching(self):
        start = datetime.date(2026, 6, 1)
        end = datetime.date(2026, 6, 30)
        batches = generate_request_batches(start, end, max_batch_days=5)

        self.assertEqual(len(batches), 6)
        self.assertEqual(batches[0]["start_date"], "2026-06-01")
        self.assertEqual(batches[0]["day_range"], 5)
        self.assertEqual(batches[0]["end_date"], "2026-06-05")
        self.assertEqual(batches[-1]["start_date"], "2026-06-26")
        self.assertEqual(batches[-1]["day_range"], 5)
        self.assertEqual(batches[-1]["end_date"], "2026-06-30")

    # D. Cache reuse
    def test_d_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = HistoricalBaselineManager(cache_dir=tmpdir)
            start_str, end_str = "2026-06-01", "2026-06-30"
            raw_path, json_path = mgr.get_cache_file_paths(start_str, end_str)

            # Pre-write dummy cached summary
            dummy_cache = {
                "quality_summary": {
                    "dataset": "VIIRS_NOAA20_SP",
                    "period_start": start_str,
                    "period_end": end_str,
                    "valid_days": 30,
                    "valid_observation_count": 42
                },
                "overall_statistics": {"observation_count": 42},
                "daily_statistics": [],
                "spatial_grid": {"cells": []},
                "last_retrieved_iso": "2026-09-25T12:00:00Z"
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(dummy_cache, f)

            with patch.object(historical_baseline, "query_sp_availability", return_value={"min_date": "2018-04-01", "max_date": "2026-06-30"}):
                mgr.load_or_fetch("dummy_key")

            self.assertTrue(mgr.is_loaded)
            self.assertEqual(mgr.quality_summary["valid_observation_count"], 42)

    # E. Coordinate validation
    def test_e_coordinate_validation(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 30)

        # Valid coordinate in 82–90E, 20–27N
        valid_row = {
            "latitude": "23.5",
            "longitude": "85.5",
            "bright_ti4": "330.5",
            "acq_date": "2026-06-15"
        }
        rec, err = validate_and_normalize_record(valid_row, p_start, p_end)
        self.assertIsNotNone(rec)
        self.assertIsNone(err)

        # Coordinate out of bounds (below south bound)
        oob_row = {
            "latitude": str(MONITORING_REGION["south"] - 5.0),
            "longitude": "85.5",
            "bright_ti4": "330.5",
            "acq_date": "2026-06-15"
        }
        rec2, err2 = validate_and_normalize_record(oob_row, p_start, p_end)
        self.assertIsNone(rec2)
        self.assertEqual(err2, "out_of_bounds")

        # Invalid coordinate (non-numeric)
        inv_row = {
            "latitude": "bad_lat",
            "longitude": "85.5",
            "bright_ti4": "330.5",
            "acq_date": "2026-06-15"
        }
        rec3, err3 = validate_and_normalize_record(inv_row, p_start, p_end)
        self.assertIsNone(rec3)
        self.assertEqual(err3, "invalid_coordinates")

    # F. Date validation
    def test_f_date_validation(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 30)

        # Date outside period
        out_row = {
            "latitude": "23.5",
            "longitude": "85.5",
            "bright_ti4": "330.5",
            "acq_date": "2026-07-05"
        }
        rec, err = validate_and_normalize_record(out_row, p_start, p_end)
        self.assertIsNone(rec)
        self.assertEqual(err, "invalid_date_time")

    # G. Duplicate handling
    def test_g_duplicate_handling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = HistoricalBaselineManager(cache_dir=tmpdir)
            p_start = datetime.date(2026, 6, 1)
            p_end = datetime.date(2026, 6, 5)

            raw_rows = [
                {"latitude": "23.5", "longitude": "85.5", "bright_ti4": "330.0", "acq_date": "2026-06-01", "acq_time": "0600", "satellite": "N20"},
                {"latitude": "23.5", "longitude": "85.5", "bright_ti4": "330.0", "acq_date": "2026-06-01", "acq_time": "0600", "satellite": "N20"}
            ]

            valid = []
            seen = set()
            duplicates = 0
            for r in raw_rows:
                rec, err = validate_and_normalize_record(r, p_start, p_end)
                if not err:
                    key = (rec["latitude"], rec["longitude"], rec["acq_date"], rec["acq_time"], rec["satellite"])
                    if key in seen:
                        duplicates += 1
                    else:
                        seen.add(key)
                        valid.append(rec)

            self.assertEqual(len(valid), 1)
            self.assertEqual(duplicates, 1)

    # H. Missing FRP
    def test_h_missing_frp(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 30)
        row = {
            "latitude": "23.5",
            "longitude": "85.5",
            "bright_ti4": "330.5",
            "frp": "",
            "acq_date": "2026-06-15"
        }
        rec, err = validate_and_normalize_record(row, p_start, p_end)
        self.assertIsNotNone(rec)
        self.assertIsNone(rec["frp"])

    # I. Missing brightness
    def test_i_missing_brightness(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 30)
        row = {
            "latitude": "23.5",
            "longitude": "85.5",
            "bright_ti4": "",
            "acq_date": "2026-06-15"
        }
        rec, err = validate_and_normalize_record(row, p_start, p_end)
        self.assertIsNone(rec)
        self.assertEqual(err, "invalid_brightness")

    # J. Zero-observation day
    def test_j_zero_observation_day(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 2)
        # Observations only on June 1
        obs = [
            {"latitude": 23.5, "longitude": 85.5, "bright_ti4": 330.0, "frp": 2.5, "acq_date": "2026-06-01"}
        ]
        status_map = {"2026-06-01": True, "2026-06-02": True}
        daily = compute_daily_baseline(p_start, p_end, obs, status_map)

        self.assertEqual(len(daily), 2)
        self.assertEqual(daily[0]["date"], "2026-06-01")
        self.assertEqual(daily[0]["status"], "valid_with_observations")
        self.assertEqual(daily[0]["observation_count"], 1)

        self.assertEqual(daily[1]["date"], "2026-06-02")
        self.assertEqual(daily[1]["status"], "zero_observations")
        self.assertEqual(daily[1]["observation_count"], 0)
        self.assertIsNone(daily[1]["brightness_ti4"])
        self.assertIsNone(daily[1]["frp"])

    # K. Unavailable-data day
    def test_k_unavailable_data_day(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 2)
        obs = []
        status_map = {"2026-06-01": True, "2026-06-02": False}
        daily = compute_daily_baseline(p_start, p_end, obs, status_map)

        self.assertEqual(daily[1]["status"], "unavailable")
        self.assertIsNone(daily[1]["observation_count"])
        self.assertIsNone(daily[1]["brightness_ti4"])

    # L. Daily aggregation
    def test_l_daily_aggregation(self):
        p_start = datetime.date(2026, 6, 1)
        p_end = datetime.date(2026, 6, 1)
        obs = [
            {"latitude": 23.5, "longitude": 85.5, "bright_ti4": 300.0, "frp": 2.0, "acq_date": "2026-06-01"},
            {"latitude": 23.6, "longitude": 85.6, "bright_ti4": 340.0, "frp": 4.0, "acq_date": "2026-06-01"}
        ]
        daily = compute_daily_baseline(p_start, p_end, obs, {"2026-06-01": True})
        d0 = daily[0]
        self.assertEqual(d0["observation_count"], 2)
        self.assertEqual(d0["brightness_ti4"]["mean"], 320.0)
        self.assertEqual(d0["brightness_ti4"]["max"], 340.0)
        self.assertEqual(d0["frp"]["mean"], 3.0)
        self.assertEqual(d0["frp"]["max"], 4.0)

    # M. Overall aggregation
    def test_m_overall_aggregation(self):
        daily = [
            {"status": "valid_with_observations"},
            {"status": "zero_observations"},
            {"status": "unavailable"}
        ]
        obs = [
            {"latitude": 23.5, "longitude": 85.5, "bright_ti4": 320.0, "frp": 2.0},
            {"latitude": 23.6, "longitude": 85.6, "bright_ti4": 340.0, "frp": 4.0}
        ]
        summary = {}
        overall = compute_overall_baseline(daily, obs, summary)

        self.assertEqual(overall["observation_count"], 2)
        self.assertEqual(overall["brightness_ti4"]["mean"], 330.0)
        self.assertEqual(overall["frp"]["mean"], 3.0)
        self.assertEqual(summary["valid_days"], 2)
        self.assertEqual(summary["days_with_observations"], 1)
        self.assertEqual(summary["zero_observation_days"], 1)
        self.assertEqual(summary["unavailable_days"], 1)

    # N. Spatial grid aggregation
    def test_n_spatial_grid_aggregation(self):
        obs = [
            {"latitude": 20.72, "longitude": 85.34, "bright_ti4": 330.0, "frp": 2.0},
            {"latitude": 20.78, "longitude": 85.39, "bright_ti4": 340.0, "frp": 4.0}
        ]
        grid = compute_spatial_grid_baseline(obs, grid_res=0.1)
        self.assertEqual(grid["total_populated_cells"], 1)
        cell = grid["cells"][0]
        self.assertEqual(cell["observation_count"], 2)
        self.assertEqual(cell["mean_bright_ti4"], 335.0)
        self.assertEqual(cell["mean_frp"], 3.0)

    # O. No overlap with current NRT window
    def test_o_no_overlap_with_nrt_window(self):
        nrt_start = "2026-09-16"
        start, end = select_baseline_period("2018-04-01", "2026-09-20", target_days=30, nrt_start_date_str=nrt_start)
        self.assertLess(end, datetime.date(2026, 9, 16))
        self.assertEqual(end, datetime.date(2026, 9, 15))

    # P, Q, R, S: API endpoint tests via FastAPI TestClient
    def test_p_q_r_s_api_endpoints(self):
        client = TestClient(main.app)

        # 1. Summary endpoint
        res_sum = client.get("/historical-baseline/summary")
        self.assertEqual(res_sum.status_code, 200)
        data_sum = res_sum.json()
        self.assertIn("dataset", data_sum)

        # 2. Daily endpoint
        res_day = client.get("/historical-baseline/daily")
        self.assertEqual(res_day.status_code, 200)
        data_day = res_day.json()
        self.assertIn("dataset", data_day)

        # 3. Grid endpoint
        res_grid = client.get("/historical-baseline/grid")
        self.assertEqual(res_grid.status_code, 200)
        data_grid = res_grid.json()
        self.assertIn("cells", data_grid)

        # 4. Status endpoint
        res_stat = client.get("/historical-baseline/status")
        self.assertEqual(res_stat.status_code, 200)
        data_stat = res_stat.json()
        self.assertIn("status", data_stat)


if __name__ == "__main__":
    unittest.main()
