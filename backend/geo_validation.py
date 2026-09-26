"""
AGNIVISION-GIS: Geographic & Land-Cover Domain Validation Service
================================================================
Determines the geographic domain and administrative attribution for thermal observations:
- LAND
- INLAND_WATER
- COASTAL_NEAR_SHORE
- OFFSHORE_MARINE
- UNKNOWN_UNRESOLVED

DATA SOURCES & LICENSING:
-------------------------
1. NOAA GLOBE 1km Digital Elevation Model & Land-Water Mask
   - Source: NOAA National Centers for Environmental Information (NCEI)
   - URL: https://www.ngdc.noaa.gov/mgg/topo/globe.html (packaged via global-land-mask)
   - License: Public Domain (U.S. Government Work) / MIT License
   - Mode: Downloaded locally; queried 100% offline in-memory (~0.05 ms per lookup).

2. Natural Earth 50m Cultural Admin 1 (Indian States & Union Territories)
   - Source: Natural Earth Vector
   - URL: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson
   - License: Public Domain
   - Mode: Downloaded locally to backend/data/india_states.geojson; queried offline using Shapely prepared geometries.

3. Natural Earth 10m Physical Lakes & Reservoirs (Regional South Asia subset)
   - Source: Natural Earth Vector
   - URL: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson
   - License: Public Domain
   - Mode: Downloaded locally to backend/data/regional_lakes.geojson; queried offline using Shapely prepared geometries.

4. OpenStreetMap Nominatim Reverse Geocoding API
   - Source: OpenStreetMap contributors
   - URL: https://nominatim.openstreetmap.org/reverse
   - License: Open Database License (ODbL)
   - Mode: Queried remotely on-demand for specific point inspections with persistent disk cache
     (backend/geo_cache.json) to respect Nominatim's 1 request/second usage policy.
"""

import json
import logging
import math
import os
import threading
from typing import Any, Dict, Optional, Tuple

from global_land_mask import globe
import numpy as np
import requests
from shapely.geometry import Point, shape
from shapely.prepared import prep

logger = logging.getLogger("agnivision.geo")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GEO_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_cache.json")
GEO_CACHE_LOCK = threading.Lock()

# Global spatial index containers
_STATES_PREPPED = []
_LAKES_PREPPED = []
_GEO_CACHE: Dict[str, Dict[str, Any]] = {}
_INITIALIZED = False


