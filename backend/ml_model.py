"""
AGNIVISION-GIS: Trained Random Forest ML Inference Service
Integrates the pre-trained 13-feature Random Forest Classifier for thermal event / observation classification.
Classes: Agricultural, Forest, Industrial, Other.

Features required (exact order):
 1. brightness: FIRMS thermal brightness (brightness or bright_ti4)
 2. bright_t31: actual FIRMS thermal-temperature channel (bright_t31 or bright_ti5)
 3. frp: FIRMS Fire Radiative Power (MW)
 4. detections_same_cell: count of thermal detections within the 0.1° (~11 km) grid cell
 5. active_days_same_cell: distinct observation acquisition dates within the same grid cell
 6. mean_frp_same_cell: mean Fire Radiative Power within the same grid cell
 7. max_frp_same_cell: peak Fire Radiative Power within the same grid cell
 8. frp_vs_local_mean: ratio of observation FRP to local cell mean (frp / mean_frp_same_cell)
 9. temperature_c: 2m air temperature (°C) from real NWP weather (Open-Meteo)
10. u10: 10m eastward wind vector component (m/s)
11. v10: 10m northward wind vector component (m/s)
12. wind_speed_mps: 10m wind speed (m/s)
13. precipitation_mm: precipitation (mm)
"""

import sys
import types
import os
import math
import re

import logging
import statistics
from typing import Dict, Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Windows Smart App Control Compatibility Shims
# Scikit-learn imports unused legacy routines on initialization that are blocked
# by Windows Smart App Control on recent Python builds. Providing lightweight
# module shims allows Random Forest and Decision Tree models to operate uninhibited.
# ---------------------------------------------------------------------------
if 'sklearn.preprocessing._csr_polynomial_expansion' not in sys.modules:
    _poly_mod = types.ModuleType('sklearn.preprocessing._csr_polynomial_expansion')
    _poly_mod._calc_expanded_nnz = lambda *a, **k: None
    _poly_mod._calc_total_nnz = lambda *a, **k: None
    _poly_mod._csr_polynomial_expansion = lambda *a, **k: None
    sys.modules['sklearn.preprocessing._csr_polynomial_expansion'] = _poly_mod

if 'sklearn.linear_model._sgd_fast' not in sys.modules:
    class _DummySGD:
        pass
    _sgd_mod = types.ModuleType('sklearn.linear_model._sgd_fast')
    _sgd_mod.EpsilonInsensitive = _DummySGD
    _sgd_mod.Hinge = _DummySGD
    _sgd_mod.ModifiedHuber = _DummySGD
    _sgd_mod.SquaredEpsilonInsensitive = _DummySGD
    _sgd_mod.SquaredHinge = _DummySGD
    _sgd_mod._plain_sgd32 = lambda *a, **k: None
    _sgd_mod._plain_sgd64 = lambda *a, **k: None
    sys.modules['sklearn.linear_model._sgd_fast'] = _sgd_mod

import io
import zipfile
import joblib
import pandas as pd
import sklearn

from weather_service import get_weather_for_location

logger = logging.getLogger("agnivision.ml_model")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ZIP_PATH = os.path.join(BASE_DIR, "data", "new_dataset", "AGNIVISION_final_model.zip")
MODEL_CANDIDATE_PATHS = [
    MODEL_ZIP_PATH,
    os.path.join(BASE_DIR, "data", "models", "agnivision_fire_classifier_final.pkl"),
    os.path.join(BASE_DIR, "data", "model", "agnivision_fire_classifier_final.pkl"),
    os.path.join(BASE_DIR, "models", "agnivision_fire_classifier_final.pkl"),
]

