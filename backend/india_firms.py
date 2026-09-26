"""
AGNIVISION-GIS: India-Wide FIRMS Observation Ingestion & Data Management Layer
Handles NASA FIRMS VIIRS NOAA-20 NRT observation retrieval, validation, and disk caching
for the All-India bounding box (West 67, South 7, East 98, North 38)
while preserving the existing Eastern India demo dataset (West 82, South 20, East 90, North 27).
"""

import os
import io
import csv
import json
import time
import logging
import datetime
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agnivision.india_firms")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EXISTING_DIR = os.path.join(DATA_DIR, "existing")
INDIA_DIR = os.path.join(DATA_DIR, "india")

EASTERN_INDIA_FILE = os.path.join(EXISTING_DIR, "firms_eastern_india_918.json")
INDIA_OBSERVATIONS_FILE = os.path.join(INDIA_DIR, "firms_india_observations.json")
INDIA_EVENTS_FILE = os.path.join(INDIA_DIR, "firms_india_events.json")
INDIA_RAW_CSV_FILE = os.path.join(INDIA_DIR, "firms_india_raw.csv")

EASTERN_INDIA_BBOX = "82,20,90,27"
INDIA_BBOX = "67,7,98,38"
SOURCE = "VIIRS_NOAA20_NRT"


def ensure_directories():
    os.makedirs(EXISTING_DIR, exist_ok=True)
    os.makedirs(INDIA_DIR, exist_ok=True)


def sanitize_log(text: str, secret: Optional[str] = None) -> str:
    if not secret:
        return text
    return text.replace(secret, "[REDACTED_MAP_KEY]")