def _init_spatial_data():
    """Load local Natural Earth GeoJSON layers into memory with Shapely spatial indexing."""
    global _STATES_PREPPED, _LAKES_PREPPED, _INITIALIZED

    if _INITIALIZED:
        return

    # 1. Load India States
    states_path = os.path.join(DATA_DIR, "india_states.geojson")
    if os.path.exists(states_path):
        try:
            with open(states_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _STATES_PREPPED = [
                (prep(shape(f["geometry"])), f["properties"].get("name"))
                for f in data.get("features", [])
            ]
            logger.info(f"[GEO] Loaded {len(_STATES_PREPPED)} state boundaries.")
        except Exception as e:
            logger.warning(f"[GEO] Could not load india_states.geojson: {e}")

    # 2. Load Regional Lakes / Reservoirs
    lakes_path = os.path.join(DATA_DIR, "regional_lakes.geojson")
    if os.path.exists(lakes_path):
        try:
            with open(lakes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _LAKES_PREPPED = [
                (prep(shape(f["geometry"])), f["properties"].get("name") or "Inland Water Body")
                for f in data.get("features", [])
            ]
            logger.info(f"[GEO] Loaded {len(_LAKES_PREPPED)} inland water bodies.")
        except Exception as e:
            logger.warning(f"[GEO] Could not load regional_lakes.geojson: {e}")

    # 3. Load Geocoding Cache
    _load_geo_cache()
    _INITIALIZED = True


def _load_geo_cache():
    """Load disk-persisted reverse geocoding cache."""
    global _GEO_CACHE
    if not os.path.exists(GEO_CACHE_FILE):
        return
    try:
        with open(GEO_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _GEO_CACHE = data
    except Exception as e:
        logger.warning(f"[GEO] Could not read geo_cache.json: {e}")


def _save_geo_cache():
    """Save disk-persisted reverse geocoding cache."""
    try:
        temp_file = GEO_CACHE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(_GEO_CACHE, f, indent=2)
        os.replace(temp_file, GEO_CACHE_FILE)
    except Exception as e:
        logger.warning(f"[GEO] Could not save geo_cache.json: {e}")


def _cache_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _query_nominatim(lat: float, lon: float) -> Dict[str, Optional[str]]:
    """Query OpenStreetMap Nominatim reverse geocoder for detailed district/city information."""
    key = _cache_key(lat, lon)

    with GEO_CACHE_LOCK:
        if key in _GEO_CACHE:
            return _GEO_CACHE[key]

    headers = {
        "User-Agent": "AGNIVISION-GIS/1.0 (academic.research.gis)",
        "Accept": "application/json"
    }
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=jsonv2"

    try:
        response = requests.get(url, headers=headers, timeout=3.5)
        if response.status_code == 200:
            data = response.json()
            addr = data.get("address", {})

            district = (
                addr.get("state_district")
                or addr.get("district")
                or addr.get("county")
            )
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("municipality")
                or addr.get("suburb")
                or addr.get("village")
            )
            state = addr.get("state")

            result = {
                "state": state,
                "district": district,
                "city": city
            }

            with GEO_CACHE_LOCK:
                _GEO_CACHE[key] = result
                _save_geo_cache()

            return result
    except Exception as e:
        logger.debug(f"[GEO] Nominatim lookup skipped for ({lat}, {lon}): {e}")

    return {}


def is_coordinate_valid(lat: Any, lon: Any) -> Tuple[bool, Optional[float], Optional[float]]:
    """Validate that coordinates are finite numbers within Earth geographic bounds."""
    try:
        plat = float(lat)
        plon = float(lon)
    except (ValueError, TypeError):
        return False, None, None

    if math.isnan(plat) or math.isinf(plat) or math.isnan(plon) or math.isinf(plon):
        return False, None, None

    if not (-90.0 <= plat <= 90.0 and -180.0 <= plon <= 180.0):
        return False, None, None

    return True, plat, plon


def validate_geographic_domain(
    latitude: Any,
    longitude: Any,
    resolve_detailed: bool = False
) -> Dict[str, Any]:
    """
    Validate and classify the geographic & land-cover domain of an observation coordinate.

    Domains:
    - LAND: Continental terrain
    - INLAND_WATER: Lakes, reservoirs, or major interior freshwater bodies
    - COASTAL_NEAR_SHORE: Intertidal or marine waters within 5 km of land
    - OFFSHORE_MARINE: Open sea / ocean waters > 5 km from land (state/district = 'Not applicable')
    - UNKNOWN_UNRESOLVED: Invalid or unresolvable coordinates

    Returns normalized geographic validation payload.
    """
    _init_spatial_data()

    valid, lat, lon = is_coordinate_valid(latitude, longitude)
    if not valid or lat is None or lon is None:
        return {
            "domain": "UNKNOWN_UNRESOLVED",
            "status": "unresolved",
            "state": None,
            "district": None,
            "city": None,
            "source": "Coordinate Validation Check",
            "confidence": None
        }

    # 1. Check planetary ocean vs continental land using NOAA GLOBE 1km mask
    try:
        is_ocean = bool(globe.is_ocean(lat, lon))
    except Exception as e:
        logger.warning(f"[GEO] GLOBE mask lookup failed for ({lat}, {lon}): {e}")
        return {
            "domain": "UNKNOWN_UNRESOLVED",
            "status": "unresolved",
            "state": None,
            "district": None,
            "city": None,
            "source": "NOAA GLOBE 1km Land-Ocean Mask",
            "confidence": None
        }

    # 2. Oceanic / Marine domain handling
    if is_ocean:
        # Check proximity to coastline (5 km distance buffer)
        lat_idx = globe.lat_to_index(lat)
        lon_idx = globe.lon_to_index(lon)
        # GLOBE resolution is ~0.00833 deg per pixel (~925m at equator)
        # Radius 6 pixels corresponds to ~5.5 km buffer
        radius_pixels = 6
        h, w = globe._mask.shape
        sub_mask = globe._mask[
            max(0, lat_idx - radius_pixels) : min(h, lat_idx + radius_pixels + 1),
            max(0, lon_idx - radius_pixels) : min(w, lon_idx + radius_pixels + 1)
        ]
        # In globe._mask, 0 = Land, 1 = Ocean
        near_land = bool(np.any(sub_mask == 0))

        if near_land:
            return {
                "domain": "COASTAL_NEAR_SHORE",
                "status": "validated",
                "state": "Not applicable",
                "district": "Not applicable",
                "city": "Not applicable",
                "source": "NOAA GLOBE 1km Land-Ocean Mask / Natural Earth",
                "confidence": None
            }
        else:
            return {
                "domain": "OFFSHORE_MARINE",
                "status": "validated",
                "state": "Not applicable",
                "district": "Not applicable",
                "city": "Not applicable",
                "source": "NOAA GLOBE 1km Land-Ocean Mask",
                "confidence": None
            }

    # 3. Check for Inland Water Bodies (Lakes & Reservoirs)
    point = Point(lon, lat)
    for lake_prep, lake_name in _LAKES_PREPPED:
        if lake_prep.contains(point):
            # Resolve State for inland water body if inside India
            matched_state = None
            for state_prep, state_name in _STATES_PREPPED:
                if state_prep.contains(point):
                    matched_state = state_name
                    break

            return {
                "domain": "INLAND_WATER",
                "status": "validated",
                "state": matched_state or "Not applicable",
                "district": None,
                "city": lake_name,
                "source": "Natural Earth 10m Lakes & Reservoirs",
                "confidence": None
            }

    # 4. Continental Land Domain: Resolve Indian State and Administrative boundaries
    matched_state = None
    for state_prep, state_name in _STATES_PREPPED:
        if state_prep.contains(point):
            matched_state = state_name
            break

    district = None
    city = None
    source = "NOAA GLOBE 1km Land Mask / Natural Earth"

    # Check local geocache first
    cached_info = _GEO_CACHE.get(_cache_key(lat, lon))
    if cached_info:
        district = cached_info.get("district")
        city = cached_info.get("city")
        if cached_info.get("state") and not matched_state:
            matched_state = cached_info["state"]
        source = "NOAA GLOBE / Natural Earth / OpenStreetMap"

    # Query remote Nominatim reverse geocode if specifically requested and not yet cached
    elif resolve_detailed:
        remote_info = _query_nominatim(lat, lon)
        if remote_info.get("district"):
            district = remote_info["district"]
        if remote_info.get("city"):
            city = remote_info["city"]
        if remote_info.get("state") and not matched_state:
            matched_state = remote_info["state"]
        if district or city:
            source = "NOAA GLOBE / Natural Earth / OpenStreetMap"

    return {
        "domain": "LAND",
        "status": "validated",
        "state": matched_state,
        "district": district,
        "city": city,
        "source": source,
        "confidence": None
    }
