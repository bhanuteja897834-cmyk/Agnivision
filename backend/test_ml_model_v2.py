"""
Unit tests for AGNIVISION-GIS V2 Candidate B ML Model Integration (Checkpoint 7)
Tests:
 1. Model loading & V2 metadata
 2. Exact 28-feature schema
 3. Exact 28-feature sequence & order
 4. Contextual static distance calculation (World Bank, GEM, OSM)
 5. NaN handling & validation failure
 6. Infinite (Inf) value handling
 7. Direct prediction on observation
 8. Probability calibration and distribution (sums to 1.0)
 9. Fallback & routing to V1 legacy model
10. Invalid feature vector rejection
11. All four target ML classes representation
12. FastAPI API compatibility (/ml/predict and /ml/metadata)
"""

import math
import numpy as np
import unittest
from fastapi.testclient import TestClient

try:
    from backend.ml_model import (
        ml_model_service,
        EXPECTED_FEATURES_V1,
        EXPECTED_FEATURES_V2,
        validate_feature_vector,
        MODEL_VERSION_V1,
        MODEL_VERSION_V2,
    )
    from backend.ml_context import context_registry_manager
    import backend.main as main_module
except ModuleNotFoundError:
    from ml_model import (
        ml_model_service,
        EXPECTED_FEATURES_V1,
        EXPECTED_FEATURES_V2,
        validate_feature_vector,
        MODEL_VERSION_V1,
        MODEL_VERSION_V2,
    )
    from ml_context import context_registry_manager
    import main as main_module

app = main_module.app
_ensure_events_cache = main_module._ensure_events_cache
find_event = main_module.find_event


