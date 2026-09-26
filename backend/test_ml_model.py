"""
Unit tests for AGNIVISION-GIS Trained Random Forest ML Inference Service (Step 2)
Tests:
- Model metadata inspection (type, estimators, classes, 13 features)
- Exact 13 features extraction and sequence
- Missing/invalid feature validation
- Weather unavailability handling
- Model inference and probability calibration on EVT-000029 and EVT-000001
- FastAPI /ml/predict and /ml/metadata endpoints
- Safe inclusion in /events/{event_id} preserving rule-based classification
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient

try:
    from backend.ml_model import ml_model_service, EXPECTED_FEATURES
    import backend.main as main_module
except ModuleNotFoundError:
    from ml_model import ml_model_service, EXPECTED_FEATURES
    import main as main_module

app = main_module.app
_ensure_events_cache = main_module._ensure_events_cache
find_event = main_module.find_event


class TestMLModelIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_events_cache()
        cls.client = TestClient(app)

    def test_01_model_loaded_and_metadata(self):
        """Verify model loads into memory once and matches training specifications."""
        meta = ml_model_service.get_model_metadata()
        self.assertTrue(meta["is_loaded"], "Model must be loaded into memory")
        self.assertEqual(meta["model_type"], "RandomForestClassifier")
        self.assertEqual(meta["n_estimators"], 400)
        self.assertEqual(meta["feature_count"], 25)
        self.assertEqual(meta["classes"], ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"])
        self.assertEqual(meta["expected_features"], EXPECTED_FEATURES)

    def test_02_exact_25_features_order(self):
        """Verify feature vector matches the exact 25 features in exact required order."""
        expected_seq = [
            "brightness",
            "bright_t31",
            "frp",
            "detections_same_cell",
            "active_days_same_cell",
            "mean_frp_same_cell",
            "max_frp_same_cell",
            "frp_vs_local_mean",
            "temperature_c",
            "u10",
            "v10",
            "wind_speed_mps",
            "precipitation_mm",
            "brightness_t31_delta",
            "log_frp",
            "detections_per_active_day",
            "frp_max_minus_mean",
            "acq_hour",
            "month",
            "hour_sin",
            "hour_cos",
            "month_sin",
            "month_cos",
            "is_day",
            "sensor_source_encoded"
        ]
        self.assertEqual(EXPECTED_FEATURES, expected_seq)

        dummy_obs = {
            "latitude": 23.8,
            "longitude": 86.4,
            "brightness": 335.5,
            "bright_ti5": 298.2,
            "frp": 12.4,
            "acq_date": "2026-09-20",
            "acq_time": "1200",
            "daynight": "D",
            "satellite": "N20"
        }
        dummy_weather = {
            "temperature_c": 28.5,
            "u10": 2.1,
            "v10": -1.4,
            "wind_speed_mps": 2.52,
            "precipitation_mm": 0.0,
            "available": True
        }

        vector, feat_dict, err = ml_model_service.extract_features(
            observation=dummy_obs,
            spatial_context=[dummy_obs],
            weather=dummy_weather
        )
        self.assertIsNone(err)
        self.assertIsNotNone(vector)
        self.assertEqual(len(vector), 25)
        self.assertEqual(vector[0], 335.5)  # brightness
        self.assertEqual(vector[1], 298.2)  # bright_t31
        self.assertEqual(vector[2], 12.4)   # frp
        self.assertEqual(vector[3], 1.0)    # detections_same_cell
        self.assertEqual(vector[4], 1.0)    # active_days_same_cell
        self.assertEqual(vector[5], 12.4)   # mean_frp_same_cell
        self.assertEqual(vector[6], 12.4)   # max_frp_same_cell
        self.assertEqual(vector[7], 0.0)    # frp_vs_local_mean (frp - mean_frp)
        self.assertEqual(vector[8], 28.5)   # temperature_c
        self.assertEqual(vector[9], 2.1)    # u10
        self.assertEqual(vector[10], -1.4)  # v10
        self.assertEqual(vector[11], 2.52)  # wind_speed_mps
        self.assertEqual(vector[12], 0.0)   # precipitation_mm
        self.assertEqual(vector[13], round(335.5 - 298.2, 4))  # brightness_t31_delta
        self.assertGreater(vector[14], 0.0) # log_frp
        self.assertEqual(vector[15], 1.0)   # detections_per_active_day
        self.assertEqual(vector[16], 0.0)   # frp_max_minus_mean
        self.assertEqual(vector[17], 12.0)  # acq_hour
        self.assertEqual(vector[18], 9.0)   # month
        self.assertEqual(vector[23], 1.0)   # is_day
        self.assertEqual(vector[24], 0.0)   # sensor_source_encoded (N20)

    def test_03_missing_feature_handling(self):
        """Missing required features must return status unavailable without crashing."""
        # Missing brightness
        obs_no_b = {"latitude": 23.8, "longitude": 86.4, "bright_ti5": 298.2, "frp": 12.4}
        res = ml_model_service.predict_observation(obs_no_b)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("brightness", res["reason"].lower())

        # Missing thermal channel (neither bright_t31 nor bright_ti5)
        obs_no_t31 = {"latitude": 23.8, "longitude": 86.4, "brightness": 335.5, "frp": 12.4}
        res = ml_model_service.predict_observation(obs_no_t31)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("bright_t31", res["reason"].lower())

        # Missing FRP
        obs_no_frp = {"latitude": 23.8, "longitude": 86.4, "brightness": 335.5, "bright_ti5": 298.2}
        res = ml_model_service.predict_observation(obs_no_frp)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("frp", res["reason"].lower())

    def test_04_weather_unavailable_handling(self):
        """If atmospheric weather is unavailable, prediction must be unavailable with explicit reason."""
        obs = {"latitude": 23.8, "longitude": 86.4, "brightness": 335.5, "bright_ti5": 298.2, "frp": 12.4}
        unavailable_weather = {"available": False}
        res = ml_model_service.predict_observation(obs, weather=unavailable_weather)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("weather", res["reason"].lower())

    def test_05_predict_evt_000029(self):
        """Predict on authoritative landmark event EVT-000029."""
        ev = find_event("EVT-000029")
        self.assertIsNotNone(ev, "EVT-000029 must exist")

        res = ml_model_service.predict_event(ev)
        self.assertEqual(res["status"], "ready")
        self.assertIn(res["predicted_class"], ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"])
        self.assertGreater(res["confidence"], 0.0)
        self.assertLessEqual(res["confidence"], 1.0)

        # Probabilities dictionary validation
        probs = res["probabilities"]
        self.assertEqual(set(probs.keys()), {"AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"})
        prob_sum = sum(probs.values())
        self.assertAlmostEqual(prob_sum, 1.0, places=2)

        # Features validation
        feats = res["features_used"]
        self.assertEqual(len(feats), 25)
        for expected in EXPECTED_FEATURES:
            self.assertIn(expected, feats)
            self.assertIsNotNone(feats[expected])

    def test_06_predict_evt_000001(self):
        """Predict on landmark event EVT-000001."""
        ev = find_event("EVT-000001")
        self.assertIsNotNone(ev, "EVT-000001 must exist")

        res = ml_model_service.predict_event(ev)
        self.assertEqual(res["status"], "ready")
        self.assertIn(res["predicted_class"], ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"])
        prob_sum = sum(res["probabilities"].values())
        self.assertAlmostEqual(prob_sum, 1.0, places=2)

    def test_07_api_ml_predict_endpoint(self):
        """Test GET /ml/predict?event_id=EVT-000029."""
        resp = self.client.get("/ml/predict?event_id=EVT-000029")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("event_id"), "EVT-000029")
        self.assertIn(data.get("predicted_class"), ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"])
        self.assertIn("confidence", data)
        self.assertIn("probabilities", data)
        self.assertIn("features_used", data)

    def test_08_api_ml_metadata_endpoint(self):
        """Test GET /ml/metadata."""
        resp = self.client.get("/ml/metadata")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("is_loaded"))
        self.assertEqual(data.get("model_type"), "RandomForestClassifier")
        self.assertEqual(data.get("feature_count"), 25)

    def test_09_event_details_ml_enrichment_preserves_rules(self):
        """Test that GET /events/EVT-000029 safely includes ml_prediction and keeps system_classification intact."""
        resp = self.client.get("/events/EVT-000029")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Rule-based classification must remain intact
        self.assertIn("system_classification", data)
        self.assertNotEqual(data["system_classification"], "")

        # ML prediction must be present
        self.assertIn("ml_prediction", data)
        ml_pred = data["ml_prediction"]
        self.assertEqual(ml_pred.get("status"), "ready")
        self.assertIn("predicted_class", ml_pred)
        self.assertIn("confidence", ml_pred)
        self.assertIn("probabilities", ml_pred)


if __name__ == "__main__":
    unittest.main()
