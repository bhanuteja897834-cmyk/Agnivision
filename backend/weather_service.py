"""
AGNIVISION-GIS — Weather & Wind Ingestion Service
Retrieves real atmospheric conditions from Open-Meteo API for FIRMS thermal observations.
Extracts:
  - temperature_c (2m air temperature in °C)
  - u10 (10m eastward wind component in m/s)
  - v10 (10m northward wind component in m/s)
  - wind_speed_mps (10m wind speed in m/s)
  - precipitation_mm (precipitation in mm)
Includes in-memory TTL caching, disk persistence, and multi-location batching for high performance.
"""

import os
import json
import math
import time
import logging
import threading
from typing import Dict, Any, List, Tuple, Optional
import requests

logger = logging.getLogger("agnivision.weather")

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_CACHE_TTL_SECONDS = 3600 * 2  # 2 hours TTL
DEFAULT_TIMEOUT_SECONDS = 12
BATCH_CHUNK_SIZE = 100  # Open-Meteo supports multi-location batches up to 100 locations
GRID_PRECISION = 1  # 0.1° grid (~11 km) matching NWP atmospheric model resolution


class WeatherService:
    """
    Manages retrieval, batching, and caching of authentic Open-Meteo weather data.
    """

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self._cache: Dict[Tuple[float, float], Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.cache_file = os.path.join(os.path.dirname(__file__), "data", "weather_cache.json")
        self._load_disk_cache()

    def _load_disk_cache(self):
        """Loads cached atmospheric data from disk if available."""
        if not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            now = time.time()
            loaded = 0
            with self._lock:
                for key_str, entry in raw.items():
                    try:
                        parts = key_str.split(",")
                        grid_k = (round(float(parts[0]), GRID_PRECISION), round(float(parts[1]), GRID_PRECISION))
                        exp = entry.get("expires_at", 0)
                        if exp > now and entry.get("data", {}).get("available"):
                            self._cache[grid_k] = entry
                            loaded += 1
                    except Exception:
                        continue
            if loaded:
                logger.info(f"[WEATHER] Loaded {loaded} cached weather locations from disk.")
        except Exception as e:
            logger.warning(f"[WEATHER] Could not load disk cache: {e}")

    def _save_disk_cache(self):
        """Persists valid in-memory cache entries to disk."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            serializable = {}
            now = time.time()
            with self._lock:
                for (lat, lon), entry in self._cache.items():
                    if entry.get("expires_at", 0) > now and entry.get("data", {}).get("available"):
                        serializable[f"{lat},{lon}"] = entry
            temp_file = self.cache_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(serializable, f)
            os.replace(temp_file, self.cache_file)
        except Exception as e:
            logger.warning(f"[WEATHER] Could not persist disk cache: {e}")

    def _get_grid_key(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Rounds coordinates to standard NWP atmospheric model grid cell (0.1° ≈ 11 km).
        """
        return (round(float(lat), GRID_PRECISION), round(float(lon), GRID_PRECISION))

    def _compute_uv_components(self, wind_speed: Optional[float], wind_direction_deg: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """
        Computes standard meteorological u10 and v10 wind components from speed (m/s)
        and direction (degrees clockwise from true north).
        u10 = -speed * sin(rad) (eastward wind component)
        v10 = -speed * cos(rad) (northward wind component)
        """
        if wind_speed is None or wind_direction_deg is None:
            return None, None
        try:
            rad = math.radians(float(wind_direction_deg))
            u10 = round(-float(wind_speed) * math.sin(rad), 2)
            v10 = round(-float(wind_speed) * math.cos(rad), 2)
            return u10, v10
        except (ValueError, TypeError):
            return None, None

    def _extract_weather_payload(self, current_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extracts the five required ML atmospheric features from an Open-Meteo 'current' dictionary.
        """
        if not current_data or not isinstance(current_data, dict):
            return {
                "temperature_c": None,
                "u10": None,
                "v10": None,
                "wind_speed_mps": None,
                "precipitation_mm": None,
                "source": "Open-Meteo",
                "available": False
            }

        temp_c = current_data.get("temperature_2m")
        precip_mm = current_data.get("precipitation")
        wind_speed_mps = current_data.get("wind_speed_10m")
        wind_dir = current_data.get("wind_direction_10m")

        u10, v10 = self._compute_uv_components(wind_speed_mps, wind_dir)

        available = temp_c is not None or wind_speed_mps is not None

        return {
            "temperature_c": float(temp_c) if temp_c is not None else None,
            "u10": u10,
            "v10": v10,
            "wind_speed_mps": float(wind_speed_mps) if wind_speed_mps is not None else None,
            "precipitation_mm": float(precip_mm) if precip_mm is not None else None,
            "source": "Open-Meteo",
            "available": available
        }

    def get_weather_for_location(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """
        Retrieves real atmospheric weather data from Open-Meteo for a given latitude and longitude.
        Checks in-memory spatial cache first.
        """
        try:
            lat_f = float(latitude)
            lon_f = float(longitude)
        except (ValueError, TypeError):
            logger.warning(f"[WEATHER] Invalid coordinate inputs: lat={latitude}, lon={longitude}")
            return {
                "temperature_c": None,
                "u10": None,
                "v10": None,
                "wind_speed_mps": None,
                "precipitation_mm": None,
                "source": "Open-Meteo",
                "available": False
            }

        grid_key = self._get_grid_key(lat_f, lon_f)
        now = time.time()

        # Check cache
        with self._lock:
            entry = self._cache.get(grid_key)
            if entry and entry["expires_at"] > now and entry.get("data", {}).get("available"):
                logger.info(f"[WEATHER] Cache hit for ({grid_key[0]}, {grid_key[1]})")
                return dict(entry["data"])

        # Fetch from Open-Meteo
        logger.info(f"[WEATHER] Fetching Open-Meteo data for ({grid_key[0]}, {grid_key[1]})...")
        params = {
            "latitude": grid_key[0],
            "longitude": grid_key[1],
            "current": "temperature_2m,precipitation,wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "ms"
        }

        try:
            resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                current_data = data.get("current")
                weather_info = self._extract_weather_payload(current_data)

                # Store in cache
                with self._lock:
                    self._cache[grid_key] = {
                        "data": dict(weather_info),
                        "expires_at": now + self.cache_ttl
                    }
                self._save_disk_cache()

                logger.info(
                    f"[WEATHER] Success for ({grid_key[0]}, {grid_key[1]}): "
                    f"temp={weather_info['temperature_c']}°C, wind={weather_info['wind_speed_mps']}m/s, "
                    f"u10={weather_info['u10']}, v10={weather_info['v10']}, precip={weather_info['precipitation_mm']}mm"
                )
                return weather_info
            else:
                logger.warning(f"[WEATHER] API failure for ({grid_key[0]}, {grid_key[1]}): HTTP {resp.status_code} - {resp.text[:200]}")
        except requests.Timeout:
            logger.warning(f"[WEATHER] API failure for ({grid_key[0]}, {grid_key[1]}): Request timed out after {self.timeout}s")
        except Exception as e:
            logger.warning(f"[WEATHER] API failure for ({grid_key[0]}, {grid_key[1]}): {e}")

        # Failure fallback: real null values, NO synthetic/random numbers
        return {
            "temperature_c": None,
            "u10": None,
            "v10": None,
            "wind_speed_mps": None,
            "precipitation_mm": None,
            "source": "Open-Meteo",
            "available": False
        }

    def _fetch_batch_chunk(self, chunk_keys: List[Tuple[float, float]]) -> Dict[Tuple[float, float], Dict[str, Any]]:
        """
        Executes a single multi-location Open-Meteo request for up to 100 coordinates.
        """
        results: Dict[Tuple[float, float], Dict[str, Any]] = {}
        if not chunk_keys:
            return results

        lats = [str(k[0]) for k in chunk_keys]
        lons = [str(k[1]) for k in chunk_keys]

        params = {
            "latitude": ",".join(lats),
            "longitude": ",".join(lons),
            "current": "temperature_2m,precipitation,wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "ms"
        }

        logger.info(f"[WEATHER] Fetching Open-Meteo batch for {len(chunk_keys)} grid locations...")
        now = time.time()

        try:
            resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=self.timeout + 5)
            if resp.status_code == 200:
                raw_json = resp.json()
                items = raw_json if isinstance(raw_json, list) else [raw_json]

                for idx, item in enumerate(items):
                    if idx < len(chunk_keys):
                        k = chunk_keys[idx]
                        cur = item.get("current") if isinstance(item, dict) else None
                        w_info = self._extract_weather_payload(cur)
                        results[k] = w_info
                        # Update cache
                        with self._lock:
                            self._cache[k] = {
                                "data": dict(w_info),
                                "expires_at": now + self.cache_ttl
                            }
                logger.info(f"[WEATHER] Success batch chunk: {len(results)}/{len(chunk_keys)} locations retrieved.")
            else:
                logger.warning(f"[WEATHER] API failure for batch chunk: HTTP {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"[WEATHER] API failure for batch chunk: {e}")

        return results

    def batch_get_weather(self, coordinates: List[Tuple[float, float]]) -> Dict[Tuple[float, float], Dict[str, Any]]:
        """
        Batches unique grid coordinates to Open-Meteo and returns weather data.
        Uses in-memory cache for all cached locations; queries missing ones in batches of up to 100.
        """
        now = time.time()
        results: Dict[Tuple[float, float], Dict[str, Any]] = {}
        missing_keys: List[Tuple[float, float]] = []

        # 1. Deduplicate grid keys and check cache
        unique_grid_keys = list(set(self._get_grid_key(lat, lon) for lat, lon in coordinates if lat is not None and lon is not None))

        with self._lock:
            for k in unique_grid_keys:
                entry = self._cache.get(k)
                if entry and entry["expires_at"] > now and entry.get("data", {}).get("available"):
                    results[k] = dict(entry["data"])
                else:
                    missing_keys.append(k)

        if not missing_keys:
            logger.info(f"[WEATHER] Cache hit for all {len(unique_grid_keys)} unique grid locations.")
            return results

        logger.info(f"[WEATHER] Cache hit: {len(results)}, Missing: {len(missing_keys)} unique grid locations.")

        # 2. Chunk missing keys into batches of up to BATCH_CHUNK_SIZE
        chunks = [missing_keys[i:i + BATCH_CHUNK_SIZE] for i in range(0, len(missing_keys), BATCH_CHUNK_SIZE)]

        # 3. Retrieve chunks sequentially with polite pacing to prevent burst rate limits
        for idx, chunk in enumerate(chunks):
            if idx > 0:
                time.sleep(0.2)  # Polite pause between chunks
            chunk_results = self._fetch_batch_chunk(chunk)
            results.update(chunk_results)

        # Save newly fetched items to disk cache
        self._save_disk_cache()

        # 4. Fill any remaining unretrieved keys with available=False (real nulls, no fake numbers)
        for k in unique_grid_keys:
            if k not in results:
                results[k] = {
                    "temperature_c": None,
                    "u10": None,
                    "v10": None,
                    "wind_speed_mps": None,
                    "precipitation_mm": None,
                    "source": "Open-Meteo",
                    "available": False
                }

        return results

    def enrich_observations_with_weather(self, fires: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enriches a list of FIRMS thermal observation dictionaries with real weather data.
        Adds:
          - temperature_c
          - u10
          - v10
          - wind_speed_mps
          - precipitation_mm
          - weather_source
          - weather_available
        """
        if not fires or not isinstance(fires, list):
            return fires

        # Gather valid coordinates
        valid_coords: List[Tuple[float, float]] = []
        for fire in fires:
            try:
                lat = float(fire.get("latitude"))
                lon = float(fire.get("longitude"))
                valid_coords.append((lat, lon))
            except (ValueError, TypeError):
                continue

        # Batch query Open-Meteo with caching
        weather_map = self.batch_get_weather(valid_coords)

        # Attach fields to each observation
        for fire in fires:
            try:
                lat = float(fire.get("latitude"))
                lon = float(fire.get("longitude"))
                grid_k = self._get_grid_key(lat, lon)
                w_info = weather_map.get(grid_k)
            except (ValueError, TypeError):
                w_info = None

            if w_info:
                fire["temperature_c"] = w_info.get("temperature_c")
                fire["u10"] = w_info.get("u10")
                fire["v10"] = w_info.get("v10")
                fire["wind_speed_mps"] = w_info.get("wind_speed_mps")
                fire["precipitation_mm"] = w_info.get("precipitation_mm")
                fire["weather_source"] = w_info.get("source", "Open-Meteo")
                fire["weather_available"] = bool(w_info.get("available", False))
            else:
                fire["temperature_c"] = None
                fire["u10"] = None
                fire["v10"] = None
                fire["wind_speed_mps"] = None
                fire["precipitation_mm"] = None
                fire["weather_source"] = "Open-Meteo"
                fire["weather_available"] = False

        return fires


# Global singleton instance
weather_service = WeatherService()


def get_weather_for_location(latitude: float, longitude: float) -> Dict[str, Any]:
    """
    Public entrypoint: returns real weather data for a given latitude and longitude.
    """
    return weather_service.get_weather_for_location(latitude, longitude)


def enrich_observations_with_weather(fires: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Public entrypoint: enriches FIRMS observations with real weather data.
    """
    return weather_service.enrich_observations_with_weather(fires)
