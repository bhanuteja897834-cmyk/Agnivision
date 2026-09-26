"""
Unit tests for AGNIVISION-GIS Step 3: Evidence-Based Event Assessment Layer
Tests:
- Multi-source signal integration (ML, thermal radiance, persistence, anomaly, OSM)
- Assessment categories:
  - LIKELY_INDUSTRIAL_HEAT (EVT-000029, EVT-000001)
  - LIKELY_AGRICULTURAL_BURNING (EVT-000002)
  - HIGH_PRIORITY_THERMAL_EVENT (EVT-000230)
  - LOW_CONFIDENCE_THERMAL_ANOMALY (marginal detection / marine constraint)
- Explainability and evidence structure
- Dedicated GET /events/{event_id}/assessment endpoint
- Backward-compatible enrichment of GET /events/{event_id}
"""

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

try:
    import backend.main as main_module
    import backend.weather_service as weather_module
    import backend.ml_model as ml_module
    from backend.event_assessment import (
        assess_event,
        ASSESSMENT_HIGH_PRIORITY,
        ASSESSMENT_INDUSTRIAL_HEAT,
        ASSESSMENT_AGRICULTURAL,
        ASSESSMENT_WILDLAND,
        ASSESSMENT_LOW_CONFIDENCE,
        ASSESSMENT_UNRESOLVED,
    )
except ModuleNotFoundError:
    import main as main_module
    import weather_service as weather_module
    import ml_model as ml_module
    from event_assessment import (
        assess_event,
        ASSESSMENT_HIGH_PRIORITY,
        ASSESSMENT_INDUSTRIAL_HEAT,
        ASSESSMENT_AGRICULTURAL,
        ASSESSMENT_WILDLAND,
        ASSESSMENT_LOW_CONFIDENCE,
        ASSESSMENT_UNRESOLVED,
    )

app = main_module.app
_ensure_events_cache = main_module._ensure_events_cache
find_event = main_module.find_event
get_historical_baseline_manager = main_module.get_historical_baseline_manager
_ensure_historical_baseline = main_module._ensure_historical_baseline

# Deterministic representative weather telemetry for tests
DETERMINISTIC_WEATHER = {
    "temperature_c": 28.5,
    "u10": 2.1,
    "v10": -1.4,
    "wind_speed_mps": 2.52,
    "precipitation_mm": 0.0,
    "source": "Open-Meteo",
    "available": True,
}


