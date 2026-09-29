"""
AGNIVISION-GIS: Static Spatial Context Registry Service
Computes deterministic, static geospatial nearest-neighbor distances for:
  1. dist_worldbank_km: Distance to nearest World Bank global gas flare inventory site (India subset)
  2. dist_gem_km: Distance to nearest GEM Global Oil and Gas Plant Tracker extraction/power plant
  3. dist_osm_km: Distance to nearest OpenStreetMap industrial manufacturing / chemical / energy facility

Zero forward temporal leakage: Uses ONLY pre-compiled static geospatial coordinate registries.
Zero dependency on labels, confidence, target class, or runtime predictions.
"""

import os
import math
import logging
from typing import Dict, Any, Tuple, Optional
import numpy as np
import joblib
from scipy.spatial import cKDTree

logger = logging.getLogger("agnivision.ml_context")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PRIMARY_PATH = os.path.join(BASE_DIR, "data", "ml_context_registry.joblib")
REGISTRY_FALLBACK_PATHS = [
    REGISTRY_PRIMARY_PATH,
    os.path.join(BASE_DIR, "data", "models", "ml_context_registry.joblib"),
    os.path.join(BASE_DIR, "data", "ml_training_v2", "context", "ml_context_registry.joblib"),
]


def to_km_coords_single(lat: float, lon: float) -> np.ndarray:
    """
    Equirectangular projection to km coordinates centered around India (~21°N).
    Matches the exact projection formula used in Checkpoints 3, 5, and 6.
    """
    phi0 = math.radians(21.0)
    x = lon * 111.0 * math.cos(phi0)
    y = lat * 111.0
    return np.array([[y, x]], dtype=np.float64)


class ContextRegistryManager:
    """
    Loads and serves high-speed cKDTree nearest-neighbor queries against
    static contextual registries.
    """

    def __init__(self):
        self._is_loaded = False
        self._wb_tree: Optional[cKDTree] = None
        self._gem_tree: Optional[cKDTree] = None
        self._osm_tree: Optional[cKDTree] = None
        self._counts: Dict[str, int] = {}
        self._load_error: Optional[str] = None
        self._registry_path: Optional[str] = None

        self.load_registry()

    def load_registry(self) -> bool:
        """Loads pre-compiled static context coordinate trees from disk."""
        for path in REGISTRY_FALLBACK_PATHS:
            if os.path.exists(path):
                self._registry_path = path
                break

        if not self._registry_path or not os.path.exists(self._registry_path):
            self._load_error = f"Context registry not found in candidate paths: {REGISTRY_FALLBACK_PATHS}"
            logger.warning(f"[ML_CONTEXT] {self._load_error}")
            return False

        try:
            logger.info(f"[ML_CONTEXT] Loading static context registry from {self._registry_path}...")
            data = joblib.load(self._registry_path)

            wb_coords = data.get("wb_coords_km")
            gem_coords = data.get("gem_coords_km")
            osm_coords = data.get("osm_coords_km")

            if wb_coords is None or gem_coords is None or osm_coords is None:
                raise ValueError("Registry file missing one or more required coordinate matrices")

            self._wb_tree = cKDTree(wb_coords)
            self._gem_tree = cKDTree(gem_coords)
            self._osm_tree = cKDTree(osm_coords)
            self._counts = {
                "world_bank_flare_sites": len(wb_coords),
                "gem_oil_gas_plants": len(gem_coords),
                "osm_industrial_facilities": len(osm_coords)
            }
            self._is_loaded = True
            self._load_error = None

            logger.info(
                f"[ML_CONTEXT] Context registry loaded successfully: "
                f"WB={self._counts['world_bank_flare_sites']}, "
                f"GEM={self._counts['gem_oil_gas_plants']}, "
                f"OSM={self._counts['osm_industrial_facilities']}"
            )
            return True
        except Exception as e:
            self._load_error = f"Exception loading context registry: {str(e)}"
            logger.error(f"[ML_CONTEXT] {self._load_error}")
            self._is_loaded = False
            return False

    @property
    def is_ready(self) -> bool:
        return self._is_loaded and self._wb_tree is not None

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_loaded": self._is_loaded,
            "registry_path": self._registry_path,
            "site_counts": self._counts,
            "error": self._load_error
        }

    def compute_distances(self, lat: float, lon: float) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
        """
        Computes (dist_worldbank_km, dist_gem_km, dist_osm_km) for a coordinate.
        Returns: (d_wb, d_gem, d_osm, error_reason)
        """
        if not self.is_ready:
            return None, None, None, self._load_error or "Context registry is not loaded"

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return None, None, None, f"Invalid geographic coordinates: lat={lat}, lon={lon}"

        if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
            return None, None, None, f"Non-finite coordinates: lat={lat_f}, lon={lon_f}"

        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            return None, None, None, f"Coordinates out of bounds: lat={lat_f}, lon={lon_f}"

        try:
            q = to_km_coords_single(lat_f, lon_f)
            d_wb = round(float(self._wb_tree.query(q, k=1)[0][0]), 3)
            d_gem = round(float(self._gem_tree.query(q, k=1)[0][0]), 3)
            d_osm = round(float(self._osm_tree.query(q, k=1)[0][0]), 3)
            return d_wb, d_gem, d_osm, None
        except Exception as e:
            return None, None, None, f"Error querying context KDTree: {str(e)}"


# Global singleton instance
context_registry_manager = ContextRegistryManager()
