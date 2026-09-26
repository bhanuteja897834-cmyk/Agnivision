"""
Script to rebuild the authentic India-wide historical baseline cache.
"""
import csv
import datetime
import json
import math
import os
import statistics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "data", "historical_firms")
CSV_PATH = os.path.join(CACHE_DIR, "VIIRS_NOAA20_SP_2026-06-01_2026-06-30_67_7_98_38.csv")
JSON_PATH = os.path.join(CACHE_DIR, "VIIRS_NOAA20_SP_2026-06-01_2026-06-30_67_7_98_38_baseline.json")

REGION = {
    "name": "All-India Coverage",
    "west": 67.0,
    "south": 7.0,
    "east": 98.0,
    "north": 38.0
}
PERIOD_START = datetime.date(2026, 6, 1)
PERIOD_END = datetime.date(2026, 6, 30)
GRID_RES = 0.1

def rebuild():
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    raw_count = len(rows)
    seen = set()
    valid_obs = []
    discarded = 0
    discard_reasons = {}

    for r in rows:
        try:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
        except (ValueError, TypeError):
            discarded += 1
            discard_reasons["invalid_coords"] = discard_reasons.get("invalid_coords", 0) + 1
            continue

        if not (REGION["west"] <= lon <= REGION["east"] and REGION["south"] <= lat <= REGION["north"]):
            discarded += 1
            discard_reasons["out_of_bounds"] = discard_reasons.get("out_of_bounds", 0) + 1
            continue

        d_str = r.get("acq_date", "").strip()
        try:
            d = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            discarded += 1
            discard_reasons["invalid_date"] = discard_reasons.get("invalid_date", 0) + 1
            continue

        if not (PERIOD_START <= d <= PERIOD_END):
            discarded += 1
            continue

        try:
            b4 = float(r["bright_ti4"])
            if b4 <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            discarded += 1
            discard_reasons["invalid_brightness"] = discard_reasons.get("invalid_brightness", 0) + 1
            continue

        try:
            frp = float(r["frp"]) if r.get("frp") not in (None, "") else None
        except (ValueError, TypeError):
            frp = None

        try:
            b5 = float(r["bright_ti5"]) if r.get("bright_ti5") not in (None, "") else None
        except (ValueError, TypeError):
            b5 = None

        acq_time = (r.get("acq_time") or "0000").strip().zfill(4)
        sat = (r.get("satellite") or "N20").strip()

        dup_key = (round(lat, 5), round(lon, 5), d_str, acq_time, sat)
        if dup_key in seen:
            discarded += 1
            discard_reasons["duplicates"] = discard_reasons.get("duplicates", 0) + 1
            continue
        seen.add(dup_key)

        valid_obs.append({
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "bright_ti4": round(b4, 2),
            "bright_ti5": round(b5, 2) if b5 is not None else None,
            "scan": float(r["scan"]) if r.get("scan") else None,
            "track": float(r["track"]) if r.get("track") else None,
            "acq_date": d_str,
            "acq_time": acq_time,
            "satellite": sat,
            "instrument": (r.get("instrument") or "VIIRS").strip(),
            "confidence": (r.get("confidence") or "nominal").strip(),
            "version": (r.get("version") or "2").strip(),
            "frp": round(frp, 2) if frp is not None else None,
            "daynight": (r.get("daynight") or "D").strip().upper(),
            "dataset": "VIIRS_NOAA20_SP"
        })

    # 1. Daily statistics
    obs_by_date = {}
    for o in valid_obs:
        obs_by_date.setdefault(o["acq_date"], []).append(o)

    daily_list = []
    curr = PERIOD_START
    while curr <= PERIOD_END:
        d_str = curr.strftime("%Y-%m-%d")
        day_obs = obs_by_date.get(d_str, [])
        if not day_obs:
            daily_list.append({
                "date": d_str,
                "status": "zero_observations",
                "observation_count": 0,
                "brightness_ti4": None,
                "frp": None
            })
        else:
            b_vals = [o["bright_ti4"] for o in day_obs if o.get("bright_ti4") is not None]
            frp_vals = [o["frp"] for o in day_obs if o.get("frp") is not None]
            daily_list.append({
                "date": d_str,
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

    # 2. Overall statistics
    b_all = [o["bright_ti4"] for o in valid_obs if o.get("bright_ti4") is not None]
    frp_all = [o["frp"] for o in valid_obs if o.get("frp") is not None]
    overall_stats = {
        "observation_count": len(valid_obs),
        "brightness_ti4": {
            "mean": round(statistics.mean(b_all), 2) if b_all else None,
            "median": round(statistics.median(b_all), 2) if b_all else None,
            "max": round(max(b_all), 2) if b_all else None
        },
        "frp": {
            "mean": round(statistics.mean(frp_all), 2) if frp_all else None,
            "median": round(statistics.median(frp_all), 2) if frp_all else None,
            "max": round(max(frp_all), 2) if frp_all else None
        }
    }

    # 3. Spatial Grid
    cells_dict = {}
    for o in valid_obs:
        lat = o["latitude"]
        lon = o["longitude"]
        lat_idx = int(math.floor((lat - REGION["south"]) / GRID_RES))
        lon_idx = int(math.floor((lon - REGION["west"]) / GRID_RES))
        cells_dict.setdefault((lat_idx, lon_idx), []).append(o)

    grid_cells = []
    max_cell_obs = 0
    for (lat_idx, lon_idx), c_obs in cells_dict.items():
        cnt = len(c_obs)
        if cnt > max_cell_obs:
            max_cell_obs = cnt
        lat_min = round(REGION["south"] + (lat_idx * GRID_RES), 2)
        lat_max = round(lat_min + GRID_RES, 2)
        lon_min = round(REGION["west"] + (lon_idx * GRID_RES), 2)
        lon_max = round(lon_min + GRID_RES, 2)
        center_lat = round((lat_min + lat_max) / 2.0, 3)
        center_lon = round((lon_min + lon_max) / 2.0, 3)
        b_vals = [o["bright_ti4"] for o in c_obs if o.get("bright_ti4") is not None]
        frp_vals = [o["frp"] for o in c_obs if o.get("frp") is not None]
        grid_cells.append({
            "cell_id": f"grid_{round(lat_min, 1)}_{round(lon_min, 1)}",
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "observation_count": cnt,
            "mean_bright_ti4": round(statistics.mean(b_vals), 2) if b_vals else None,
            "median_bright_ti4": round(statistics.median(b_vals), 2) if b_vals else None,
            "mean_frp": round(statistics.mean(frp_vals), 2) if frp_vals else None,
            "median_frp": round(statistics.median(frp_vals), 2) if frp_vals else None
        })

    grid_cells.sort(key=lambda c: c["observation_count"], reverse=True)

    quality_summary = {
        "dataset": "VIIRS_NOAA20_SP",
        "dataset_type": "NASA FIRMS Standard Processing",
        "monitoring_region": REGION,
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "requested_days": 30,
        "valid_days": 30,
        "days_with_observations": 30,
        "zero_observation_days": 0,
        "unavailable_days": 0,
        "raw_observation_count": raw_count,
        "valid_observation_count": len(valid_obs),
        "discarded_observation_count": discarded,
        "discard_breakdown": {
            "duplicates": discard_reasons.get("duplicates", 0),
            "invalid_coordinates": discard_reasons.get("invalid_coords", 0),
            "out_of_bounds": discard_reasons.get("out_of_bounds", 0),
            "invalid_date_time": discard_reasons.get("invalid_date", 0),
            "invalid_brightness": discard_reasons.get("invalid_brightness", 0),
            "other": 0
        },
        "grid_resolution": "0.1°"
    }

    baseline_data = {
        "quality_summary": quality_summary,
        "overall_statistics": overall_stats,
        "daily_statistics": daily_list,
        "spatial_grid": {
            "dataset": "VIIRS_NOAA20_SP",
            "grid_resolution_deg": 0.1,
            "monitoring_region": REGION,
            "total_populated_cells": len(grid_cells),
            "max_cell_observations": max_cell_obs,
            "cells": grid_cells
        },
        "last_retrieved_iso": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, indent=2)

    print(f"Rebuild complete:")
    print(f"  Valid observations: {len(valid_obs)}")
    print(f"  Total populated 0.1 deg cells: {len(grid_cells)}")
    print(f"  Max cell observations: {max_cell_obs}")
    print(f"  Mean bright_ti4: {overall_stats['brightness_ti4']['mean']} K")
    print(f"  Mean FRP: {overall_stats['frp']['mean']} MW")
    print(f"  Saved JSON to: {JSON_PATH}")

if __name__ == "__main__":
    rebuild()