EXPECTED_FEATURES = [
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

GRID_CELL_DEG = 0.1


class MLModelService:
    """
    Manages loading, feature extraction, and inference for the pre-trained
    Random Forest fire classification model (25 features, 3 source classes).
    """

    def __init__(self):
        self._model = None
        self._model_path: Optional[str] = None
        self._feature_names: List[str] = list(EXPECTED_FEATURES)
        self._classes: List[str] = []
        self._sklearn_version: str = sklearn.__version__
        self._n_estimators: Optional[int] = None
        self._is_loaded = False
        self._load_error: Optional[str] = None

        # Automatically attempt load on instantiation
        self.load_model()

    def load_model(self) -> bool:
        """
        Loads the pre-trained Random Forest model from disk once into memory.
        Safely loads from AGNIVISION_final_model.zip without modifying the archive.
        """
        if self._is_loaded and self._model is not None:
            return True

        if os.path.exists(MODEL_ZIP_PATH):
            self._model_path = MODEL_ZIP_PATH
            try:
                logger.info(f"[ML_MODEL] Loading Random Forest model from ZIP archive: {MODEL_ZIP_PATH}...")
                with zipfile.ZipFile(MODEL_ZIP_PATH, "r") as z:
                    pkl_name = "agnivision_fire_classifier_final.pkl"
                    if pkl_name in z.namelist():
                        model_bytes = z.read(pkl_name)
                        model = joblib.load(io.BytesIO(model_bytes))
                    else:
                        raise FileNotFoundError(f"{pkl_name} not found inside {MODEL_ZIP_PATH}")

                    # Load features list from archive if present
                    feat_name = "agnivision_fire_classifier_final_features.pkl"
                    if feat_name in z.namelist():
                        feat_bytes = z.read(feat_name)
                        self._feature_names = list(joblib.load(io.BytesIO(feat_bytes)))

                # Suppress verbose multithreading stdout logging
                if hasattr(model, "verbose"):
                    model.verbose = 0
                if hasattr(model, "n_jobs"):
                    model.n_jobs = 1

                self._model = model
                self._classes = list(getattr(model, "classes_", []))
                self._n_estimators = getattr(model, "n_estimators", None)
                model_type = type(model).__name__

                self._is_loaded = True
                self._load_error = None

                logger.info(
                    f"[ML_MODEL] Model loaded successfully from ZIP: "
                    f"Type={model_type}, "
                    f"sklearn_version={self._sklearn_version}, "
                    f"n_estimators={self._n_estimators}, "
                    f"classes={self._classes}, "
                    f"feature_count={len(self._feature_names)}"
                )
                return True
            except Exception as e:
                self._load_error = f"Exception loading model from ZIP: {str(e)}"
                logger.error(f"[ML_MODEL] Failed to load model from ZIP: {self._load_error}")
                self._model = None
                self._is_loaded = False

        # Fallback to loose candidate pickle files
        for path in MODEL_CANDIDATE_PATHS[1:]:
            if os.path.exists(path):
                self._model_path = path
                break

        if not self._model_path or not os.path.exists(self._model_path):
            self._load_error = f"Model file not found in any candidate path: {MODEL_CANDIDATE_PATHS}"
            logger.warning(f"[ML_MODEL] {self._load_error}")
            return False

        try:
            logger.info(f"[ML_MODEL] Loading Random Forest model from {self._model_path}...")
            model = joblib.load(self._model_path)
            if hasattr(model, "verbose"):
                model.verbose = 0
            if hasattr(model, "n_jobs"):
                model.n_jobs = 1

            self._model = model
            self._classes = list(getattr(model, "classes_", []))
            self._n_estimators = getattr(model, "n_estimators", None)
            model_type = type(model).__name__
            feature_names = getattr(model, "feature_names_in_", None)
            if feature_names is not None:
                self._feature_names = list(feature_names)

            self._is_loaded = True
            self._load_error = None

            logger.info(
                f"[ML_MODEL] Model loaded successfully: "
                f"Type={model_type}, "
                f"sklearn_version={self._sklearn_version}, "
                f"n_estimators={self._n_estimators}, "
                f"classes={self._classes}, "
                f"feature_count={len(self._feature_names)}, "
                f"features={self._feature_names}"
            )
            return True
        except Exception as e:
            self._load_error = f"Exception loading model: {str(e)}"
            logger.error(f"[ML_MODEL] Failed to load model: {self._load_error}")
            self._model = None
            self._is_loaded = False
            return False

    def is_ready(self) -> bool:
        return self._is_loaded and self._model is not None

    def get_model_metadata(self) -> Dict[str, Any]:
        """Returns metadata about the loaded ML model."""
        return {
            "is_loaded": self._is_loaded,
            "model_path": self._model_path,
            "model_type": type(self._model).__name__ if self._model else None,
            "sklearn_version": self._sklearn_version,
            "n_estimators": self._n_estimators,
            "classes": self._classes,
            "expected_features": self._feature_names,
            "feature_count": len(self._feature_names),
            "error": self._load_error
        }

    def _get_cell_key(self, lat: float, lon: float) -> Tuple[float, float]:
        """Computes 0.1° grid cell coordinates."""
        return (
            round(math.floor(lat / GRID_CELL_DEG) * GRID_CELL_DEG, 2),
            round(math.floor(lon / GRID_CELL_DEG) * GRID_CELL_DEG, 2)
        )

    def extract_features(
        self,
        observation: Dict[str, Any],
        spatial_context: Optional[List[Dict[str, Any]]] = None,
        weather: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[List[float]], Optional[Dict[str, Any]], Optional[str]]:
        """
        Extracts the exact 25 features in the exact required sequence:
         1. brightness
         2. bright_t31
         3. frp
         4. detections_same_cell
         5. active_days_same_cell
         6. mean_frp_same_cell
         7. max_frp_same_cell
         8. frp_vs_local_mean (frp - mean_frp_same_cell)
         9. temperature_c
        10. u10
        11. v10
        12. wind_speed_mps
        13. precipitation_mm
        14. brightness_t31_delta (brightness - bright_t31)
        15. log_frp (log1p(max(frp, 0)))
        16. detections_per_active_day (detections / max(active_days, 1))
        17. frp_max_minus_mean (max_frp - mean_frp)
        18. acq_hour (0-23)
        19. month (1-12)
        20. hour_sin
        21. hour_cos
        22. month_sin
        23. month_cos
        24. is_day (1.0 if Day else 0.0)
        25. sensor_source_encoded (0=NOAA20, 1=SNPP, 2=UNKNOWN)

        Returns: (feature_vector, features_dict, error_reason)
        """
        features_dict: Dict[str, Any] = {}

        # 1. Thermal Brightness (brightness or bright_ti4)
        raw_b = observation.get("brightness")
        if raw_b is None or raw_b == "":
            raw_b = observation.get("bright_ti4")
        if raw_b is None or raw_b == "":
            return None, features_dict, "Missing brightness (neither 'brightness' nor 'bright_ti4' present)"
        try:
            brightness = float(raw_b)
        except (ValueError, TypeError):
            return None, features_dict, f"Invalid brightness value: {raw_b}"
        features_dict["brightness"] = brightness

        # 2. Thermal Channel 31 / I5 (bright_t31 or bright_ti5)
        raw_b31 = observation.get("bright_t31")
        if raw_b31 is None or raw_b31 == "":
            raw_b31 = observation.get("bright_ti5")
        if raw_b31 is None or raw_b31 == "":
            return None, features_dict, "Missing bright_t31 (neither 'bright_t31' nor 'bright_ti5' present)"
        try:
            bright_t31 = float(raw_b31)
        except (ValueError, TypeError):
            return None, features_dict, f"Invalid bright_t31 value: {raw_b31}"
        features_dict["bright_t31"] = bright_t31

        # 3. Fire Radiative Power (frp)
        raw_frp = observation.get("frp")
        if raw_frp is None or raw_frp == "":
            return None, features_dict, "Missing Fire Radiative Power (frp)"
        try:
            frp = max(float(raw_frp), 0.1)
        except (ValueError, TypeError):
            return None, features_dict, f"Invalid frp value: {raw_frp}"
        features_dict["frp"] = frp

        # Coordinates for spatial & weather enrichment
        raw_lat = observation.get("latitude")
        raw_lon = observation.get("longitude")
        if raw_lat is None or raw_lon is None:
            return None, features_dict, "Missing latitude or longitude coordinates"
        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
        except (ValueError, TypeError):
            return None, features_dict, f"Invalid coordinates: lat={raw_lat}, lon={raw_lon}"

        # 4–8. Spatial Cell Aggregations (0.1° grid)
        cell_key = self._get_cell_key(lat, lon)
        cell_obs: List[Dict[str, Any]] = []

        if spatial_context:
            for obs in spatial_context:
                try:
                    o_lat = float(obs.get("latitude", 0))
                    o_lon = float(obs.get("longitude", 0))
                    if self._get_cell_key(o_lat, o_lon) == cell_key:
                        cell_obs.append(obs)
                except (ValueError, TypeError):
                    continue

        if not cell_obs:
            # Self-contained observation fallback
            detections_same_cell = 1.0
            active_days_same_cell = 1.0
            mean_frp_same_cell = frp
            max_frp_same_cell = frp
            frp_vs_local_mean = 0.0  # frp - mean_frp
        else:
            detections_same_cell = float(len(cell_obs))
            dates = {obs.get("acq_date") for obs in cell_obs if obs.get("acq_date")}
            active_days_same_cell = float(max(len(dates), 1))

            cell_frps = []
            for obs in cell_obs:
                try:
                    f_val = float(obs.get("frp", 0))
                    cell_frps.append(f_val)
                except (ValueError, TypeError):
                    pass

            if cell_frps:
                mean_frp_same_cell = round(statistics.mean(cell_frps), 4)
                max_frp_same_cell = round(max(cell_frps), 4)
            else:
                mean_frp_same_cell = frp
                max_frp_same_cell = frp

            frp_vs_local_mean = round(frp - mean_frp_same_cell, 4)

        features_dict["detections_same_cell"] = detections_same_cell
        features_dict["active_days_same_cell"] = active_days_same_cell
        features_dict["mean_frp_same_cell"] = mean_frp_same_cell
        features_dict["max_frp_same_cell"] = max_frp_same_cell
        features_dict["frp_vs_local_mean"] = frp_vs_local_mean

        # 9–13. Atmospheric Weather Features (from weather_service)
        if weather is None:
            weather = get_weather_for_location(lat, lon)

        if not weather or not weather.get("available", False):
            return None, features_dict, f"Real atmospheric weather data unavailable for location ({lat}, {lon})"

        weather_reqs = ["temperature_c", "u10", "v10", "wind_speed_mps", "precipitation_mm"]
        for w_feat in weather_reqs:
            w_val = weather.get(w_feat)
            if w_val is None:
                return None, features_dict, f"Weather feature '{w_feat}' is unavailable"
            try:
                features_dict[w_feat] = float(w_val)
            except (ValueError, TypeError):
                return None, features_dict, f"Invalid value for weather feature '{w_feat}': {w_val}"

        # 14–25. Expanded Features (exact model specifications)
        # 14. brightness_t31_delta
        features_dict["brightness_t31_delta"] = round(brightness - bright_t31, 4)

        # 15. log_frp
        features_dict["log_frp"] = round(math.log1p(max(frp, 0.0)), 4)

        # 16. detections_per_active_day
        features_dict["detections_per_active_day"] = round(
            detections_same_cell / max(active_days_same_cell, 1.0), 4
        )

        # 17. frp_max_minus_mean
        features_dict["frp_max_minus_mean"] = round(max_frp_same_cell - mean_frp_same_cell, 4)

        # 18. acq_hour (0-23)
        raw_time = observation.get("acq_time")
        if raw_time is not None and str(raw_time).strip() != "":
            time_digits = "".join(c for c in str(raw_time) if c.isdigit()).zfill(4)
            acq_hour = float(int(time_digits[:2]))
        else:
            acq_hour = 12.0
        features_dict["acq_hour"] = acq_hour

        # 19. month (1-12)
        raw_date = observation.get("acq_date")
        if raw_date and "-" in str(raw_date):
            parts = str(raw_date).split("-")
            try:
                month = float(int(parts[1]))
            except (IndexError, ValueError):
                month = 9.0
        else:
            month = 9.0
        features_dict["month"] = month

        # 20. hour_sin
        features_dict["hour_sin"] = round(math.sin(2.0 * math.pi * acq_hour / 24.0), 6)

        # 21. hour_cos
        features_dict["hour_cos"] = round(math.cos(2.0 * math.pi * acq_hour / 24.0), 6)

        # 22. month_sin
        features_dict["month_sin"] = round(math.sin(2.0 * math.pi * (month - 1.0) / 12.0), 6)

        # 23. month_cos
        features_dict["month_cos"] = round(math.cos(2.0 * math.pi * (month - 1.0) / 12.0), 6)

        # 24. is_day (1.0 for day, 0.0 for night)
        raw_dn = str(observation.get("daynight", "D")).upper().strip()
        features_dict["is_day"] = 1.0 if raw_dn in ("D", "DAY", "1") else 0.0

        # 25. sensor_source_encoded (0=NOAA20, 1=SNPP, 2=UNKNOWN)
        sat = str(
            observation.get("satellite")
            or observation.get("sensor")
            or observation.get("source")
            or ""
        ).upper().strip()
        norm_sat = re.sub(r"[^A-Z0-9]", "", sat)
        if (
            sat in {"N20", "NOAA20", "NOAA-20", "J1", "JPSS-1", "JPSS1", "N"}
            or norm_sat in {"N20", "NOAA20", "J1", "JPSS1"}
        ):
            sensor_code = 0.0
        elif (
            sat in {"SNPP", "NPP", "S-NPP", "SUOMI", "SUOMI-NPP", "SUOMINPP"}
            or norm_sat in {"SNPP", "NPP", "SUOMI", "SUOMINPP"}
        ):
            sensor_code = 1.0
        else:
            sensor_code = 2.0
        features_dict["sensor_source_encoded"] = sensor_code

        # Construct vector strictly adhering to expected order
        vector = [features_dict[feat] for feat in self._feature_names]
        return vector, features_dict, None

    def predict_observation(
        self,
        observation: Dict[str, Any],
        spatial_context: Optional[List[Dict[str, Any]]] = None,
        weather: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Runs model inference on an individual FIRMS thermal observation.
        """
        if not self.is_ready():
            return {
                "status": "unavailable",
                "reason": self._load_error or "ML model is not loaded",
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": None
            }

        vector, features_dict, error_reason = self.extract_features(
            observation=observation,
            spatial_context=spatial_context,
            weather=weather
        )

        if vector is None or error_reason is not None:
            return {
                "status": "unavailable",
                "reason": error_reason,
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": features_dict
            }

        try:
            # Predict using DataFrame with feature column names to avoid warnings
            df_input = pd.DataFrame([vector], columns=self._feature_names)
            pred_class = self._model.predict(df_input)[0]
            proba_arr = self._model.predict_proba(df_input)[0]

            prob_dict = {
                cls_name: round(float(prob), 4)
                for cls_name, prob in zip(self._classes, proba_arr)
            }
            confidence = round(float(max(proba_arr)), 4)

            return {
                "status": "ready",
                "predicted_class": str(pred_class),
                "confidence": confidence,
                "probabilities": prob_dict,
                "features_used": features_dict
            }
        except Exception as e:
            logger.error(f"[ML_MODEL] Inference exception: {e}")
            return {
                "status": "unavailable",
                "reason": f"Inference execution failed: {str(e)}",
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": features_dict
            }

    def predict_event(
        self,
        event: Dict[str, Any],
        all_observations: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Runs ML inference on a persistent thermal event by evaluating its peak
        thermal intensity observation (highest FRP) with surrounding event context.
        """
        observations = event.get("observations") or []
        context = all_observations or observations

        if not observations:
            # Synthesize representative observation from centroid if direct observations absent
            centroid = event.get("centroid", {})
            lat = centroid.get("latitude")
            lon = centroid.get("longitude")
            b_summary = event.get("brightness_summary", {})
            frp_summary = event.get("frp_summary", {})

            rep_obs = {
                "latitude": lat,
                "longitude": lon,
                "brightness": b_summary.get("max") or b_summary.get("mean"),
                "bright_t31": b_summary.get("mean"),  # fallback
                "bright_ti5": b_summary.get("mean"),
                "frp": frp_summary.get("max") or frp_summary.get("mean", 1.0),
                "acq_date": event.get("last_detected"),
                "acq_time": "1200",
                "daynight": "D",
                "satellite": "N20"
            }
            return self.predict_observation(rep_obs, spatial_context=context)

        # Select peak FRP observation as primary representative observation
        peak_obs = max(observations, key=lambda o: float(o.get("frp", 0) or 0))
        return self.predict_observation(peak_obs, spatial_context=context)


# Global singleton instance
ml_model_service = MLModelService()
