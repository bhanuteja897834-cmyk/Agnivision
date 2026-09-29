"""
AGNIVISION-GIS: Trained Random Forest ML Inference Service
Integrates the pre-trained Random Forest Classifiers for thermal event / observation classification:
  - V1 Production Model (25 features, legacy fallback): Agricultural, Forest, Industrial
  - V2 Validated Candidate B Model (28 features, enhanced): AGRICULTURAL_FIRE, FOREST_FIRE, GAS_FLARE, INDUSTRIAL_FIRE

Features required for V2 (exact 28 features in exact order):
 1. brightness: FIRMS thermal brightness (brightness or bright_ti4)
 2. bright_t31: actual FIRMS thermal-temperature channel (bright_t31 or bright_ti5)
 3. frp: FIRMS Fire Radiative Power (MW)
 4. detections_same_cell: count of thermal detections within the 0.1° (~11 km) grid cell
 5. active_days_same_cell: distinct observation acquisition dates within the same grid cell
 6. mean_frp_same_cell: mean Fire Radiative Power within the same grid cell
 7. max_frp_same_cell: peak Fire Radiative Power within the same grid cell
 8. frp_vs_local_mean: difference of observation FRP to local cell mean (frp - mean_frp_same_cell)
 9. temperature_c: 2m air temperature (°C) from real NWP weather (Open-Meteo)
10. u10: 10m eastward wind vector component (m/s)
11. v10: 10m northward wind vector component (m/s)
12. wind_speed_mps: 10m wind speed (m/s)
13. precipitation_mm: precipitation (mm)
14. brightness_t31_delta: brightness - bright_t31
15. log_frp: log1p(max(frp, 0))
16. detections_per_active_day: detections / max(active_days, 1)
17. frp_max_minus_mean: max_frp - mean_frp
18. acq_hour: acquisition hour (0-23)
19. month: acquisition month (1-12)
20. hour_sin: sin(2*pi*hour/24)
21. hour_cos: cos(2*pi*hour/24)
22. month_sin: sin(2*pi*(month-1)/12)
23. month_cos: cos(2*pi*(month-1)/12)
24. is_day: 1.0 for Day, 0.0 for Night
25. sensor_source_encoded: 0=NOAA20, 1=SNPP, 2=UNKNOWN
26. dist_worldbank_km: nearest distance to World Bank gas flare inventory site (km)
27. dist_gem_km: nearest distance to GEM Global Oil and Gas Tracker plant (km)
28. dist_osm_km: nearest distance to OpenStreetMap industrial facility (km)
"""

import sys
import types
import os
import math
import re
import logging
import statistics
import io
import zipfile
from typing import Dict, Any, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Windows Smart App Control Compatibility Shims
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

import joblib
import numpy as np
import pandas as pd
import sklearn

from weather_service import get_weather_for_location
from ml_context import context_registry_manager

logger = logging.getLogger("agnivision.ml_model")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_VERSION_V1 = "v1_25feature_production"
MODEL_VERSION_V2 = "v2_28feature_candidate_b"
MODEL_VERSION_V3 = "v3_28feature_6class"

# V1 Production model paths
MODEL_ZIP_PATH = os.path.join(BASE_DIR, "data", "new_dataset", "AGNIVISION_final_model.zip")
MODEL_CANDIDATE_PATHS_V1 = [
    MODEL_ZIP_PATH,
    os.path.join(BASE_DIR, "data", "models", "agnivision_fire_classifier_final.pkl"),
    os.path.join(BASE_DIR, "data", "model", "agnivision_fire_classifier_final.pkl"),
    os.path.join(BASE_DIR, "models", "agnivision_fire_classifier_final.pkl"),
]

# V2 Candidate B model paths
MODEL_CANDIDATE_PATHS_V2 = [
    os.path.join(BASE_DIR, "data", "models", "Candidate_B_28Features_BalancedSubsample.joblib"),
    os.path.join(BASE_DIR, "data", "ml_training_v2", "models", "Candidate_B_28Features_BalancedSubsample.joblib"),
]

