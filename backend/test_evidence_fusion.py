"""
backend/test_evidence_fusion.py

Unit tests for AGNIVISION-GIS Step 7: Evidence Fusion / Source Assessment.
Verifies all 7 evidence dimensions, strength categorization rules,
contradiction detection, data quality checks, edge cases, and API endpoint.
"""

import unittest
from fastapi.testclient import TestClient

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from evidence_fusion import (
    assess_thermal_evidence,
    assess_temporal_evidence,
    assess_historical_evidence,
    assess_geographic_evidence,
    assess_spatial_evidence,
    assess_facility_context,
    assess_data_quality,
    detect_contradictions,
    fuse_event_evidence,
    EVIDENCE_THRESHOLDS,
)
from main import app


class TestEvidenceFusion(unittest.TestCase):

    def setUp(self):
        # Sample realistic event fixture (multi-observation)
        self.sample_event_strong = {
            "event_id": "EVT-TEST-STRONG",
            "observation_count": 12,
            "first_detected": "2026-09-16T20:57:00Z",
            "last_detected": "2026-09-21T19:25:00Z",
            "persistence_days": 5.0,
            "centroid": {"latitude": 23.76127, "longitude": 86.39550},
            "spatial_summary": {
                "centroid": {"latitude": 23.76127, "longitude": 86.39550},
                "min_latitude": 23.74,
                "max_latitude": 23.78,
                "min_longitude": 86.37,
                "max_longitude": 86.42,
            },
            "temporal_summary": {
                "first_detected": "2026-09-16T20:57:00Z",
                "last_detected": "2026-09-21T19:25:00Z",
                "duration_hours": 118.5,
                "distinct_days": 5,
            },
            "geographic_validation": {
                "domain": "LAND",
                "state": "Jharkhand",
                "district": "Dhanbad",
                "city": "Dhanbad",
            },
            "observations": [
                {"latitude": 23.76, "longitude": 86.39, "bright_ti4": 330.5, "frp": 3.5, "acq_date": "2026-09-16"},
                {"latitude": 23.77, "longitude": 86.40, "bright_ti4": 328.0, "frp": 2.8, "acq_date": "2026-09-17"},
                {"latitude": 23.75, "longitude": 86.38, "bright_ti4": 335.2, "frp": 5.1, "acq_date": "2026-09-18"},
                {"latitude": 23.76, "longitude": 86.41, "bright_ti4": 320.0, "frp": 2.1, "acq_date": "2026-09-19"},
                {"latitude": 23.76, "longitude": 86.39, "bright_ti4": 325.0, "frp": 4.0, "acq_date": "2026-09-20"},
                {"latitude": 23.77, "longitude": 86.40, "bright_ti4": 322.0, "frp": 2.2, "acq_date": "2026-09-21"},
                {"latitude": 23.75, "longitude": 86.39, "bright_ti4": 319.0, "frp": 1.9, "acq_date": "2026-09-21"},
                {"latitude": 23.76, "longitude": 86.38, "bright_ti4": 321.0, "frp": 2.5, "acq_date": "2026-09-21"},
                {"latitude": 23.77, "longitude": 86.41, "bright_ti4": 330.0, "frp": 3.8, "acq_date": "2026-09-21"},
                {"latitude": 23.76, "longitude": 86.40, "bright_ti4": 327.0, "frp": 3.2, "acq_date": "2026-09-21"},
                {"latitude": 23.75, "longitude": 86.39, "bright_ti4": 326.0, "frp": 2.9, "acq_date": "2026-09-21"},
                {"latitude": 23.76, "longitude": 86.39, "bright_ti4": 329.0, "frp": 3.6, "acq_date": "2026-09-21"},
            ],
        }

        # Single observation event fixture
        self.sample_event_single = {
            "event_id": "EVT-TEST-SINGLE",
            "observation_count": 1,
            "first_detected": "2026-09-18T07:15:00Z",
            "last_detected": "2026-09-18T07:15:00Z",
            "persistence_days": 1.0,
            "centroid": {"latitude": 22.5000, "longitude": 84.5000},
            "spatial_summary": {
                "centroid": {"latitude": 22.5000, "longitude": 84.5000},
                "min_latitude": 22.50,
                "max_latitude": 22.50,
                "min_longitude": 84.50,
                "max_longitude": 84.50,
            },
            "temporal_summary": {
                "first_detected": "2026-09-18T07:15:00Z",
                "last_detected": "2026-09-18T07:15:00Z",
                "duration_hours": 0.0,
                "distinct_days": 1,
            },
            "geographic_validation": {
                "domain": "LAND",
                "state": "Odisha",
                "district": "Sundargarh",
                "city": "Rourkela",
            },
            "observations": [
                {"latitude": 22.50, "longitude": 84.50, "bright_ti4": 310.2, "frp": 1.2, "acq_date": "2026-09-18"}
            ],
        }

    # 1. Thermal Evidence Tests
    def test_thermal_evidence_strong(self):
        result = assess_thermal_evidence(self.sample_event_strong)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "STRONG")
        self.assertEqual(result["observation_count"], 12)
        self.assertTrue(result["has_frp"])
        self.assertAlmostEqual(result["brightness"]["mean"], 326.06, places=1)
        self.assertAlmostEqual(result["frp"]["mean"], 3.14, places=1)

    def test_thermal_evidence_limited(self):
        result = assess_thermal_evidence(self.sample_event_single)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "LIMITED")
        self.assertEqual(result["observation_count"], 1)

    def test_thermal_evidence_missing_frp(self):
        ev = {
            "observation_count": 3,
            "observations": [
                {"bright_ti4": 312.0, "frp": None},
                {"bright_ti4": 314.0, "frp": ""},
                {"bright_ti4": 315.0},
            ]
        }
        result = assess_thermal_evidence(ev)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertFalse(result["has_frp"])
        self.assertIsNone(result["frp"]["mean"])

    # 2. Temporal Evidence Tests
    def test_temporal_evidence_strong(self):
        result = assess_temporal_evidence(self.sample_event_strong)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "STRONG")
        self.assertEqual(result["distinct_observation_days"], 5)
        self.assertEqual(result["persistence_days"], 5.0)

    def test_temporal_evidence_limited(self):
        result = assess_temporal_evidence(self.sample_event_single)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "LIMITED")
        self.assertEqual(result["distinct_observation_days"], 1)

    # 3. Historical Baseline Evidence Tests
    def test_historical_evidence_within_baseline(self):
        anomaly_res = {
            "status": "AVAILABLE",
            "interpretation": "WITHIN_BASELINE",
            "interpretation_summary": "Thermal measurements are within historical baseline variance.",
            "baseline_source": "VIIRS_NOAA20_SP",
            "baseline_scope": "0.1_degree_spatial_grid",
            "is_fallback": False,
            "grid_cell": {"cell_id": "grid_23.7_86.3", "observation_count": 172},
            "comparisons": {"brightness_percent_difference": -0.6, "frp_percent_difference": -31.05},
            "standardized_deviation": {"brightness_z_score": -0.16, "frp_z_score": -0.55}
        }
        result = assess_historical_evidence(anomaly_res)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["anomaly_status"], "WITHIN_BASELINE")
        self.assertFalse(result["is_fallback"])
        self.assertEqual(result["grid_cell"], "grid_23.7_86.3")

    def test_historical_evidence_fallback(self):
        anomaly_res = {
            "status": "AVAILABLE",
            "interpretation": "ELEVATED",
            "interpretation_summary": "Mean brightness is elevated above regional baseline.",
            "baseline_source": "VIIRS_NOAA20_SP",
            "baseline_scope": "regional_fallback",
            "is_fallback": True,
            "grid_cell": {"cell_id": "grid_24.2_82.5", "observation_count": 0},
            "comparisons": {"brightness_percent_difference": 8.5, "frp_percent_difference": 15.0},
            "standardized_deviation": {"brightness_z_score": 1.2, "frp_z_score": 0.8}
        }
        result = assess_historical_evidence(anomaly_res)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["anomaly_status"], "ELEVATED")
        self.assertTrue(result["is_fallback"])

    def test_historical_evidence_unavailable(self):
        result = assess_historical_evidence(None)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["anomaly_status"], "UNAVAILABLE")

    # 4. Geographic Evidence Tests
    def test_geographic_evidence_land(self):
        result = assess_geographic_evidence(self.sample_event_strong)
        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(result["land_water_class"], "LAND")
        self.assertEqual(result["state"], "Jharkhand")

    def test_geographic_evidence_marine(self):
        ev = {"geographic_validation": {"domain": "OFFSHORE_MARINE", "state": "Bay of Bengal"}}
        result = assess_geographic_evidence(ev)
        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(result["land_water_class"], "OFFSHORE_MARINE")

    # 5. Spatial Evidence Tests
    def test_spatial_evidence_strong(self):
        result = assess_spatial_evidence(self.sample_event_strong)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "STRONG")
        self.assertIsNotNone(result["centroid"])
        self.assertIsNotNone(result["observed_footprint"])

    def test_spatial_evidence_single(self):
        result = assess_spatial_evidence(self.sample_event_single)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["strength"], "LIMITED")

    # 6. Facility Context Tests
    def test_facility_context_present(self):
        asset_data = {
            "counts": {"industrial": 2, "power": 1, "hospitals": 0, "schools": 1},
            "assets": [
                {"name": "Steel Plant", "type": "industrial", "distance_km": 1.2},
                {"name": "Substation", "type": "power", "distance_km": 3.4}
            ]
        }
        result = assess_facility_context(asset_data)
        self.assertEqual(result["status"], "PRESENT")
        self.assertEqual(result["facilities_count"], 3)
        self.assertEqual(result["industrial_count"], 2)
        self.assertIn("does not establish source attribution", result["contextual_caveat"])

    def test_facility_context_not_identified(self):
        asset_data = {"counts": {"industrial": 0, "power": 0}, "assets": []}
        result = assess_facility_context(asset_data)
        self.assertEqual(result["status"], "NOT_IDENTIFIED")
        self.assertEqual(result["facilities_count"], 0)

    def test_facility_context_unqueried(self):
        result = assess_facility_context(None)
        self.assertEqual(result["status"], "UNAVAILABLE")

    # 7. Data Quality & Completeness Tests
    def test_data_quality_complete(self):
        t = {"status": "AVAILABLE"}
        tmp = {"status": "AVAILABLE"}
        h = {"status": "AVAILABLE", "baseline_source": "SP"}
        g = {"status": "VALIDATED"}
        s = {"status": "AVAILABLE"}
        f = {"status": "PRESENT"}
        result = assess_data_quality(t, tmp, h, g, s, f)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertGreaterEqual(len(result["available_evidence"]), 5)
        self.assertGreater(len(result["missing_evidence"]), 0)
        self.assertGreater(len(result["limitations"]), 0)

    # 8. Contradiction Detection Tests
    def test_contradiction_marine_domain(self):
        ev = {"observation_count": 5}
        t = {"observation_count": 5}
        tmp = {"persistence_days": 1}
        h = {"anomaly_status": "WITHIN_BASELINE"}
        g = {"land_water_class": "OFFSHORE_MARINE"}
        s = {}
        f = {"status": "NOT_IDENTIFIED"}
        contradictions = detect_contradictions(ev, t, tmp, h, g, s, f)
        self.assertTrue(any("offshore marine" in c.lower() for c in contradictions))

    def test_contradiction_elevated_small_sample(self):
        ev = {"observation_count": 1}
        t = {"observation_count": 1}
        tmp = {"persistence_days": 1}
        h = {"anomaly_status": "ELEVATED"}
        g = {"land_water_class": "LAND"}
        s = {}
        f = {"status": "PRESENT"}
        contradictions = detect_contradictions(ev, t, tmp, h, g, s, f)
        self.assertTrue(any("small" in c.lower() for c in contradictions))

    def test_contradiction_high_persistence_no_facility(self):
        ev = {"observation_count": 10}
        t = {"observation_count": 10, "has_frp": True}
        tmp = {"persistence_days": 4.0}
        h = {"anomaly_status": "WITHIN_BASELINE"}
        g = {"land_water_class": "LAND"}
        s = {}
        f = {"status": "NOT_IDENTIFIED"}
        contradictions = detect_contradictions(ev, t, tmp, h, g, s, f)
        self.assertTrue(any("persistence" in c.lower() for c in contradictions))

    # 9. Full Evidence Profile Integration
    def test_fuse_event_evidence_full_profile(self):
        profile = fuse_event_evidence(
            self.sample_event_strong,
            anomaly_result={"status": "AVAILABLE", "interpretation": "WITHIN_BASELINE"},
            asset_data={"counts": {"industrial": 1, "power": 0}, "assets": []}
        )
        self.assertEqual(profile["status"], "success")
        self.assertEqual(profile["event_id"], "EVT-TEST-STRONG")
        self.assertIn("summary", profile)
        self.assertIn("thermal", profile)
        self.assertIn("temporal", profile)
        self.assertIn("historical", profile)
        self.assertIn("geographic", profile)
        self.assertIn("spatial", profile)
        self.assertIn("facility_context", profile)
        self.assertIn("data_quality", profile)
        self.assertIn("contradictions", profile)

        # Check absence of forbidden fake confidence scores or source classifications
        self.assertNotIn("fire_probability", profile["summary"])
        self.assertNotIn("overall_confidence_percent", profile["summary"])
        self.assertNotIn("predicted_source", profile["summary"])

    # 10. API TestClient Endpoint Test
    def test_api_get_evidence_endpoint(self):
        client = TestClient(app)
        res = client.get("/events/EVT-000029/evidence")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["event_id"], "EVT-000029")
        self.assertIn("summary", data)
        self.assertIn("categories", data["summary"])
        self.assertEqual(data["summary"]["categories"]["thermal"], "STRONG")
        self.assertEqual(data["summary"]["categories"]["temporal"], "STRONG")
        self.assertEqual(data["summary"]["categories"]["geographic"], "VALIDATED")


if __name__ == "__main__":
    unittest.main()
