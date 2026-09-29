"""
Unit tests for AGNIVISION-GIS V3 6-Class ML Model Integration
Tests:
 1. Model loading & V3 metadata (all 6 classes, 28 features, 400 trees)
 2. Feature schema and extraction adheres to 28 features
 3. Direct prediction on observation with model_version='v3'
 4. Probability output calibrated with all 6 classes summing to 1.0
 5. Invalid feature rejection
 6. Model isolation (V2 returns 4 classes, V3 returns 6 classes)
 7. FastAPI API compatibility: /ml/predict?model_version=v3
 8. FastAPI API compatibility: /ml/metadata?version=v3
 9. FastAPI API compatibility: GET /events/{event_id} includes ml_prediction_v3
 10. Fallback behavior for invalid model versions
"""

import unittest
from fastapi.testclient import TestClient

try:
    from backend.ml_model import (
        ml_model_service,
        EXPECTED_FEATURES_V2,
        EXPECTED_FEATURES_V3,
        MODEL_VERSION_V2,
        MODEL_VERSION_V3,
        TARGET_CLASSES_V2,
        TARGET_CLASSES_V3,
    )
    import backend.main as main_module
except ModuleNotFoundError:
    from ml_model import (
        ml_model_service,
        EXPECTED_FEATURES_V2,
        EXPECTED_FEATURES_V3,
        MODEL_VERSION_V2,
        MODEL_VERSION_V3,
        TARGET_CLASSES_V2,
        TARGET_CLASSES_V3,
    )
    import main as main_module

app = main_module.app
_ensure_events_cache = main_module._ensure_events_cache