class TestMLModelV2Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_events_cache()
        cls.client = TestClient(app)
        cls.dummy_obs = {
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
        cls.dummy_weather = {
            "temperature_c": 28.5,
            "u10": 2.1,
            "v10": -1.4,
            "wind_speed_mps": 2.52,
            "precipitation_mm": 0.0,
            "available": True
        }

    def test_01_model_loading(self):
        """1. Model loading: Verify V2 candidate model loads and returns correct metadata."""
        meta = ml_model_service.get_model_metadata(version="v2")
        self.assertTrue(meta["is_loaded"], "V2 candidate model must be loaded into memory")
        self.assertEqual(meta["model_version"], MODEL_VERSION_V2)
        self.assertEqual(meta["model_type"], "RandomForestClassifier")
        self.assertEqual(meta["n_estimators"], 400)
        self.assertEqual(meta["feature_count"], 28)
        self.assertEqual(
            sorted(meta["classes"]),
            sorted(["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"])
        )
        self.assertTrue(ml_model_service.is_ready("v2"))

    def test_02_28_feature_schema(self):
        """2. 28-feature schema: Verify schema specification contains exactly 28 features."""
        self.assertEqual(len(EXPECTED_FEATURES_V2), 28)
        # Check first 25 match V1 production schema
        self.assertEqual(EXPECTED_FEATURES_V2[:25], EXPECTED_FEATURES_V1)
        # Check last 3 are distance features
        self.assertEqual(
            EXPECTED_FEATURES_V2[25:],
            ["dist_worldbank_km", "dist_gem_km", "dist_osm_km"]
        )

    def test_03_feature_order(self):
        """3. Feature order: Verify extraction adheres strictly to required feature sequence."""
        vector, feat_dict, err = ml_model_service.extract_features(
            observation=self.dummy_obs,
            spatial_context=[self.dummy_obs],
            weather=self.dummy_weather,
            version="v2"
        )
        self.assertIsNone(err)
        self.assertIsNotNone(vector)
        self.assertEqual(len(vector), 28)

        # Verify key feature values in specific positions
        self.assertEqual(vector[0], 335.5)                          # brightness
        self.assertEqual(vector[1], 298.2)                          # bright_t31
        self.assertEqual(vector[2], 12.4)                           # frp
        self.assertEqual(vector[8], 28.5)                           # temperature_c
        self.assertEqual(vector[13], round(335.5 - 298.2, 4))       # brightness_t31_delta
        self.assertEqual(vector[24], 0.0)                           # sensor_source_encoded (N20)
        self.assertGreater(vector[25], 0.0)                         # dist_worldbank_km
        self.assertGreater(vector[26], 0.0)                         # dist_gem_km
        self.assertGreater(vector[27], 0.0)                         # dist_osm_km

        for idx, name in enumerate(EXPECTED_FEATURES_V2):
            self.assertEqual(vector[idx], feat_dict[name])

    def test_04_context_distance_calculation(self):
        """4. Context-distance calculation: Static nearest-neighbor calculation works without leakage."""
        self.assertTrue(context_registry_manager.is_ready)
        d_wb, d_gem, d_osm, err = context_registry_manager.compute_distances(23.8, 86.4)
        self.assertIsNone(err)
        self.assertIsInstance(d_wb, float)
        self.assertIsInstance(d_gem, float)
        self.assertIsInstance(d_osm, float)
        self.assertGreater(d_wb, 0.0)
        self.assertGreater(d_gem, 0.0)
        self.assertGreater(d_osm, 0.0)
        # Expected approximate distance to nearest OSM industrial facility near Dhanbad/Jharia (~1.88 km)
        self.assertAlmostEqual(d_osm, 1.887, delta=0.5)

    def test_05_nan_handling(self):
        """5. NaN handling: NaN coordinates or feature values must be rejected safely."""
        # NaN coordinate
        d_wb, d_gem, d_osm, err = context_registry_manager.compute_distances(float("nan"), 86.4)
        self.assertIsNotNone(err)
        self.assertIn("non-finite", err.lower())

        # Vector with NaN
        bad_vector = [1.0] * 28
        bad_vector[5] = float("nan")
        is_valid, reason = validate_feature_vector(bad_vector, EXPECTED_FEATURES_V2)
        self.assertFalse(is_valid)
        self.assertIn("non-finite", reason.lower())

        # Prediction with bad vector
        res = ml_model_service.predict_observation(bad_vector)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("validation failed", res["reason"].lower())

    def test_06_inf_handling(self):
        """6. Inf handling: Infinite values must fail safely."""
        # Vector with +Inf
        bad_vector = [1.0] * 28
        bad_vector[10] = float("inf")
        is_valid, reason = validate_feature_vector(bad_vector, EXPECTED_FEATURES_V2)
        self.assertFalse(is_valid)
        self.assertIn("non-finite", reason.lower())

        res = ml_model_service.predict_observation(bad_vector)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("validation failed", res["reason"].lower())

    def test_07_prediction(self):
        """7. Prediction: Observation prediction with V2 model succeeds."""
        res = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v2"
        )
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["model_version"], MODEL_VERSION_V2)
        self.assertEqual(res["feature_schema_version"], "28_features_v2")
        self.assertIn(
            res["predicted_class"],
            ["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"]
        )
        self.assertGreaterEqual(res["confidence"], 0.0)
        self.assertLessEqual(res["confidence"], 1.0)

    def test_08_probability_output(self):
        """8. Probability output: Class probabilities are calibrated and sum to 1.0."""
        res = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v2"
        )
        probs = res["probabilities"]
        self.assertIsInstance(probs, dict)
        self.assertEqual(
            set(probs.keys()),
            {"AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"}
        )
        prob_sum = sum(probs.values())
        self.assertAlmostEqual(prob_sum, 1.0, places=2)

    def test_09_fallback_to_old_model(self):
        """9. Fallback & routing: Explicit routing between 25-feature and 28-feature models."""
        # 25-feature vector routes to V1 production model
        v1_vector = [1.0] * 25
        res_v1 = ml_model_service.predict_observation(v1_vector)
        self.assertEqual(res_v1["status"], "ready")
        self.assertEqual(res_v1["model_version"], MODEL_VERSION_V1)
        self.assertEqual(res_v1["feature_schema_version"], "25_features_v1")
        self.assertIn(
            res_v1["predicted_class"],
            ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"]
        )

        # 28-feature vector routes to V2 Candidate B model
        v2_vector = [1.0] * 28
        res_v2 = ml_model_service.predict_observation(v2_vector)
        self.assertEqual(res_v2["status"], "ready")
        self.assertEqual(res_v2["model_version"], MODEL_VERSION_V2)
        self.assertEqual(res_v2["feature_schema_version"], "28_features_v2")
        self.assertIn(
            res_v2["predicted_class"],
            ["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"]
        )

    def test_10_invalid_feature_vector_rejection(self):
        """10. Invalid feature vector rejection: Rejects vectors with wrong length or bad types."""
        # 20 features (neither 25 nor 28)
        res_wrong_len = ml_model_service.predict_observation([1.0] * 20)
        self.assertEqual(res_wrong_len["status"], "unavailable")
        self.assertIn("Invalid feature vector length", res_wrong_len["reason"])

        # Non-numeric string in vector
        bad_types = [1.0] * 28
        bad_types[2] = "not_a_number"
        res_bad_types = ml_model_service.predict_observation(bad_types)
        self.assertEqual(res_bad_types["status"], "unavailable")
        self.assertIn("validation failed", res_bad_types["reason"].lower())

    def test_11_all_four_ml_classes(self):
        """11. All four ML classes: Verify all 4 target classes are supported and non-empty."""
        target_classes = ["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"]
        meta = ml_model_service.get_model_metadata(version="v2")
        for cls_name in target_classes:
            self.assertIn(cls_name, meta["classes"])
        self.assertEqual(len(meta["classes"]), 4)

    def test_12_api_compatibility(self):
        """12. API compatibility: Test /ml/predict?model_version=v2 and /ml/metadata?version=v2."""
        # Test /ml/predict with model_version=v2
        resp = self.client.get("/ml/predict?event_id=EVT-000029&model_version=v2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("model_version"), MODEL_VERSION_V2)
        self.assertEqual(data.get("feature_schema_version"), "28_features_v2")
        self.assertIn(
            data.get("predicted_class"),
            ["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"]
        )
        self.assertIn("dist_osm_km", data.get("features_used", {}))

        # Test /ml/metadata with version=v2
        resp_meta = self.client.get("/ml/metadata?version=v2")
        self.assertEqual(resp_meta.status_code, 200)
        meta_data = resp_meta.json()
        self.assertEqual(meta_data.get("model_version"), MODEL_VERSION_V2)
        self.assertEqual(meta_data.get("feature_count"), 28)
        self.assertIn("context_registry_status", meta_data)


if __name__ == "__main__":
    unittest.main()