class TestEventAssessment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_events_cache()
        cls.mgr = get_historical_baseline_manager()
        _ensure_historical_baseline(cls.mgr)
        cls.client = TestClient(app)

        # Pin weather across all access paths in assess_event() and app endpoints
        cls._weather_patches = [
            patch.object(weather_module.weather_service, "get_weather_for_location", return_value=DETERMINISTIC_WEATHER),
            patch.object(weather_module, "get_weather_for_location", return_value=DETERMINISTIC_WEATHER),
            patch.object(ml_module, "get_weather_for_location", return_value=DETERMINISTIC_WEATHER),
        ]
        for p in cls._weather_patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_weather_patches"):
            for p in cls._weather_patches:
                try:
                    p.stop()
                except Exception:
                    pass

    def test_01_assess_evt_000029(self):
        """EVT-000029: Extreme stationary persistence (133 obs, 5 days) outweighs Wildland ML -> GAS_FLARE."""
        ev = find_event("EVT-000029")
        self.assertIsNotNone(ev)
        res = assess_event(ev, baseline_manager=self.mgr)

        self.assertEqual(res["event_id"], "EVT-000029")
        self.assertEqual(res["ml_class"], "WILDLAND_FIRE")
        self.assertIn(res["assessment"], ["GAS_FLARE", ASSESSMENT_INDUSTRIAL_HEAT])
        self.assertEqual(res["assessment_confidence"], "HIGH")
        self.assertIn("explanation", res)
        self.assertIn("133", res["explanation"])
        self.assertIn("5", res["explanation"])

        # Check evidence structure
        ev_data = res["evidence"]
        self.assertEqual(ev_data["thermal"]["observation_count"], 133)
        self.assertEqual(ev_data["temporal"]["distinct_days"], 5)
        self.assertIn("WILDLAND_FIRE", ev_data["ml_inference"]["probabilities"])

    def test_02_assess_evt_000001(self):
        """EVT-000001: 83 detections across 5 days reflects stationary persistent heat -> GAS_FLARE."""
        ev = find_event("EVT-000001")
        self.assertIsNotNone(ev)
        res = assess_event(ev, baseline_manager=self.mgr)

        self.assertEqual(res["event_id"], "EVT-000001")
        self.assertEqual(res["ml_class"], "WILDLAND_FIRE")
        self.assertIn(res["assessment"], ["GAS_FLARE", ASSESSMENT_INDUSTRIAL_HEAT])
        self.assertEqual(res["assessment_confidence"], "HIGH")
        self.assertIn("83", res["explanation"])

    def test_03_assess_evt_000002(self):
        """EVT-000002: Single-pass episodic agricultural burning -> AGRICULTURAL_FIRE."""
        ev = find_event("EVT-000002")
        self.assertIsNotNone(ev)
        res = assess_event(ev, baseline_manager=self.mgr)

        self.assertEqual(res["event_id"], "EVT-000002")
        self.assertIn(res["ml_class"], ["AGRICULTURAL_BURNING", "WILDLAND_FIRE"])
        self.assertGreaterEqual(res["evidence"]["ml_inference"]["probabilities"].get("AGRICULTURAL_BURNING", 0.0), 0.40)
        self.assertIn(res["assessment"], ["AGRICULTURAL_FIRE", ASSESSMENT_AGRICULTURAL])
        self.assertEqual(res["assessment_confidence"], "MODERATE")
        self.assertIn("crop", res["explanation"].lower())

    def test_04_assess_evt_000230(self):
        """EVT-000230: Peak FRP of 6.6 MW (> 5.0 MW threshold) warrants HIGH_PRIORITY."""
        ev = find_event("EVT-000230")
        self.assertIsNotNone(ev)
        res = assess_event(ev, baseline_manager=self.mgr)

        self.assertEqual(res["event_id"], "EVT-000230")
        self.assertEqual(res["assessment"], ASSESSMENT_HIGH_PRIORITY)
        self.assertIn("peak frp", res["explanation"].lower())

    def test_05_low_confidence_anomaly(self):
        """Marginal single-pass detection with low FRP (< 2.0 MW) is LOW_CONFIDENCE_THERMAL_ANOMALY."""
        dummy_low = {
            "event_id": "EVT-DUMMY-LOW",
            "observation_count": 1,
            "persistence_days": 1.0,
            "observations": [{
                "latitude": 23.0,
                "longitude": 85.0,
                "brightness": 308.0,
                "bright_ti4": 308.0,
                "bright_ti5": 288.0,
                "frp": 1.2,
                "acq_date": "2026-09-20"
            }],
            "frp_summary": {"max": 1.2, "mean": 1.2},
            "brightness_summary": {"max": 308.0, "mean": 308.0},
            "geographic_validation": {"domain": "LAND", "state": "Jharkhand"}
        }
        res = assess_event(
            dummy_low,
            anomaly_result={"status": "AVAILABLE", "interpretation": "WITHIN_BASELINE"},
            asset_data={"industrial": [], "power": []}
        )
        self.assertEqual(res["assessment"], ASSESSMENT_LOW_CONFIDENCE)
        self.assertIn("low-confidence thermal anomaly", res["explanation"].lower())

    def test_06_marine_domain_constraint(self):
        """Marine coordinates are classified as low-confidence / non-terrestrial."""
        dummy_marine = {
            "event_id": "EVT-DUMMY-MARINE",
            "observation_count": 1,
            "persistence_days": 1.0,
            "observations": [{
                "latitude": 18.0,
                "longitude": 88.0,
                "brightness": 320.0,
                "bright_ti4": 320.0,
                "bright_ti5": 290.0,
                "frp": 2.5,
                "acq_date": "2026-09-20"
            }],
            "geographic_validation": {"land_water_class": "OFFSHORE_MARINE", "domain": "OFFSHORE_MARINE"}
        }
        res = assess_event(dummy_marine)
        self.assertEqual(res["assessment"], ASSESSMENT_LOW_CONFIDENCE)
        self.assertIn("non-terrestrial", res["explanation"].lower())

    def test_07_api_event_assessment_endpoint(self):
        """Dedicated GET /events/{event_id}/assessment endpoint."""
        resp = self.client.get("/events/EVT-000029/assessment")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["event_id"], "EVT-000029")
        self.assertEqual(data["assessment"], ASSESSMENT_INDUSTRIAL_HEAT)
        self.assertIn("ml_class", data)
        self.assertIn("evidence", data)
        self.assertIn("explanation", data)

    def test_08_get_event_by_id_includes_assessment(self):
        """GET /events/{event_id} safely includes event_assessment and preserves rules."""
        resp = self.client.get("/events/EVT-000029")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Rule-based classification intact
        self.assertIn("system_classification", data)
        # ML prediction intact
        self.assertIn("ml_prediction", data)
        # Event assessment intact
        self.assertIn("event_assessment", data)
        assessment = data["event_assessment"]
        self.assertEqual(assessment["assessment"], ASSESSMENT_INDUSTRIAL_HEAT)


if __name__ == "__main__":
    unittest.main()