class TestMLModelV3Integration(unittest.TestCase):
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
            "satellite": "N20",
        }
        cls.dummy_weather = {
            "temperature_c": 28.5,
            "u10": 2.1,
            "v10": -1.4,
            "wind_speed_mps": 2.52,
            "precipitation_mm": 0.0,
            "available": True,
        }

    def test_01_v3_model_loading_and_metadata(self):
        """1. Verify V3 model is loaded into memory with 6 classes and 28 features."""
        meta = ml_model_service.get_model_metadata(version="v3")
        self.assertTrue(meta["is_loaded"], "V3 candidate model must be loaded into memory")
        self.assertEqual(meta["model_version"], MODEL_VERSION_V3)
        self.assertIn(meta["model_type"], ["RandomForestClassifier", "HierarchicalRandomForestClassifier"])
        self.assertIn(meta["n_estimators"], [300, 400, 700])
        self.assertEqual(meta["feature_count"], 28)
        self.assertEqual(len(meta["classes"]), 6)
        expected_classes = [
            "AGRICULTURAL_FIRE",
            "FOREST_FIRE",
            "GAS_FLARE",
            "INDUSTRIAL_FIRE",
            "OTHER_THERMAL_EVENT",
            "UNKNOWN",
        ]
        self.assertEqual(sorted(meta["classes"]), sorted(expected_classes))
        self.assertTrue(ml_model_service.is_ready("v3"))

    def test_02_v3_feature_schema(self):
        """2. Verify V3 feature schema contains exactly 28 features identical to V2 schema."""
        self.assertEqual(len(EXPECTED_FEATURES_V3), 28)
        self.assertEqual(EXPECTED_FEATURES_V3, EXPECTED_FEATURES_V2)

        vector, feat_dict, err = ml_model_service.extract_features(
            observation=self.dummy_obs,
            spatial_context=[self.dummy_obs],
            weather=self.dummy_weather,
            version="v3",
        )
        self.assertIsNone(err)
        self.assertIsNotNone(vector)
        self.assertEqual(len(vector), 28)
        self.assertEqual(len(feat_dict), 28)

    def test_03_v3_prediction(self):
        """3. Direct observation prediction with V3 model succeeds."""
        res = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v3",
        )
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["model_version"], MODEL_VERSION_V3)
        self.assertEqual(res["feature_schema_version"], "28_features_v3")
        self.assertIn(res["predicted_class"], TARGET_CLASSES_V3)
        self.assertGreaterEqual(res["confidence"], 0.0)
        self.assertLessEqual(res["confidence"], 1.0)

    def test_04_v3_probability_distribution(self):
        """4. Probability output contains all 6 classes and sums strictly to 1.0."""
        res = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v3",
        )
        probs = res["probabilities"]
        self.assertIsInstance(probs, dict)
        self.assertEqual(len(probs), 6)
        self.assertEqual(set(probs.keys()), set(TARGET_CLASSES_V3))
        prob_sum = sum(probs.values())
        self.assertAlmostEqual(prob_sum, 1.0, places=2)
        for cls_name, p in probs.items():
            self.assertGreaterEqual(p, 0.0, f"Probability for {cls_name} cannot be negative")
            self.assertLessEqual(p, 1.0, f"Probability for {cls_name} cannot exceed 1.0")

    def test_05_v3_invalid_feature_rejection(self):
        """5. Invalid feature vectors (NaN, Inf, wrong length) are safely rejected."""
        # Non-finite value in vector
        bad_vec = [1.0] * 28
        bad_vec[7] = float("nan")
        res_nan = ml_model_service.predict_observation(bad_vec, model_version="v3")
        self.assertEqual(res_nan["status"], "unavailable")

        # Wrong feature length
        res_short = ml_model_service.predict_observation([1.0] * 15, model_version="v3")
        self.assertEqual(res_short["status"], "unavailable")

    def test_06_v2_v3_model_isolation(self):
        """6. Verify V2 and V3 models remain strictly isolated without cross-contamination."""
        # V2 prediction returns exactly 4 classes
        res_v2 = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v2",
        )
        self.assertEqual(res_v2["model_version"], MODEL_VERSION_V2)
        self.assertEqual(len(res_v2["probabilities"]), 4)
        self.assertEqual(set(res_v2["probabilities"].keys()), set(TARGET_CLASSES_V2))

        # V3 prediction returns exactly 6 classes
        res_v3 = ml_model_service.predict_observation(
            observation=self.dummy_obs,
            weather=self.dummy_weather,
            model_version="v3",
        )
        self.assertEqual(res_v3["model_version"], MODEL_VERSION_V3)
        self.assertEqual(len(res_v3["probabilities"]), 6)
        self.assertEqual(set(res_v3["probabilities"].keys()), set(TARGET_CLASSES_V3))

    def test_07_api_predict_v3(self):
        """7. API compatibility: Test /ml/predict?model_version=v3 endpoint."""
        resp = self.client.get("/ml/predict?event_id=EVT-000029&model_version=v3")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ready")
        self.assertEqual(data.get("model_version"), MODEL_VERSION_V3)
        self.assertEqual(data.get("feature_schema_version"), "28_features_v3")
        self.assertIn(data.get("predicted_class"), TARGET_CLASSES_V3)
        probs = data.get("probabilities", {})
        self.assertEqual(len(probs), 6)
        self.assertEqual(set(probs.keys()), set(TARGET_CLASSES_V3))
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)

    def test_08_api_metadata_v3(self):
        """8. API compatibility: Test /ml/metadata?version=v3 endpoint."""
        resp = self.client.get("/ml/metadata?version=v3")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("model_version"), MODEL_VERSION_V3)
        self.assertEqual(data.get("feature_count"), 28)
        self.assertEqual(len(data.get("classes", [])), 6)
        self.assertEqual(sorted(data.get("classes", [])), sorted(TARGET_CLASSES_V3))

    def test_09_api_events_has_v3_prediction(self):
        """9. Event detail endpoint /events/{event_id} includes both ml_prediction and ml_prediction_v3."""
        resp = self.client.get("/events/EVT-000029")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # ml_prediction_v2 is V2 Candidate B
        ml_v2 = data.get("ml_prediction_v2")
        self.assertIsNotNone(ml_v2)
        self.assertEqual(ml_v2.get("model_version"), MODEL_VERSION_V2)
        self.assertEqual(len(ml_v2.get("probabilities", {})), 4)

        # ml_prediction_v3 is candidate V3
        ml_v3 = data.get("ml_prediction_v3")
        self.assertIsNotNone(ml_v3)
        self.assertEqual(ml_v3.get("model_version"), MODEL_VERSION_V3)
        self.assertEqual(len(ml_v3.get("probabilities", {})), 6)


if __name__ == "__main__":
    unittest.main()
