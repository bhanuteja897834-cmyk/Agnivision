"""
AGNIVISION-GIS — HISTORICAL BASELINE FOUNDATION
Step 5: Reference Historical Dataset Integration

Architecture:
- Dynamic discovery of NASA FIRMS Standard Processing (VIIRS_NOAA20_SP) availability
- Safe historical period selection (non-overlapping with live NRT analysis window)
- 5-day request batching conforming to NASA FIRMS Area API constraints
- Local deterministic cache persistence in backend/data/historical_firms/
- Strict data quality validation and normalization
- Explicit distinction between zero-observation days and unavailable days
- Daily, overall, and spatial grid (0.1° x 0.1°) baseline statistics
- Zero synthetic data, zero ML, zero anomaly scoring in Step 5
"""

import csv
import datetime
import io
import json
import logging
import math
import os
import statistics
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

import requests

logger = logging.getLogger("agnivision.historical")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# =========================================================
# CONSTANTS & CONFIGURATION
# =========================================================

SOURCE_DATASET = "VIIRS_NOAA20_SP"
SOURCE_DATASET_TYPE = "NASA FIRMS Standard Processing"

MONITORING_REGIONS = {
    "india": {
        "key": "india",
        "name": "All-India Coverage",
        "west": 67.0,
        "south": 7.0,
        "east": 98.0,
        "north": 38.0
    },
    "eastern": {
        "key": "eastern",
        "name": "Eastern / Central-Eastern India Monitoring Region",
        "west": 82.0,
        "south": 20.0,
        "east": 90.0,
        "north": 27.0
    }
}
DEFAULT_REGION_KEY = "india"
MONITORING_REGION = MONITORING_REGIONS[DEFAULT_REGION_KEY]
BBOX_STR = f"{int(MONITORING_REGION['west'])},{int(MONITORING_REGION['south'])},{int(MONITORING_REGION['east'])},{int(MONITORING_REGION['north'])}"

TARGET_BASELINE_DAYS = 30
MAX_BATCH_DAYS = 5
GRID_RESOLUTION_DEG = 0.1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "data", "historical_firms")


def sanitize_key(message: str, key: str = "") -> str:
    """Sanitize strings so the FIRMS MAP_KEY is never exposed."""
    if not message:
        return ""
    if key and key in message:
        message = message.replace(key, "[REDACTED_MAP_KEY]")
    active_key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if active_key and active_key in message:
        message = message.replace(active_key, "[REDACTED_MAP_KEY]")
    return message


# =========================================================
# 1. DATA AVAILABILITY DISCOVERY
# =========================================================

def query_sp_availability(map_key: str, timeout: int = 15) -> Dict[str, str]:
    """
    Query the NASA FIRMS data availability endpoint dynamically for VIIRS_NOAA20_SP.
    Returns: {"data_id": "VIIRS_NOAA20_SP", "min_date": "YYYY-MM-DD", "max_date": "YYYY-MM-DD"}
    """
    if not map_key:
        raise ValueError("FIRMS_MAP_KEY is missing or empty.")

    url = f"https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{map_key}/{SOURCE_DATASET}"
    redacted_url = sanitize_key(url, map_key)
    logger.info(f"[HISTORICAL] Querying FIRMS data availability from {redacted_url}")

    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        safe_err = sanitize_key(str(e), map_key)
        logger.error(f"[HISTORICAL] Network error querying data availability: {safe_err}")
        raise RuntimeError(f"Could not connect to FIRMS data availability endpoint: {safe_err}")

    if response.status_code != 200:
        safe_body = sanitize_key(response.text[:200], map_key)
        logger.error(f"[HISTORICAL] Data availability query returned HTTP {response.status_code}: {safe_body}")
        raise RuntimeError(f"FIRMS data availability returned HTTP {response.status_code}: {safe_body}")

    lines = [l.strip() for l in response.text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"Unexpected data availability CSV format: {response.text[:200]}")

    reader = csv.DictReader(lines)
    for row in reader:
        data_id = row.get("data_id", "").strip()
        min_date = row.get("min_date", "").strip()
        max_date = row.get("max_date", "").strip()
        if data_id == SOURCE_DATASET or not data_id:
            return {
                "data_id": SOURCE_DATASET,
                "min_date": min_date,
                "max_date": max_date
            }

    # Fallback to first row
    first_row = lines[1].split(",")
    if len(first_row) >= 3:
        return {
            "data_id": first_row[0].strip(),
            "min_date": first_row[1].strip(),
            "max_date": first_row[2].strip()
        }

    raise RuntimeError(f"Unable to parse min/max date from availability response: {response.text[:200]}")