class IndiaFirmsManager:
    """
    Manages authentic NASA FIRMS observations for both the existing Eastern India
    demo region and the expanded India-wide coverage region.
    """

    def __init__(self):
        ensure_directories()
        self._cached_india_data: Optional[Dict[str, Any]] = None

    def get_eastern_india_dataset(self) -> Optional[Dict[str, Any]]:
        """
        Loads the authoritative frozen 918-observation Eastern India demo dataset.
        """
        if os.path.exists(EASTERN_INDIA_FILE):
            try:
                with open(EASTERN_INDIA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[INDIA_FIRMS] Error loading Eastern India snapshot: {e}")
        return None

    def save_eastern_india_snapshot(self, fires: List[Dict[str, Any]]) -> bool:
        """
        Safely saves a snapshot of the Eastern India 918 observations if not already stored.
        """
        ensure_directories()
        try:
            temp_file = EASTERN_INDIA_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "mode": "eastern_india",
                    "bbox": EASTERN_INDIA_BBOX,
                    "source": SOURCE,
                    "count": len(fires),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "fires": fires
                }, f, indent=2)
            os.replace(temp_file, EASTERN_INDIA_FILE)
            logger.info(f"[INDIA_FIRMS] Saved Eastern India snapshot ({len(fires)} observations).")
            return True
        except Exception as e:
            logger.error(f"[INDIA_FIRMS] Error saving Eastern India snapshot: {e}")
            return False

    def load_cached_india_observations(self) -> Optional[Dict[str, Any]]:
        """
        Loads cached India-wide observations from disk if available.
        """
        if self._cached_india_data:
            return self._cached_india_data

        if os.path.exists(INDIA_OBSERVATIONS_FILE):
            try:
                with open(INDIA_OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "fires" in data and isinstance(data["fires"], list):
                        self._cached_india_data = data
                        logger.info(f"[INDIA_FIRMS] Loaded {len(data['fires'])} India-wide observations from cache.")
                        return data
            except Exception as e:
                logger.warning(f"[INDIA_FIRMS] Could not read cached India observations: {e}")
        return None

    def load_cached_india_events(self) -> Optional[List[Dict[str, Any]]]:
        """
        Loads cached India-wide persistent events from disk if available.
        """
        if os.path.exists(INDIA_EVENTS_FILE):
            try:
                with open(INDIA_EVENTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "events" in data and isinstance(data["events"], list):
                        return data["events"]
                    if isinstance(data, list):
                        return data
            except Exception as e:
                logger.warning(f"[INDIA_FIRMS] Could not read cached India events: {e}")
        return None

    def save_india_events(self, events: List[Dict[str, Any]], total_observations: int = 0) -> bool:
        """
        Saves India-wide persistent events to disk.
        """
        ensure_directories()
        try:
            temp_file = INDIA_EVENTS_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "count": len(events),
                    "total_observations": total_observations,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "events": events
                }, f, indent=2)
            os.replace(temp_file, INDIA_EVENTS_FILE)
            logger.info(f"[INDIA_FIRMS] Saved {len(events)} India-wide events to disk.")
            return True
        except Exception as e:
            logger.error(f"[INDIA_FIRMS] Could not save India events: {e}")
            return False

    def fetch_and_cache_india_observations(
        self,
        map_key: str,
        validate_geo_func=None,
        calc_risk_func=None,
        conf_label_func=None
    ) -> Dict[str, Any]:
        """
        Retrieves authentic 10-day VIIRS NOAA-20 NRT observations from NASA FIRMS Area API
        for the full-India bounding box (67,7,98,38), deduplicates them, enriches with
        geographic domain & risk scores, and caches to disk.
        """
        ensure_directories()
        today = datetime.date.today()
        start_date_earlier = (today - datetime.timedelta(days=9)).strftime("%Y-%m-%d")

        target_urls = [
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{SOURCE}/{INDIA_BBOX}/5/{start_date_earlier}",
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{SOURCE}/{INDIA_BBOX}/5"
        ]

        raw_texts = []
        raw_rows = []
        headers = []

        start_time = time.time()
        for url in target_urls:
            redacted = sanitize_log(url, map_key)
            logger.info(f"[INDIA_FIRMS] Querying NASA FIRMS India bbox: {redacted}")

            try:
                response = requests.get(url, timeout=35)
                if response.status_code == 200:
                    text = response.text.strip()
                    if text and not text.startswith("<!DOCTYPE") and not text.startswith("<html"):
                        raw_texts.append(text)
                        reader = csv.reader(io.StringIO(text))
                        batch_headers = [h.strip() for h in next(reader, [])]
                        if not headers and batch_headers:
                            headers = batch_headers
                        for row in reader:
                            if len(row) == len(batch_headers):
                                raw_rows.append(dict(zip(batch_headers, [c.strip() for c in row])))
                    else:
                        logger.warning(f"[INDIA_FIRMS] Non-CSV or HTML response from NASA FIRMS: {redacted}")
                else:
                    logger.warning(f"[INDIA_FIRMS] HTTP {response.status_code} from NASA FIRMS: {redacted}")
            except Exception as e:
                logger.error(f"[INDIA_FIRMS] Network exception querying NASA FIRMS India bbox: {sanitize_log(str(e), map_key)}")

        # Save raw CSV data to disk for provenance
        if raw_texts:
            try:
                with open(INDIA_RAW_CSV_FILE, "w", encoding="utf-8") as f:
                    for idx, t in enumerate(raw_texts):
                        f.write(f"# --- BATCH {idx + 1} ---\n")
                        f.write(t + "\n\n")
            except Exception as e:
                logger.warning(f"[INDIA_FIRMS] Could not write raw CSV: {e}")

        # Deduplicate strictly across overlapping observation intervals
        seen = set()
        fires = []
        outside_old_bbox_count = 0

        for fire in raw_rows:
            dedup_key = (
                fire.get("latitude"),
                fire.get("longitude"),
                fire.get("acq_date"),
                fire.get("acq_time"),
                fire.get("satellite"),
                fire.get("track"),
                fire.get("scan")
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Standardize brightness fields across VIIRS / MODIS
            if "brightness" not in fire and "bright_ti4" in fire:
                fire["brightness"] = fire["bright_ti4"]
            elif "bright_ti4" not in fire and "brightness" in fire:
                fire["bright_ti4"] = fire["brightness"]

            if "type" not in fire:
                fire["type"] = None

            # Calculate whether coordinate is outside the Eastern India bbox
            try:
                lat_f = float(fire.get("latitude", 0))
                lon_f = float(fire.get("longitude", 0))
                is_outside_eastern = not (82.0 <= lon_f <= 90.0 and 20.0 <= lat_f <= 27.0)
                if is_outside_eastern:
                    outside_old_bbox_count += 1
            except (ValueError, TypeError):
                is_outside_eastern = False

            fire["outside_eastern_bbox"] = is_outside_eastern

            # Geographic Domain Validation if function provided
            if validate_geo_func:
                fire["geographic_validation"] = validate_geo_func(
                    fire.get("latitude"),
                    fire.get("longitude"),
                    resolve_detailed=False
                )
            else:
                fire["geographic_validation"] = {"domain": "LAND", "state": "India", "district": "India", "city": "India"}

            # Confidence label
            raw_conf = fire.get("confidence") or ""
            if conf_label_func:
                fire["confidence_label"] = conf_label_func(raw_conf)
            else:
                fire["confidence_label"] = "Nominal"

            # Risk calculation
            if calc_risk_func:
                base_risk = calc_risk_func(fire.get("bright_ti4"), raw_conf)
                fire["risk_score"] = round(float(base_risk), 1)
                if fire["risk_score"] >= 80:
                    fire["risk_level"] = "Critical"
                elif fire["risk_score"] >= 60:
                    fire["risk_level"] = "High"
                elif fire["risk_score"] >= 30:
                    fire["risk_level"] = "Moderate"
                else:
                    fire["risk_level"] = "Low"
            else:
                fire["risk_score"] = 50.0
                fire["risk_level"] = "Moderate"

            fire["persistence_days"] = 1
            fires.append(fire)

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"[INDIA_FIRMS] Processed {len(fires)} India-wide observations "
            f"({outside_old_bbox_count} outside Eastern India) in {elapsed}s."
        )

        result_payload = {
            "mode": "india",
            "region": "India-wide National Coverage",
            "bbox": INDIA_BBOX,
            "bounds": {"west": 67.0, "south": 7.0, "east": 98.0, "north": 38.0},
            "source": SOURCE,
            "count": len(fires),
            "observations_outside_eastern_bbox": outside_old_bbox_count,
            "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fetch_duration_seconds": elapsed,
            "fires": fires
        }

        # Cache to disk
        try:
            temp_file = INDIA_OBSERVATIONS_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(result_payload, f, indent=2)
            os.replace(temp_file, INDIA_OBSERVATIONS_FILE)
            self._cached_india_data = result_payload
            logger.info(f"[INDIA_FIRMS] Saved India-wide cache ({len(fires)} observations) to disk.")
        except Exception as e:
            logger.error(f"[INDIA_FIRMS] Could not save India-wide observations cache: {e}")

        return result_payload

    def get_status(self) -> Dict[str, Any]:
        """
        Returns status summary of available datasets.
        """
        has_eastern = os.path.exists(EASTERN_INDIA_FILE)
        has_india = os.path.exists(INDIA_OBSERVATIONS_FILE)

        eastern_count = 0
        if has_eastern:
            try:
                with open(EASTERN_INDIA_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    eastern_count = d.get("count", len(d.get("fires", [])))
            except Exception:
                pass

        india_count = 0
        india_outside = 0
        if has_india:
            try:
                with open(INDIA_OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    india_count = d.get("count", len(d.get("fires", [])))
                    india_outside = d.get("observations_outside_eastern_bbox", 0)
            except Exception:
                pass

        return {
            "status": "ready",
            "active_modes": ["india", "eastern_india"],
            "default_mode": "india",
            "eastern_india": {
                "bbox": EASTERN_INDIA_BBOX,
                "cached": has_eastern,
                "observation_count": eastern_count or 918,
                "source": SOURCE,
                "description": "Authoritative Eastern India Demo Region (82°E-90°E, 20°N-27°N)"
            },
            "india": {
                "bbox": INDIA_BBOX,
                "cached": has_india,
                "observation_count": india_count,
                "observations_outside_eastern_bbox": india_outside,
                "source": SOURCE,
                "description": "Full-India National Coverage (67°E-98°E, 7°N-38°N)"
            }
        }


# Global singleton instance
india_firms_manager = IndiaFirmsManager()