# V3 Candidate model paths (6-class true classifier)
MODEL_CANDIDATE_PATHS_V3 = [
    os.path.join(BASE_DIR, "data", "models", "Candidate_V3_D_Hierarchical_Bundle.joblib"),
    os.path.join(BASE_DIR, "data", "ml_training_v3", "models", "Candidate_V3_D_Hierarchical_Bundle.joblib"),
    os.path.join(BASE_DIR, "data", "models", "Candidate_V3_6Classes_28Features.joblib"),
    os.path.join(BASE_DIR, "data", "ml_training_v3", "models", "Candidate_V3_6Classes_28Features.joblib"),
]

# 25-feature schema (Legacy V1)
EXPECTED_FEATURES_V1 = [
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
# For 100% backward compatibility with existing tests and modules
EXPECTED_FEATURES = EXPECTED_FEATURES_V1

# 28-feature schema (Candidate B V2 & Candidate V3)
EXPECTED_FEATURES_V2 = list(EXPECTED_FEATURES_V1) + [
    "dist_worldbank_km",
    "dist_gem_km",
    "dist_osm_km"
]
EXPECTED_FEATURES_V3 = list(EXPECTED_FEATURES_V2)

TARGET_CLASSES_V2 = [
    "AGRICULTURAL_FIRE",
    "FOREST_FIRE",
    "GAS_FLARE",
    "INDUSTRIAL_FIRE"
]

TARGET_CLASSES_V3 = [
    "AGRICULTURAL_FIRE",
    "FOREST_FIRE",
    "GAS_FLARE",
    "INDUSTRIAL_FIRE",
    "OTHER_THERMAL_EVENT",
    "UNKNOWN"
]

GRID_CELL_DEG = 0.1


def validate_feature_vector(
    vector: Any,
    expected_features: List[str]
) -> Tuple[bool, Optional[str]]:
    """
    Rigorously validates a feature vector before inference:
      - Checks exact sequence length
      - Validates all values are numeric floats/ints
      - Checks for NaN or Infinite values
    Returns: (is_valid, error_reason)
    """
    if not isinstance(vector, (list, tuple, np.ndarray)):
        return False, f"Feature vector must be a list, tuple, or numpy array, got {type(vector).__name__}"

    if len(vector) != len(expected_features):
        return False, f"Feature count mismatch: expected {len(expected_features)}, got {len(vector)}"

    for idx, (val, feat_name) in enumerate(zip(vector, expected_features)):
        if val is None:
            return False, f"Feature '{feat_name}' at index {idx} is None"
        try:
            num_val = float(val)
        except (TypeError, ValueError):
            return False, f"Feature '{feat_name}' at index {idx} is not numeric: {val}"
        if not math.isfinite(num_val):
            return False, f"Feature '{feat_name}' at index {idx} contains non-finite value (NaN or Inf): {val}"

    return True, None


class MLModelService:
    """
    Manages loading, feature extraction, and dual-model inference for:
      - V1: 25-feature production model (AGNIVISION_final_model.zip)
      - V2: 28-feature validated Candidate B model (Candidate_B_28Features_BalancedSubsample.joblib)
    """

    def __init__(self):
        # V1 Production Model
        self._v1_model = None
        self._v1_model_path: Optional[str] = None
        self._v1_feature_names: List[str] = list(EXPECTED_FEATURES_V1)
        self._v1_classes: List[str] = []
        self._v1_n_estimators: Optional[int] = None
        self._v1_is_loaded = False
        self._v1_load_error: Optional[str] = None

        # V2 Candidate B Model
        self._v2_model = None
        self._v2_model_path: Optional[str] = None
        self._v2_feature_names: List[str] = list(EXPECTED_FEATURES_V2)
        self._v2_classes: List[str] = []
        self._v2_n_estimators: Optional[int] = None
        self._v2_is_loaded = False
        self._v2_load_error: Optional[str] = None

        # V3 Candidate Model (6-class true classifier)
        self._v3_model = None
        self._v3_model_path: Optional[str] = None
        self._v3_feature_names: List[str] = list(EXPECTED_FEATURES_V2)
        self._v3_classes: List[str] = []
        self._v3_n_estimators: Optional[int] = None
        self._v3_is_loaded = False
        self._v3_load_error: Optional[str] = None

        self._sklearn_version: str = sklearn.__version__
        self._default_model_version: str = os.getenv("AGNIVISION_DEFAULT_MODEL_VERSION", MODEL_VERSION_V1)

        # Load models on instantiation
        self.load_model()

    @property
    def default_model_version(self) -> str:
        return self._default_model_version

    @default_model_version.setter
    def default_model_version(self, version: str):
        if version in (MODEL_VERSION_V1, MODEL_VERSION_V2, MODEL_VERSION_V3, "v1", "v2", "v3"):
            if version in ("v3", MODEL_VERSION_V3):
                self._default_model_version = MODEL_VERSION_V3
            elif version in ("v2", MODEL_VERSION_V2):
                self._default_model_version = MODEL_VERSION_V2
            else:
                self._default_model_version = MODEL_VERSION_V1

    def load_model(self) -> bool:
        """Loads V1, V2, and V3 models into memory."""
        v1_ok = self._load_v1_model()
        v2_ok = self._load_v2_model()
        v3_ok = self._load_v3_model()
        return v1_ok or v2_ok or v3_ok

    def _load_v1_model(self) -> bool:
        """Safely loads V1 production model without modifying AGNIVISION_final_model.zip."""
        if self._v1_is_loaded and self._v1_model is not None:
            return True

        if os.path.exists(MODEL_ZIP_PATH):
            self._v1_model_path = MODEL_ZIP_PATH
            try:
                logger.info(f"[ML_MODEL] Loading V1 production model from ZIP: {MODEL_ZIP_PATH}...")
                with zipfile.ZipFile(MODEL_ZIP_PATH, "r") as z:
                    pkl_name = "agnivision_fire_classifier_final.pkl"
                    if pkl_name in z.namelist():
                        model_bytes = z.read(pkl_name)
                        model = joblib.load(io.BytesIO(model_bytes))
                    else:
                        raise FileNotFoundError(f"{pkl_name} not found inside {MODEL_ZIP_PATH}")

                    feat_name = "agnivision_fire_classifier_final_features.pkl"
                    if feat_name in z.namelist():
                        feat_bytes = z.read(feat_name)
                        self._v1_feature_names = list(joblib.load(io.BytesIO(feat_bytes)))

                if hasattr(model, "verbose"):
                    model.verbose = 0
                if hasattr(model, "n_jobs"):
                    model.n_jobs = 1

                self._v1_model = model
                self._v1_classes = list(getattr(model, "classes_", []))
                self._v1_n_estimators = getattr(model, "n_estimators", None)
                self._v1_is_loaded = True
                self._v1_load_error = None

                logger.info(
                    f"[ML_MODEL] V1 production model loaded successfully: "
                    f"classes={self._v1_classes}, feature_count={len(self._v1_feature_names)}"
                )
                return True
            except Exception as e:
                self._v1_load_error = f"Exception loading V1 model from ZIP: {str(e)}"
                logger.error(f"[ML_MODEL] {self._v1_load_error}")
                self._v1_model = None
                self._v1_is_loaded = False

        # Fallback to loose candidate files for V1
        for path in MODEL_CANDIDATE_PATHS_V1[1:]:
            if os.path.exists(path):
                try:
                    logger.info(f"[ML_MODEL] Loading V1 production model from {path}...")
                    model = joblib.load(path)
                    if hasattr(model, "verbose"):
                        model.verbose = 0
                    if hasattr(model, "n_jobs"):
                        model.n_jobs = 1
                    self._v1_model = model
                    self._v1_model_path = path
                    self._v1_classes = list(getattr(model, "classes_", []))
                    self._v1_n_estimators = getattr(model, "n_estimators", None)
                    self._v1_is_loaded = True
                    self._v1_load_error = None
                    return True
                except Exception as e:
                    logger.warning(f"[ML_MODEL] Failed loading V1 from {path}: {e}")

        return False

    def _load_v2_model(self) -> bool:
        """Loads V2 Candidate B (28 features) model from disk."""
        if self._v2_is_loaded and self._v2_model is not None:
            return True

        for path in MODEL_CANDIDATE_PATHS_V2:
            if os.path.exists(path):
                self._v2_model_path = path
                try:
                    logger.info(f"[ML_MODEL] Loading V2 Candidate B model from {path}...")
                    model = joblib.load(path)
                    if hasattr(model, "verbose"):
                        model.verbose = 0
                    if hasattr(model, "n_jobs"):
                        model.n_jobs = 1

                    self._v2_model = model
                    raw_classes = list(getattr(model, "classes_", []))
                    if raw_classes and isinstance(raw_classes[0], (int, np.integer)):
                        class_names = ["AGRICULTURAL_FIRE", "FOREST_FIRE", "GAS_FLARE", "INDUSTRIAL_FIRE"]
                        self._v2_classes = class_names
                        self._v2_class_mapping = {int(c): class_names[int(c)] if int(c) < len(class_names) else str(c) for c in raw_classes}
                    else:
                        self._v2_classes = [str(c) for c in raw_classes]
                        self._v2_class_mapping = {c: str(c) for c in raw_classes}

                    self._v2_n_estimators = getattr(model, "n_estimators", None)
                    feature_names = getattr(model, "feature_names_in_", None)
                    if feature_names is not None:
                        self._v2_feature_names = list(feature_names)
                    else:
                        self._v2_feature_names = list(EXPECTED_FEATURES_V2)

                    self._v2_is_loaded = True
                    self._v2_load_error = None

                    logger.info(
                        f"[ML_MODEL] V2 Candidate B model loaded successfully: "
                        f"classes={self._v2_classes}, feature_count={len(self._v2_feature_names)}"
                    )
                    return True
                except Exception as e:
                    self._v2_load_error = f"Exception loading V2 model from {path}: {str(e)}"
                    logger.error(f"[ML_MODEL] {self._v2_load_error}")
                    self._v2_model = None
                    self._v2_is_loaded = False

        self._v2_load_error = f"V2 model artifact not found in candidate paths: {MODEL_CANDIDATE_PATHS_V2}"
        logger.warning(f"[ML_MODEL] {self._v2_load_error}")
        return False

    def _load_v3_model(self) -> bool:
        """Loads V3 6-class (28 features) model from disk."""
        if self._v3_is_loaded and self._v3_model is not None:
            return True

        for path in MODEL_CANDIDATE_PATHS_V3:
            if os.path.exists(path):
                self._v3_model_path = path
                try:
                    logger.info(f"[ML_MODEL] Loading V3 6-class model from {path}...")
                    model = joblib.load(path)
                    if hasattr(model, "verbose"):
                        model.verbose = 0
                    if hasattr(model, "n_jobs"):
                        model.n_jobs = 1

                    self._v3_model = model
                    if isinstance(model, dict) and "stage1" in model:
                        self._v3_is_hierarchical = True
                        self._v3_classes = list(TARGET_CLASSES_V3)
                        self._v3_n_estimators = 700
                        self._v3_feature_names = list(EXPECTED_FEATURES_V3)
                        self._v3_is_loaded = True
                        self._v3_load_error = None
                        logger.info(
                            f"[ML_MODEL] V3 Hierarchical 2-stage model bundle loaded successfully from {path}: "
                            f"classes={self._v3_classes}, feature_count={len(self._v3_feature_names)}"
                        )
                        return True

                    self._v3_is_hierarchical = False
                    raw_classes = list(getattr(model, "classes_", []))
                    class_names_v3 = [
                        "AGRICULTURAL_FIRE",
                        "FOREST_FIRE",
                        "GAS_FLARE",
                        "INDUSTRIAL_FIRE",
                        "OTHER_THERMAL_EVENT",
                        "UNKNOWN"
                    ]
                    if raw_classes and isinstance(raw_classes[0], (int, np.integer)):
                        self._v3_classes = class_names_v3
                        self._v3_class_mapping = {int(c): class_names_v3[int(c)] if int(c) < len(class_names_v3) else str(c) for c in raw_classes}
                    else:
                        self._v3_classes = [str(c) for c in raw_classes]
                        self._v3_class_mapping = {c: str(c) for c in raw_classes}

                    self._v3_n_estimators = getattr(model, "n_estimators", None)
                    feature_names = getattr(model, "feature_names_in_", None)
                    if feature_names is not None:
                        self._v3_feature_names = list(feature_names)
                    else:
                        self._v3_feature_names = list(EXPECTED_FEATURES_V2)

                    self._v3_is_loaded = True
                    self._v3_load_error = None

                    logger.info(
                        f"[ML_MODEL] V3 6-class model loaded successfully: "
                        f"classes={self._v3_classes}, feature_count={len(self._v3_feature_names)}"
                    )
                    return True
                except Exception as e:
                    self._v3_load_error = f"Exception loading V3 model from {path}: {str(e)}"
                    logger.error(f"[ML_MODEL] {self._v3_load_error}")
                    self._v3_model = None
                    self._v3_is_loaded = False

        self._v3_load_error = f"V3 model artifact not found in candidate paths: {MODEL_CANDIDATE_PATHS_V3}"
        logger.info(f"[ML_MODEL] {self._v3_load_error}")
        return False

    def is_ready(self, version: Optional[str] = None) -> bool:
        norm_v = self._normalize_version(version)
        if norm_v == MODEL_VERSION_V3:
            return self._v3_is_loaded and self._v3_model is not None
        if norm_v == MODEL_VERSION_V2:
            return self._v2_is_loaded and self._v2_model is not None
        return self._v1_is_loaded and self._v1_model is not None

    def _normalize_version(self, version: Optional[str]) -> str:
        if not version:
            return self._default_model_version
        v_str = str(version).strip().lower()
        if v_str in ("v3", "candidate_v3", "6class", MODEL_VERSION_V3.lower()):
            return MODEL_VERSION_V3
        if v_str in ("v2", "candidate_b", MODEL_VERSION_V2.lower()):
            return MODEL_VERSION_V2
        return MODEL_VERSION_V1

    def get_model_metadata(self, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns metadata about the ML model service.
        If version is 'v3' or 'v3_28feature_6class', returns V3 metadata.
        If version is 'v2' or 'v2_28feature_candidate_b', returns V2 metadata.
        Otherwise returns V1 metadata for 100% backward-compatibility with existing tests.
        """
        norm_v = self._normalize_version(version)

        if norm_v == MODEL_VERSION_V3:
            return {
                "is_loaded": self._v3_is_loaded,
                "model_version": MODEL_VERSION_V3,
                "model_path": self._v3_model_path,
                "model_type": "HierarchicalRandomForestClassifier" if getattr(self, "_v3_is_hierarchical", False) else (type(self._v3_model).__name__ if self._v3_model else None),
                "sklearn_version": self._sklearn_version,
                "n_estimators": self._v3_n_estimators,
                "classes": self._v3_classes,
                "expected_features": self._v3_feature_names,
                "feature_count": len(self._v3_feature_names),
                "context_registry_status": context_registry_manager.get_status(),
                "error": self._v3_load_error
            }

        if norm_v == MODEL_VERSION_V2:
            return {
                "is_loaded": self._v2_is_loaded,
                "model_version": MODEL_VERSION_V2,
                "model_path": self._v2_model_path,
                "model_type": type(self._v2_model).__name__ if self._v2_model else None,
                "sklearn_version": self._sklearn_version,
                "n_estimators": self._v2_n_estimators,
                "classes": self._v2_classes,
                "expected_features": self._v2_feature_names,
                "feature_count": len(self._v2_feature_names),
                "context_registry_status": context_registry_manager.get_status(),
                "error": self._v2_load_error
            }

        # V1 metadata (Preserves exact schema for test_01 and test_08)
        return {
            "is_loaded": self._v1_is_loaded,
            "model_version": MODEL_VERSION_V1,
            "model_path": self._v1_model_path,
            "model_type": type(self._v1_model).__name__ if self._v1_model else None,
            "sklearn_version": self._sklearn_version,
            "n_estimators": self._v1_n_estimators,
            "classes": self._v1_classes,
            "expected_features": self._v1_feature_names,
            "feature_count": len(self._v1_feature_names),
            "error": self._v1_load_error,
            "v2_candidate_available": self._v2_is_loaded,
            "v2_model_version": MODEL_VERSION_V2 if self._v2_is_loaded else None
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
        weather: Optional[Dict[str, Any]] = None,
        version: str = "v1"
    ) -> Tuple[Optional[List[float]], Optional[Dict[str, Any]], Optional[str]]:
        """
        Extracts features from an observation dictionary:
          - version='v1': 25 features (legacy production)
          - version='v2': 28 features (Candidate B enhanced with context distances)
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

        # Coordinates for spatial, weather & context distance enrichment
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
            detections_same_cell = 1.0
            active_days_same_cell = 1.0
            mean_frp_same_cell = frp
            max_frp_same_cell = frp
            frp_vs_local_mean = 0.0
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

        # 9–13. Atmospheric Weather Features (Open-Meteo)
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

        # 14–25. Expanded Physical & Temporal Features
        features_dict["brightness_t31_delta"] = round(brightness - bright_t31, 4)
        features_dict["log_frp"] = round(math.log1p(max(frp, 0.0)), 4)
        features_dict["detections_per_active_day"] = round(
            detections_same_cell / max(active_days_same_cell, 1.0), 4
        )
        features_dict["frp_max_minus_mean"] = round(max_frp_same_cell - mean_frp_same_cell, 4)

        raw_time = observation.get("acq_time")
        if raw_time is not None and str(raw_time).strip() != "":
            time_digits = "".join(c for c in str(raw_time) if c.isdigit()).zfill(4)
            acq_hour = float(int(time_digits[:2]))
        else:
            acq_hour = 12.0
        features_dict["acq_hour"] = acq_hour

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

        features_dict["hour_sin"] = round(math.sin(2.0 * math.pi * acq_hour / 24.0), 6)
        features_dict["hour_cos"] = round(math.cos(2.0 * math.pi * acq_hour / 24.0), 6)
        features_dict["month_sin"] = round(math.sin(2.0 * math.pi * (month - 1.0) / 12.0), 6)
        features_dict["month_cos"] = round(math.cos(2.0 * math.pi * (month - 1.0) / 12.0), 6)

        raw_dn = str(observation.get("daynight", "D")).upper().strip()
        features_dict["is_day"] = 1.0 if raw_dn in ("D", "DAY", "1") else 0.0

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

        norm_ver = self._normalize_version(version)
        if norm_ver in (MODEL_VERSION_V2, MODEL_VERSION_V3):
            # 26–28. Context Distances (from static geospatial registry)
            d_wb, d_gem, d_osm, dist_err = context_registry_manager.compute_distances(lat, lon)
            if dist_err is not None:
                return None, features_dict, f"Failed computing context distances: {dist_err}"

            features_dict["dist_worldbank_km"] = d_wb
            features_dict["dist_gem_km"] = d_gem
            features_dict["dist_osm_km"] = d_osm
            expected_feats = EXPECTED_FEATURES_V3 if norm_ver == MODEL_VERSION_V3 else EXPECTED_FEATURES_V2
        else:
            expected_feats = EXPECTED_FEATURES_V1

        # Construct vector strictly adhering to expected order
        vector = [features_dict[feat] for feat in expected_feats]
        return vector, features_dict, None

    def extract_28_features(
        self,
        observation: Dict[str, Any],
        spatial_context: Optional[List[Dict[str, Any]]] = None,
        weather: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[List[float]], Optional[Dict[str, Any]], Optional[str]]:
        """Convenience method for extracting V2 28-feature schema."""
        return self.extract_features(
            observation=observation,
            spatial_context=spatial_context,
            weather=weather,
            version="v2"
        )

    def predict_observation(
        self,
        observation: Union[Dict[str, Any], List[float], np.ndarray],
        spatial_context: Optional[List[Dict[str, Any]]] = None,
        weather: Optional[Dict[str, Any]] = None,
        model_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Runs model inference on an observation dict or raw feature vector.
        Explicit routing & fallback:
          - 28 features $\to$ Candidate B V2 model
          - 25 features $\to$ Legacy V1 production model
          - If V2 requested but unavailable $\to$ gracefully falls back to V1 model.
        """
        # Determine target model version
        norm_v = self._normalize_version(model_version)
        fallback_used = False

        # Direct raw feature vector input
        if isinstance(observation, (list, tuple, np.ndarray)):
            vector = list(observation)
            v_len = len(vector)
            if v_len == 28:
                target_version = MODEL_VERSION_V3 if norm_v == MODEL_VERSION_V3 else MODEL_VERSION_V2
                expected_feats = self._v3_feature_names if target_version == MODEL_VERSION_V3 else self._v2_feature_names
            elif v_len == 25:
                target_version = MODEL_VERSION_V1
                expected_feats = self._v1_feature_names
            else:
                return {
                    "status": "unavailable",
                    "reason": f"Invalid feature vector length: {v_len}. Must be exactly 25 or 28 features.",
                    "predicted_class": None,
                    "confidence": None,
                    "probabilities": None,
                    "features_used": None,
                    "model_version": None
                }
            features_dict = {f: v for f, v in zip(expected_feats, vector)}
        else:
            # Observation dictionary input
            target_version = norm_v
            # If target V3 or V2 requested but not ready, check fallback
            if target_version == MODEL_VERSION_V3 and not self.is_ready(MODEL_VERSION_V3):
                if self.is_ready(MODEL_VERSION_V2):
                    logger.warning("[ML_MODEL] V3 model requested but not loaded. Falling back to V2 model.")
                    target_version = MODEL_VERSION_V2
                    fallback_used = True
                elif self.is_ready(MODEL_VERSION_V1):
                    logger.warning("[ML_MODEL] V3 model requested but not loaded. Falling back to V1 production model.")
                    target_version = MODEL_VERSION_V1
                    fallback_used = True
                else:
                    return {
                        "status": "unavailable",
                        "reason": self._v3_load_error or "V3 ML model is not loaded",
                        "predicted_class": None,
                        "confidence": None,
                        "probabilities": None,
                        "features_used": None,
                        "model_version": MODEL_VERSION_V3
                    }
            elif target_version == MODEL_VERSION_V2 and not self.is_ready(MODEL_VERSION_V2):
                if self.is_ready(MODEL_VERSION_V1):
                    logger.warning("[ML_MODEL] V2 model requested but not loaded. Falling back to V1 production model.")
                    target_version = MODEL_VERSION_V1
                    fallback_used = True
                else:
                    return {
                        "status": "unavailable",
                        "reason": self._v2_load_error or "V2 ML model is not loaded",
                        "predicted_class": None,
                        "confidence": None,
                        "probabilities": None,
                        "features_used": None,
                        "model_version": MODEL_VERSION_V2
                    }

            ver_arg = "v2" if target_version in (MODEL_VERSION_V2, MODEL_VERSION_V3) else "v1"
            vector, features_dict, error_reason = self.extract_features(
                observation=observation,
                spatial_context=spatial_context,
                weather=weather,
                version=ver_arg
            )

            if vector is None or error_reason is not None:
                return {
                    "status": "unavailable",
                    "reason": error_reason,
                    "predicted_class": None,
                    "confidence": None,
                    "probabilities": None,
                    "features_used": features_dict,
                    "model_version": target_version
                }

        # Select model and metadata according to target version
        if target_version == MODEL_VERSION_V3:
            model = self._v3_model
            classes = self._v3_classes
            feature_names = self._v3_feature_names
            schema_version = "28_features_v3"
        elif target_version == MODEL_VERSION_V2:
            model = self._v2_model
            classes = self._v2_classes
            feature_names = self._v2_feature_names
            schema_version = "28_features_v2"
        else:
            model = self._v1_model
            classes = self._v1_classes
            feature_names = self._v1_feature_names
            schema_version = "25_features_v1"

        if model is None:
            return {
                "status": "unavailable",
                "reason": f"Selected model '{target_version}' is not loaded",
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": features_dict,
                "model_version": target_version
            }

        # Validate feature schema strictly before prediction
        is_valid, val_err = validate_feature_vector(vector, feature_names)
        if not is_valid:
            return {
                "status": "unavailable",
                "reason": f"Feature schema validation failed: {val_err}",
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": features_dict,
                "model_version": target_version
            }

        try:
            if target_version == MODEL_VERSION_V3 and getattr(self, "_v3_is_hierarchical", False) and isinstance(model, dict):
                model_input = np.asarray([vector], dtype=np.float32)
                p_s1 = model["stage1"].predict_proba(model_input)[0]
                p_s2a = model["stage2a_known"].predict_proba(model_input)[0]
                p_s2b = model["stage2b_ambig"].predict_proba(model_input)[0]
                raw_probs = {
                    "AGRICULTURAL_FIRE": float(p_s2a[0] * p_s1[0]),
                    "FOREST_FIRE": float(p_s2a[1] * p_s1[0]),
                    "GAS_FLARE": float(p_s2a[2] * p_s1[0]),
                    "INDUSTRIAL_FIRE": float(p_s2a[3] * p_s1[0]),
                    "OTHER_THERMAL_EVENT": float(p_s2b[0] * p_s1[1]),
                    "UNKNOWN": float(p_s2b[1] * p_s1[1])
                }
                total_p = sum(raw_probs.values()) or 1.0
                prob_dict = {k: round(v / total_p, 4) for k, v in raw_probs.items()}
                pred_class_str = max(prob_dict.items(), key=lambda x: x[1])[0]
                confidence = prob_dict[pred_class_str]
            else:
                if hasattr(model, "feature_names_in_") and model.feature_names_in_ is not None:
                    model_input = pd.DataFrame([vector], columns=feature_names)
                else:
                    model_input = np.asarray([vector], dtype=np.float32)

                pred_raw = model.predict(model_input)[0]
                proba_arr = model.predict_proba(model_input)[0]

                if target_version == MODEL_VERSION_V3 and hasattr(self, "_v3_class_mapping"):
                    pred_key = int(pred_raw) if isinstance(pred_raw, (int, np.integer)) else pred_raw
                    pred_class_str = self._v3_class_mapping.get(pred_key, str(pred_raw))
                    prob_dict = {}
                    raw_classes_in_model = getattr(model, "classes_", [])
                    for c_val, prob in zip(raw_classes_in_model, proba_arr):
                        c_key = int(c_val) if isinstance(c_val, (int, np.integer)) else c_val
                        lbl = self._v3_class_mapping.get(c_key, str(c_val))
                        prob_dict[lbl] = round(float(prob), 4)
                elif target_version == MODEL_VERSION_V2 and hasattr(self, "_v2_class_mapping"):
                    pred_key = int(pred_raw) if isinstance(pred_raw, (int, np.integer)) else pred_raw
                    pred_class_str = self._v2_class_mapping.get(pred_key, str(pred_raw))
                    prob_dict = {}
                    raw_classes_in_model = getattr(model, "classes_", [])
                    for c_val, prob in zip(raw_classes_in_model, proba_arr):
                        c_key = int(c_val) if isinstance(c_val, (int, np.integer)) else c_val
                        lbl = self._v2_class_mapping.get(c_key, str(c_val))
                        prob_dict[lbl] = round(float(prob), 4)
                else:
                    pred_class_str = str(pred_raw)
                    prob_dict = {
                        str(cls_name): round(float(prob), 4)
                        for cls_name, prob in zip(classes, proba_arr)
                    }

                confidence = round(float(max(proba_arr)), 4)

            response = {
                "status": "ready",
                "predicted_class": pred_class_str,
                "confidence": confidence,
                "probabilities": prob_dict,
                "features_used": features_dict,
                "model_version": target_version,
                "feature_schema_version": schema_version
            }
            if fallback_used:
                response["fallback_used"] = True
                response["fallback_reason"] = "V2 candidate model unavailable; served by V1 production model"

            return response
        except Exception as e:
            logger.error(f"[ML_MODEL] Inference execution exception: {e}")
            return {
                "status": "unavailable",
                "reason": f"Inference execution failed: {str(e)}",
                "predicted_class": None,
                "confidence": None,
                "probabilities": None,
                "features_used": features_dict,
                "model_version": target_version
            }

    def predict_event(
        self,
        event: Dict[str, Any],
        all_observations: Optional[List[Dict[str, Any]]] = None,
        model_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Runs ML inference on a persistent thermal event by evaluating its peak
        thermal intensity observation (highest FRP) with surrounding event context.
        """
        observations = event.get("observations") or []
        context = all_observations or observations

        if not observations:
            centroid = event.get("centroid", {})
            lat = centroid.get("latitude")
            lon = centroid.get("longitude")
            b_summary = event.get("brightness_summary", {})
            frp_summary = event.get("frp_summary", {})

            rep_obs = {
                "latitude": lat,
                "longitude": lon,
                "brightness": b_summary.get("max") or b_summary.get("mean"),
                "bright_t31": b_summary.get("mean"),
                "bright_ti5": b_summary.get("mean"),
                "frp": frp_summary.get("max") or frp_summary.get("mean", 1.0),
                "acq_date": event.get("last_detected"),
                "acq_time": "1200",
                "daynight": "D",
                "satellite": "N20"
            }
            return self.predict_observation(rep_obs, spatial_context=context, model_version=model_version)

        peak_obs = max(observations, key=lambda o: float(o.get("frp", 0) or 0))
        return self.predict_observation(peak_obs, spatial_context=context, model_version=model_version)


# Global singleton instance
ml_model_service = MLModelService()