# =========================================================
# 2. HISTORICAL PERIOD SELECTION
# =========================================================

def select_baseline_period(
    min_date_str: str,
    max_date_str: str,
    target_days: int = TARGET_BASELINE_DAYS,
    nrt_start_date_str: Optional[str] = None
) -> Tuple[datetime.date, datetime.date]:
    """
    Select the latest valid contiguous period of target_days from the available SP range,
    strictly ensuring no overlap with the live NRT analysis window.
    """
    min_date = datetime.datetime.strptime(min_date_str, "%Y-%m-%d").date()
    max_date = datetime.datetime.strptime(max_date_str, "%Y-%m-%d").date()

    period_end = max_date

    # If NRT window start date is provided, enforce non-overlap
    if nrt_start_date_str:
        nrt_start = datetime.datetime.strptime(nrt_start_date_str, "%Y-%m-%d").date()
        if period_end >= nrt_start:
            period_end = nrt_start - datetime.timedelta(days=1)

    period_start = period_end - datetime.timedelta(days=target_days - 1)
    if period_start < min_date:
        period_start = min_date

    if period_start > period_end:
        raise ValueError(f"Invalid baseline period selected: {period_start} to {period_end}")

    return period_start, period_end


# =========================================================
# 3. REQUEST BATCHING
# =========================================================

def generate_request_batches(
    period_start: datetime.date,
    period_end: datetime.date,
    max_batch_days: int = MAX_BATCH_DAYS
) -> List[Dict[str, Any]]:
    """
    Split the [period_start, period_end] contiguous date range into batches of <= 5 days
    as required by the NASA FIRMS Area API.
    """
    batches = []
    curr = period_start

    while curr <= period_end:
        days_remaining = (period_end - curr).days + 1
        batch_days = min(days_remaining, max_batch_days)
        batch_end = curr + datetime.timedelta(days=batch_days - 1)
        batches.append({
            "start_date": curr.strftime("%Y-%m-%d"),
            "end_date": batch_end.strftime("%Y-%m-%d"),
            "day_range": batch_days
        })
        curr = batch_end + datetime.timedelta(days=1)

    return batches


# =========================================================
# 4. NORMALIZATION & QUALITY VALIDATION
# =========================================================

