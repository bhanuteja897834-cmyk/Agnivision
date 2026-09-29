"""
AGNIVISION-GIS: Unit and Integration Tests for NASA FIRMS Temporal Hotspot Pipeline
Tests date validation, single/multi-day queries, boundary enforcement, deduplication,
multi-satellite ingestion, date-range chunking, MAP_KEY security, and API endpoints.
"""

import os
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.firms.models import FIRMSDatabase
from data.firms.normalizer import normalize_firms_record, calculate_raw_hash, normalize_acq_time
from data.firms.client import FIRMSClient, generate_date_chunks, sanitize_message, DEFAULT_INDIA_BBOX
from data.firms.ingestion import FIRMSIngestionService
from main import app


class TestFIRMSTemporalPipeline(unittest.TestCase):
    """Test suite for NASA FIRMS temporal ingestion and query foundation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.test_dir, "test_temporal.db")
        self.db = FIRMSDatabase(db_path=self.test_db_path)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # A. Date Range Chunking (> 5 days)
    # -------------------------------------------------------------------------
    def test_chunking_greater_than_five_days(self):
        """Verify requests >5 days are automatically divided into <=5 day valid FIRMS API requests."""
        chunks = generate_date_chunks("2026-09-01", "2026-09-17", max_chunk_days=5)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0], {"start_date": "2026-09-01", "end_date": "2026-09-05", "day_range": 5})
        self.assertEqual(chunks[1], {"start_date": "2026-09-06", "end_date": "2026-09-10", "day_range": 5})
        self.assertEqual(chunks[2], {"start_date": "2026-09-11", "end_date": "2026-09-15", "day_range": 5})
        self.assertEqual(chunks[3], {"start_date": "2026-09-16", "end_date": "2026-09-17", "day_range": 2})

        for c in chunks:
            self.assertTrue(1 <= c["day_range"] <= 5)

    def test_chunking_single_day(self):
        """Verify 1-day request produces exactly 1 chunk of day_range=1."""
        chunks = generate_date_chunks("2026-09-20", "2026-09-20", max_chunk_days=5)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], {"start_date": "2026-09-20", "end_date": "2026-09-20", "day_range": 1})

    def test_chunking_invalid_date_order(self):
        """Verify start_date > end_date raises ValueError."""
        with self.assertRaises(ValueError):
            generate_date_chunks("2026-09-25", "2026-09-20")

    # -------------------------------------------------------------------------
    # B. MAP_KEY Security & Sanitization
    # -------------------------------------------------------------------------
    def test_api_key_missing_raises_clear_error(self):
        """Verify missing MAP_KEY raises a clear configuration error without network calls."""
        client_no_key = FIRMSClient(map_key="")
        with patch.dict(os.environ, {"NASA_FIRMS_MAP_KEY": "", "FIRMS_MAP_KEY": ""}):
            client_no_key.map_key = ""
            with self.assertRaises(ValueError) as ctx:
                client_no_key.get_validated_map_key()
            self.assertIn("FIRMS_MAP_KEY is missing", str(ctx.exception))

    def test_api_key_sanitization_in_logs(self):
        """Verify MAP_KEY is never exposed in output strings or error logs."""
        dummy_key = "abc123secretkeyxyz789"
        msg = f"Requesting https://firms.modaps.eosdis.nasa.gov/api/area/csv/{dummy_key}/VIIRS/67,7,98,38/1"
        sanitized = sanitize_message(msg, secret=dummy_key)
        self.assertNotIn(dummy_key, sanitized)
        self.assertIn("[REDACTED_MAP_KEY]", sanitized)

    # -------------------------------------------------------------------------
    # C. Data Quality Validation & Normalization
    # -------------------------------------------------------------------------
    def test_normalizer_valid_record(self):
        """Verify canonical standardization of valid FIRMS record."""
        raw = {
            "latitude": "23.51234",
            "longitude": "85.67890",
            "bright_ti4": "335.8",
            "scan": "0.48",
            "track": "0.65",
            "acq_date": "2026-09-20",
            "acq_time": "715",  # Padded to 0715
            "satellite": "N20",
            "instrument": "VIIRS",
            "confidence": "n",
            "version": "2.0NRT",
            "bright_ti5": "285.4",
            "frp": "8.5",
            "daynight": "D"
        }
        rec, err = normalize_firms_record(raw, source="VIIRS_NOAA20_NRT")
        self.assertIsNone(err)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["acq_time"], "0715")
        self.assertEqual(rec["acquisition_datetime"], "2026-09-20T07:15:00Z")
        self.assertEqual(rec["satellite"], "NOAA-20")
        self.assertEqual(rec["latitude"], 23.51234)
        self.assertEqual(rec["longitude"], 85.67890)
        self.assertEqual(rec["bright_ti4"], 335.8)
        self.assertEqual(rec["frp"], 8.5)
        self.assertIsNotNone(rec["raw_hash"])

    def test_normalizer_rejections(self):
        """Verify invalid records are rejected safely with informative reason codes."""
        # 1. Invalid coordinates
        rec, err = normalize_firms_record({"latitude": "invalid", "longitude": "85.0", "acq_date": "2026-09-20", "acq_time": "0700"}, "SRC")
        self.assertEqual(err, "invalid_coordinates")

        # 2. Out of range coordinates
        rec, err = normalize_firms_record({"latitude": "95.0", "longitude": "85.0", "acq_date": "2026-09-20", "acq_time": "0700"}, "SRC")
        self.assertEqual(err, "out_of_range_coordinates")

        # 3. Invalid date
        rec, err = normalize_firms_record({"latitude": "23.0", "longitude": "85.0", "acq_date": "not-a-date", "acq_time": "0700"}, "SRC")
        self.assertEqual(err, "invalid_acq_date_format")

        # 4. Invalid time
        rec, err = normalize_firms_record({"latitude": "23.0", "longitude": "85.0", "acq_date": "2026-09-20", "acq_time": "9999"}, "SRC")
        self.assertEqual(err, "invalid_acq_time")

        # 5. Negative FRP
        rec, err = normalize_firms_record({"latitude": "23.0", "longitude": "85.0", "acq_date": "2026-09-20", "acq_time": "0700", "frp": "-5.0"}, "SRC")
        self.assertEqual(err, "negative_frp")

    # -------------------------------------------------------------------------
    # D. Deduplication & Persistence
    # -------------------------------------------------------------------------
    def test_deduplication_exact_record(self):
        """Verify ingesting the exact same FIRMS record twice produces exactly one database row."""
        raw = {
            "latitude": "22.50000",
            "longitude": "84.50000",
            "bright_ti4": "340.0",
            "bright_ti5": "290.0",
            "scan": "0.5",
            "track": "0.6",
            "acq_date": "2026-09-20",
            "acq_time": "0730",
            "satellite": "N20",
            "instrument": "VIIRS",
            "confidence": "n",
            "frp": "10.0",
            "daynight": "D"
        }
        rec, _ = normalize_firms_record(raw, source="VIIRS_NOAA20_NRT")

        inserted1, dupes1 = self.db.insert_hotspots([rec])
        self.assertEqual(inserted1, 1)
        self.assertEqual(dupes1, 0)

        # Ingest exact same record again
        inserted2, dupes2 = self.db.insert_hotspots([rec])
        self.assertEqual(inserted2, 0)
        self.assertEqual(dupes2, 1)

        # Total in db remains 1
        total, _ = self.db.query_hotspots("2026-09-20", "2026-09-20")
        self.assertEqual(total, 1)

    # -------------------------------------------------------------------------
    # E. Multi-Satellite Ingestion (NOAA-20 + NOAA-21)
    # -------------------------------------------------------------------------
    def test_multi_satellite_support(self):
        """Verify NOAA-20 and NOAA-21 records are both persisted and filterable."""
        rec_n20, _ = normalize_firms_record({
            "latitude": "20.1", "longitude": "80.1", "bright_ti4": "330", "scan": "0.5", "track": "0.5",
            "acq_date": "2026-09-20", "acq_time": "0600", "satellite": "N20", "instrument": "VIIRS", "daynight": "D"
        }, source="VIIRS_NOAA20_NRT")

        rec_n21, _ = normalize_firms_record({
            "latitude": "20.2", "longitude": "80.2", "bright_ti4": "332", "scan": "0.5", "track": "0.5",
            "acq_date": "2026-09-20", "acq_time": "0630", "satellite": "N21", "instrument": "VIIRS", "daynight": "D"
        }, source="VIIRS_NOAA21_NRT")

        self.db.insert_hotspots([rec_n20, rec_n21])

        # Query all
        tot_all, rows_all = self.db.query_hotspots("2026-09-20", "2026-09-20")
        self.assertEqual(tot_all, 2)

        # Filter by NOAA-20
        tot_20, rows_20 = self.db.query_hotspots("2026-09-20", "2026-09-20", satellite="NOAA-20")
        self.assertEqual(tot_20, 1)
        self.assertEqual(rows_20[0]["satellite"], "NOAA-20")

        # Filter by NOAA-21
        tot_21, rows_21 = self.db.query_hotspots("2026-09-20", "2026-09-20", satellite="NOAA-21")
        self.assertEqual(tot_21, 1)
        self.assertEqual(rows_21[0]["satellite"], "NOAA-21")

    # -------------------------------------------------------------------------
    # F. Temporal Boundary Correctness
    # -------------------------------------------------------------------------
    def test_temporal_boundary_strictness(self):
        """Verify strict inclusive boundary enforcement: [2026-09-20, 2026-09-22] never returns 2026-09-19 or 2026-09-23."""
        dates = ["2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23"]
        records = []
        for i, d in enumerate(dates):
            rec, _ = normalize_firms_record({
                "latitude": f"21.{i}", "longitude": f"81.{i}", "bright_ti4": "330", "scan": "0.5", "track": "0.5",
                "acq_date": d, "acq_time": "0800", "satellite": "N20", "instrument": "VIIRS", "daynight": "D"
            }, source="VIIRS_NOAA20_NRT")
            records.append(rec)

        self.db.insert_hotspots(records)

        # Query range [2026-09-20, 2026-09-22]
        tot, rows = self.db.query_hotspots("2026-09-20", "2026-09-22")
        self.assertEqual(tot, 3)
        queried_dates = {r["acq_date"] for r in rows}
        self.assertEqual(queried_dates, {"2026-09-20", "2026-09-21", "2026-09-22"})
        self.assertNotIn("2026-09-19", queried_dates)
        self.assertNotIn("2026-09-23", queried_dates)

        # Single-day query
        tot_single, rows_single = self.db.query_hotspots("2026-09-20", "2026-09-20")
        self.assertEqual(tot_single, 1)
        self.assertEqual(rows_single[0]["acq_date"], "2026-09-20")

    # -------------------------------------------------------------------------
    # G. API Endpoint: GET /api/v1/hotspots
    # -------------------------------------------------------------------------
    def test_api_hotspots_endpoint_valid(self):
        """Verify GET /api/v1/hotspots returns 200 with inclusive date range observations."""
        resp = self.client.get("/api/v1/hotspots?start_date=2026-09-20&end_date=2026-09-21")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["start_date"], "2026-09-20")
        self.assertEqual(data["end_date"], "2026-09-21")
        self.assertIn("total_matching", data)
        self.assertIn("observations", data)

        # Verify all returned observations fall strictly in date range
        for obs in data["observations"]:
            self.assertTrue("2026-09-20" <= obs["acq_date"] <= "2026-09-21")

    def test_api_hotspots_endpoint_invalid_date_order(self):
        """Verify GET /api/v1/hotspots with start_date > end_date returns 400."""
        resp = self.client.get("/api/v1/hotspots?start_date=2026-09-25&end_date=2026-09-20")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("prior or equal", resp.json()["detail"])

    def test_api_hotspots_endpoint_missing_params(self):
        """Verify GET /api/v1/hotspots without parameters returns 422 or 400."""
        resp = self.client.get("/api/v1/hotspots")
        self.assertIn(resp.status_code, (400, 422))

    def test_api_hotspots_stats_endpoint(self):
        """Verify GET /api/v1/hotspots/stats returns database overview."""
        resp = self.client.get("/api/v1/hotspots/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("total_hotspots", data["stats"])


if __name__ == "__main__":
    unittest.main()