def parse_float_safe(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f if not math.isnan(f) and not math.isinf(f) else None
    except (ValueError, TypeError):
        return None


def validate_and_normalize_record(
    raw_row: Dict[str, str],
    period_start: datetime.date,
    period_end: datetime.date,
    region: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates a raw FIRMS observation row against spatial bounds, date ranges, and formats.
    Returns (normalized_record, None) if valid, or (None, discard_reason) if invalid.
    """
    # 1. Coordinate check
    lat = parse_float_safe(raw_row.get("latitude"))
    lon = parse_float_safe(raw_row.get("longitude"))

    if lat is None or lon is None:
        return None, "invalid_coordinates"

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, "invalid_coordinates"

    # 2. Monitoring Region Bounding Box Check
    target_region = region or MONITORING_REGION
    west = target_region["west"]
    south = target_region["south"]
    east = target_region["east"]
    north = target_region["north"]

    if not (west <= lon <= east and south <= lat <= north):
        return None, "out_of_bounds"

    # 3. Date / Time Validation
    acq_date_str = (raw_row.get("acq_date") or "").strip()
    try:
        acq_date = datetime.datetime.strptime(acq_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, "invalid_date_time"

    if not (period_start <= acq_date <= period_end):
        return None, "invalid_date_time"

    raw_time = (raw_row.get("acq_time") or "").strip()
    if not raw_time:
        acq_time_norm = "0000"
    else:
        acq_time_norm = raw_time.zfill(4)

    # 4. Brightness Values
    bright_ti4 = parse_float_safe(raw_row.get("bright_ti4"))
    bright_ti5 = parse_float_safe(raw_row.get("bright_ti5"))

    if bright_ti4 is None or bright_ti4 <= 0.0:
        return None, "invalid_brightness"

    # 5. FRP
    frp = parse_float_safe(raw_row.get("frp"))

    # Normalized clean schema (No current Event IDs assigned)
    record = {
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "bright_ti4": round(bright_ti4, 2),
        "bright_ti5": round(bright_ti5, 2) if bright_ti5 is not None else None,
        "scan": parse_float_safe(raw_row.get("scan")),
        "track": parse_float_safe(raw_row.get("track")),
        "acq_date": acq_date_str,
        "acq_time": acq_time_norm,
        "satellite": (raw_row.get("satellite") or "N20").strip(),
        "instrument": (raw_row.get("instrument") or "VIIRS").strip(),
        "confidence": (raw_row.get("confidence") or "nominal").strip(),
        "version": (raw_row.get("version") or "2").strip(),
        "frp": round(frp, 2) if frp is not None else None,
        "daynight": (raw_row.get("daynight") or "D").strip().upper(),
        "dataset": SOURCE_DATASET
    }

    return record, None


# =========================================================
# 5. BASELINE AGGREGATIONS & STATISTICS
# =========================================================

def compute_daily_baseline(
    period_start: datetime.date,
    period_end: datetime.date,
    valid_observations: List[Dict[str, Any]],
    batch_retrieval_status: Dict[str, bool]
) -> List[Dict[str, Any]]:
    """
    Computes daily historical baseline statistics.
    Preserves strict distinction between zero-observation days and unavailable days.
    Does NOT use 0 for missing thermal measurements.
    """
    # Group observations by date
    obs_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for obs in valid_observations:
        d = obs["acq_date"]
        obs_by_date.setdefault(d, []).append(obs)

    daily_list = []
    curr = period_start

    while curr <= period_end:
        date_str = curr.strftime("%Y-%m-%d")
        is_available = batch_retrieval_status.get(date_str, True)

        if not is_available:
            daily_list.append({
                "date": date_str,
                "status": "unavailable",
                "observation_count": None,
                "brightness_ti4": None,
                "frp": None
            })
        elif date_str not in obs_by_date or len(obs_by_date[date_str]) == 0:
            daily_list.append({
                "date": date_str,
                "status": "zero_observations",
                "observation_count": 0,
                "brightness_ti4": None,
                "frp": None
            })
        else:
            day_obs = obs_by_date[date_str]
            b_vals = [o["bright_ti4"] for o in day_obs if o.get("bright_ti4") is not None]
            frp_vals = [o["frp"] for o in day_obs if o.get("frp") is not None]

            daily_list.append({
                "date": date_str,
                "status": "valid_with_observations",
                "observation_count": len(day_obs),
                "brightness_ti4": {
                    "mean": round(statistics.mean(b_vals), 2) if b_vals else None,
                    "median": round(statistics.median(b_vals), 2) if b_vals else None,
                    "max": round(max(b_vals), 2) if b_vals else None
                },
                "frp": {
                    "mean": round(statistics.mean(frp_vals), 2) if frp_vals else None,
                    "median": round(statistics.median(frp_vals), 2) if frp_vals else None,
                    "max": round(max(frp_vals), 2) if frp_vals else None
                }
            })

        curr += datetime.timedelta(days=1)

    return daily_list


def compute_overall_baseline(
    daily_stats: List[Dict[str, Any]],
    valid_observations: List[Dict[str, Any]],
    quality_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Computes overall period statistics from valid historical observations.
    """
    b_vals = [o["bright_ti4"] for o in valid_observations if o.get("bright_ti4") is not None]
    frp_vals = [o["frp"] for o in valid_observations if o.get("frp") is not None]

    valid_days = sum(1 for d in daily_stats if d["status"] != "unavailable")
    days_with_obs = sum(1 for d in daily_stats if d["status"] == "valid_with_observations")
    zero_obs_days = sum(1 for d in daily_stats if d["status"] == "zero_observations")
    unavailable_days = sum(1 for d in daily_stats if d["status"] == "unavailable")

    quality_summary["valid_days"] = valid_days
    quality_summary["days_with_observations"] = days_with_obs
    quality_summary["zero_observation_days"] = zero_obs_days
    quality_summary["unavailable_days"] = unavailable_days

    return {
        "observation_count": len(valid_observations),
        "brightness_ti4": {
            "mean": round(statistics.mean(b_vals), 2) if b_vals else None,
            "median": round(statistics.median(b_vals), 2) if b_vals else None,
            "max": round(max(b_vals), 2) if b_vals else None
        },
        "frp": {
            "mean": round(statistics.mean(frp_vals), 2) if frp_vals else None,
            "median": round(statistics.median(frp_vals), 2) if frp_vals else None,
            "max": round(max(frp_vals), 2) if frp_vals else None
        }
    }


def compute_spatial_grid_baseline(
    valid_observations: List[Dict[str, Any]],
    grid_res: float = GRID_RESOLUTION_DEG,
    region: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Computes 0.1° x 0.1° spatial grid baseline cells across the monitoring region.
    Does NOT infer land-use, fire risk, or source probability.
    """
    target_region = region or MONITORING_REGION
    cells_dict: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}

    for obs in valid_observations:
        lat = obs["latitude"]
        lon = obs["longitude"]
        # Bin calculation
        lat_idx = int(math.floor((lat - target_region["south"]) / grid_res))
        lon_idx = int(math.floor((lon - target_region["west"]) / grid_res))
        cells_dict.setdefault((lat_idx, lon_idx), []).append(obs)

    grid_cells = []
    max_cell_obs = 0

    for (lat_idx, lon_idx), cell_obs in cells_dict.items():
        count = len(cell_obs)
        if count > max_cell_obs:
            max_cell_obs = count

        lat_min = round(target_region["south"] + (lat_idx * grid_res), 2)
        lat_max = round(lat_min + grid_res, 2)
        lon_min = round(target_region["west"] + (lon_idx * grid_res), 2)
        lon_max = round(lon_min + grid_res, 2)
        center_lat = round((lat_min + lat_max) / 2.0, 3)
        center_lon = round((lon_min + lon_max) / 2.0, 3)

        b_vals = [o["bright_ti4"] for o in cell_obs if o.get("bright_ti4") is not None]
        frp_vals = [o["frp"] for o in cell_obs if o.get("frp") is not None]

        grid_cells.append({
            "cell_id": f"grid_{round(lat_min, 1)}_{round(lon_min, 1)}",
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "observation_count": count,
            "mean_bright_ti4": round(statistics.mean(b_vals), 2) if b_vals else None,
            "median_bright_ti4": round(statistics.median(b_vals), 2) if b_vals else None,
            "mean_frp": round(statistics.mean(frp_vals), 2) if frp_vals else None,
            "median_frp": round(statistics.median(frp_vals), 2) if frp_vals else None
        })

    # Sort cells descending by observation count for convenient inspection
    grid_cells.sort(key=lambda c: c["observation_count"], reverse=True)

    return {
        "dataset": SOURCE_DATASET,
        "grid_resolution_deg": grid_res,
        "monitoring_region": target_region,
        "total_populated_cells": len(grid_cells),
        "max_cell_observations": max_cell_obs,
        "cells": grid_cells
    }


# =========================================================
# 6. HISTORICAL BASELINE MANAGER
# =========================================================

class HistoricalBaselineManager:
    """
    Thread-safe manager for downloading, caching, normalizing,
    and serving historical baseline data.
    """

    def __init__(self, cache_dir: str = CACHE_DIR, region_key: str = "india"):
        self.cache_dir = cache_dir
        self.region_key = region_key if region_key in MONITORING_REGIONS else DEFAULT_REGION_KEY
        self.region = MONITORING_REGIONS[self.region_key]
        self.lock = threading.Lock()
        self.is_loaded = False
        self.last_retrieved_iso: Optional[str] = None
        self.error_message: Optional[str] = None

        self.sp_availability: Dict[str, str] = {}
        self.period_start: Optional[datetime.date] = None
        self.period_end: Optional[datetime.date] = None

        self.quality_summary: Dict[str, Any] = {}
        self.overall_statistics: Dict[str, Any] = {}
        self.daily_statistics: List[Dict[str, Any]] = []
        self.spatial_grid: Dict[str, Any] = {}
        self.valid_observations: List[Dict[str, Any]] = []

    def get_cache_file_paths(self, start_str: str, end_str: str) -> Tuple[str, str]:
        """Returns deterministic file paths for the raw CSV and processed JSON cache."""
        os.makedirs(self.cache_dir, exist_ok=True)
        w = int(self.region["west"])
        s = int(self.region["south"])
        e = int(self.region["east"])
        n = int(self.region["north"])
        filename_base = f"{SOURCE_DATASET}_{start_str}_{end_str}_{w}_{s}_{e}_{n}"
        raw_csv_path = os.path.join(self.cache_dir, f"{filename_base}.csv")
        summary_json_path = os.path.join(self.cache_dir, f"{filename_base}_baseline.json")
        return raw_csv_path, summary_json_path

    def load_or_fetch(self, map_key: str, force_refresh: bool = False) -> None:
        """
        Loads baseline from local cache if present, otherwise queries NASA FIRMS.
        Thread-safe singleton operation.
        """
        with self.lock:
            if self.is_loaded and not force_refresh:
                return

            try:
                # 0. Check if a valid local baseline cache already exists for this region
                if not force_refresh and os.path.exists(self.cache_dir):
                    w = int(self.region["west"])
                    s = int(self.region["south"])
                    e = int(self.region["east"])
                    n = int(self.region["north"])
                    suffix = f"_{w}_{s}_{e}_{n}_baseline.json"
                    for fname in os.listdir(self.cache_dir):
                        if fname.endswith(suffix):
                            cached_path = os.path.join(self.cache_dir, fname)
                            try:
                                with open(cached_path, "r", encoding="utf-8") as f:
                                    cached_data = json.load(f)
                                self.quality_summary = cached_data["quality_summary"]
                                self.overall_statistics = cached_data["overall_statistics"]
                                self.daily_statistics = cached_data["daily_statistics"]
                                self.spatial_grid = cached_data["spatial_grid"]
                                self.last_retrieved_iso = cached_data.get("last_retrieved_iso")
                                self.period_start = datetime.datetime.strptime(self.quality_summary.get("period_start", "2026-06-01"), "%Y-%m-%d").date()
                                self.period_end = datetime.datetime.strptime(self.quality_summary.get("period_end", "2026-06-30"), "%Y-%m-%d").date()
                                self.is_loaded = True
                                self.error_message = None
                                logger.info(f"[HISTORICAL] Loaded existing cached baseline from {fname}")
                                return
                            except Exception as load_err:
                                logger.warning(f"[HISTORICAL] Failed loading cache {fname}: {load_err}")

                # 1. Dynamic Availability Discovery
                self.sp_availability = query_sp_availability(map_key)
                min_avail = self.sp_availability.get("min_date")
                max_avail = self.sp_availability.get("max_date")

                if not min_avail or not max_avail:
                    raise RuntimeError("FIRMS SP availability did not return min_date or max_date.")

                # 2. Select Baseline Period (30 contiguous days up to max_date)
                self.period_start, self.period_end = select_baseline_period(min_avail, max_avail, TARGET_BASELINE_DAYS)
                start_str = self.period_start.strftime("%Y-%m-%d")
                end_str = self.period_end.strftime("%Y-%m-%d")

                raw_csv_path, json_cache_path = self.get_cache_file_paths(start_str, end_str)

                # Check if processed JSON cache exists
                if os.path.exists(json_cache_path) and not force_refresh:
                    logger.info(f"[HISTORICAL] Loading cached baseline from {os.path.basename(json_cache_path)}")
                    with open(json_cache_path, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)

                    self.quality_summary = cached_data["quality_summary"]
                    self.overall_statistics = cached_data["overall_statistics"]
                    self.daily_statistics = cached_data["daily_statistics"]
                    self.spatial_grid = cached_data["spatial_grid"]
                    self.last_retrieved_iso = cached_data.get("last_retrieved_iso")
                    self.is_loaded = True
                    self.error_message = None
                    return

                # 3. Query FIRMS Area API in Batches of <= 5 days
                batches = generate_request_batches(self.period_start, self.period_end, MAX_BATCH_DAYS)
                raw_rows: List[Dict[str, str]] = []
                batch_day_status: Dict[str, bool] = {}

                # Pre-populate day status as True
                curr_d = self.period_start
                while curr_d <= self.period_end:
                    batch_day_status[curr_d.strftime("%Y-%m-%d")] = True
                    curr_d += datetime.timedelta(days=1)

                logger.info(f"[HISTORICAL] Downloading {len(batches)} batches for period {start_str} to {end_str}")

                for b in batches:
                    b_start = b["start_date"]
                    b_range = b["day_range"]
                    b_end = b["end_date"]
                    bbox_str = f"{int(self.region['west'])},{int(self.region['south'])},{int(self.region['east'])},{int(self.region['north'])}"
                    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{SOURCE_DATASET}/{bbox_str}/{b_range}/{b_start}"
                    redacted_url = sanitize_key(url, map_key)
                    logger.info(f"[HISTORICAL] Requesting batch {b_start} ({b_range} days) from {redacted_url}")

                    try:
                        resp = requests.get(url, timeout=25)
                        if resp.status_code == 200 and resp.text.strip():
                            csv_file = io.StringIO(resp.text.strip())
                            reader = csv.DictReader(csv_file)
                            for row in reader:
                                raw_rows.append({k.strip(): v.strip() for k, v in row.items() if k})
                        else:
                            logger.warning(f"[HISTORICAL] Batch {b_start} returned HTTP {resp.status_code}")
                            curr_b = datetime.datetime.strptime(b_start, "%Y-%m-%d").date()
                            end_b = datetime.datetime.strptime(b_end, "%Y-%m-%d").date()
                            while curr_b <= end_b:
                                batch_day_status[curr_b.strftime("%Y-%m-%d")] = False
                                curr_b += datetime.timedelta(days=1)
                    except requests.RequestException as e:
                        logger.error(f"[HISTORICAL] Batch request failed for {b_start}: {sanitize_key(str(e), map_key)}")
                        curr_b = datetime.datetime.strptime(b_start, "%Y-%m-%d").date()
                        end_b = datetime.datetime.strptime(b_end, "%Y-%m-%d").date()
                        while curr_b <= end_b:
                            batch_day_status[curr_b.strftime("%Y-%m-%d")] = False
                            curr_b += datetime.timedelta(days=1)

                # 4. Validation, Normalization, Deduplication
                raw_count = len(raw_rows)
                valid_obs: List[Dict[str, Any]] = []
                discarded_count = 0
                discard_breakdown = {
                    "duplicates": 0,
                    "invalid_coordinates": 0,
                    "out_of_bounds": 0,
                    "invalid_date_time": 0,
                    "invalid_brightness": 0,
                    "other": 0
                }
                seen_keys = set()

                for raw in raw_rows:
                    record, discard_reason = validate_and_normalize_record(raw, self.period_start, self.period_end, region=self.region)
                    if discard_reason:
                        discarded_count += 1
                        discard_breakdown[discard_reason] = discard_breakdown.get(discard_reason, 0) + 1
                        continue

                    # Deduplication key
                    dup_key = (
                        record["latitude"],
                        record["longitude"],
                        record["acq_date"],
                        record["acq_time"],
                        record["satellite"]
                    )
                    if dup_key in seen_keys:
                        discarded_count += 1
                        discard_breakdown["duplicates"] += 1
                        continue

                    seen_keys.add(dup_key)
                    valid_obs.append(record)

                self.valid_observations = valid_obs

                # 5. Base Metadata Object
                self.quality_summary = {
                    "dataset": SOURCE_DATASET,
                    "dataset_type": SOURCE_DATASET_TYPE,
                    "monitoring_region": self.region,
                    "period_start": start_str,
                    "period_end": end_str,
                    "requested_days": (self.period_end - self.period_start).days + 1,
                    "valid_days": 0,
                    "days_with_observations": 0,
                    "zero_observation_days": 0,
                    "unavailable_days": 0,
                    "raw_observation_count": raw_count,
                    "valid_observation_count": len(valid_obs),
                    "discarded_observation_count": discarded_count,
                    "discard_breakdown": discard_breakdown,
                    "grid_resolution": f"{GRID_RESOLUTION_DEG}°"
                }

                # 6. Daily, Overall, and Grid Aggregations
                self.daily_statistics = compute_daily_baseline(
                    self.period_start,
                    self.period_end,
                    valid_obs,
                    batch_day_status
                )

                self.overall_statistics = compute_overall_baseline(
                    self.daily_statistics,
                    valid_obs,
                    self.quality_summary
                )

                self.spatial_grid = compute_spatial_grid_baseline(
                    valid_obs,
                    GRID_RESOLUTION_DEG,
                    region=self.region
                )

                self.last_retrieved_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self.is_loaded = True
                self.error_message = None

                # 7. Write to Local Deterministic Cache
                # Save raw observations CSV
                if raw_rows:
                    fieldnames = list(raw_rows[0].keys())
                    with open(raw_csv_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(raw_rows)

                # Save metadata and baseline summaries JSON
                with open(json_cache_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "quality_summary": self.quality_summary,
                        "overall_statistics": self.overall_statistics,
                        "daily_statistics": self.daily_statistics,
                        "spatial_grid": self.spatial_grid,
                        "last_retrieved_iso": self.last_retrieved_iso
                    }, f, indent=2)

                logger.info(f"[HISTORICAL] Baseline successfully built and cached. Valid observations: {len(valid_obs)}")

            except Exception as e:
                safe_err = sanitize_key(str(e), map_key)
                logger.error(f"[HISTORICAL] Failed to load/build historical baseline: {safe_err}")
                self.error_message = safe_err
                self.is_loaded = False
                raise

    def get_summary(self) -> Dict[str, Any]:
        if not self.is_loaded:
            return {"status": "unavailable", "reason": self.error_message or "Historical baseline not loaded"}
        return {
            "dataset": SOURCE_DATASET,
            "dataset_type": SOURCE_DATASET_TYPE,
            "period": {
                "start": self.quality_summary.get("period_start"),
                "end": self.quality_summary.get("period_end"),
                "requested_days": self.quality_summary.get("requested_days")
            },
            "monitoring_region": self.region,
            "quality": self.quality_summary,
            "statistics": self.overall_statistics
        }

    def get_daily(self) -> Dict[str, Any]:
        if not self.is_loaded:
            return {"status": "unavailable", "reason": self.error_message or "Historical baseline not loaded"}
        return {
            "dataset": SOURCE_DATASET,
            "period_start": self.quality_summary.get("period_start"),
            "period_end": self.quality_summary.get("period_end"),
            "total_days": len(self.daily_statistics),
            "days": self.daily_statistics
        }

    def get_grid(self) -> Dict[str, Any]:
        if not self.is_loaded:
            return {"status": "unavailable", "reason": self.error_message or "Historical baseline not loaded"}
        return self.spatial_grid

    def get_status(self) -> Dict[str, Any]:
        start_str = self.period_start.strftime("%Y-%m-%d") if self.period_start else "N/A"
        end_str = self.period_end.strftime("%Y-%m-%d") if self.period_end else "N/A"
        raw_csv_path, json_cache_path = self.get_cache_file_paths(start_str, end_str)

        cache_exists = os.path.exists(json_cache_path)
        cache_size = os.path.getsize(json_cache_path) if cache_exists else 0

        return {
            "status": "ready" if self.is_loaded else ("error" if self.error_message else "uninitialized"),
            "dataset": SOURCE_DATASET,
            "dataset_type": SOURCE_DATASET_TYPE,
            "sp_availability": self.sp_availability,
            "selected_period": {
                "start": start_str,
                "end": end_str,
                "days": TARGET_BASELINE_DAYS
            },
            "cache_status": {
                "cached": cache_exists,
                "cache_file": os.path.basename(json_cache_path) if cache_exists else None,
                "cache_size_bytes": cache_size
            },
            "last_retrieved": self.last_retrieved_iso,
            "data_quality_status": "passed" if (self.is_loaded and self.quality_summary.get("valid_observation_count", 0) > 0) else "warning",
            "valid_observations": self.quality_summary.get("valid_observation_count", 0),
            "error_message": self.error_message
        }

    def get_valid_observations(self) -> List[Dict[str, Any]]:
        """Returns the list of valid historical observations, loading from raw CSV cache if needed."""
        with self.lock:
            if self.valid_observations:
                return self.valid_observations

            start_str = self.period_start.strftime("%Y-%m-%d") if self.period_start else "2026-06-01"
            end_str = self.period_end.strftime("%Y-%m-%d") if self.period_end else "2026-06-30"
            raw_csv_path, _ = self.get_cache_file_paths(start_str, end_str)

            if os.path.exists(raw_csv_path):
                valid_obs = []
                p_start = self.period_start or datetime.date(2026, 6, 1)
                p_end = self.period_end or datetime.date(2026, 6, 30)
                try:
                    with open(raw_csv_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            rec, err = validate_and_normalize_record(row, p_start, p_end, region=self.region)
                            if rec and not err:
                                valid_obs.append(rec)
                    self.valid_observations = valid_obs
                except Exception as e:
                    logger.error(f"[HISTORICAL] Error reading raw cache: {e}")

            return self.valid_observations

    def get_cell_observations(self, cell_id: str) -> List[Dict[str, Any]]:
        """Returns all historical observations falling into a specific 0.1° grid cell."""
        obs_list = self.get_valid_observations()
        parts = cell_id.replace("grid_", "").split("_")
        if len(parts) != 2:
            return []
        try:
            c_lat = float(parts[0])
            c_lon = float(parts[1])
            lat_min = round(c_lat, 2)
            lat_max = round(lat_min + GRID_RESOLUTION_DEG, 2)
            lon_min = round(c_lon, 2)
            lon_max = round(lon_min + GRID_RESOLUTION_DEG, 2)
            north_bound = self.region["north"]
            east_bound = self.region["east"]
            return [
                o for o in obs_list
                if (lat_min <= o["latitude"] < lat_max or (lat_max >= north_bound and o["latitude"] == north_bound))
                and (lon_min <= o["longitude"] < lon_max or (lon_max >= east_bound and o["longitude"] == east_bound))
            ]
        except (ValueError, TypeError):
            return []


# Global Manager Registry
_baseline_managers: Dict[str, HistoricalBaselineManager] = {}

def get_historical_baseline_manager(mode: Optional[str] = None) -> HistoricalBaselineManager:
    key = (mode or DEFAULT_REGION_KEY).strip().lower()
    if key not in MONITORING_REGIONS:
        key = DEFAULT_REGION_KEY
    if key not in _baseline_managers:
        _baseline_managers[key] = HistoricalBaselineManager(region_key=key)
    return _baseline_managers[key]


# Default Manager Singleton (India-wide)
historical_baseline_manager = get_historical_baseline_manager("india")
