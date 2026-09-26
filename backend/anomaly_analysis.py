"""
AGNIVISION-GIS — ANOMALY ANALYSIS ENGINE
Step 6: Event-vs-Historical-Baseline Anomaly Analysis

Features:
- Deterministic event-vs-historical baseline comparative statistics
- Cell-level spatial mapping against 0.1° x 0.1° historical reference grid
- Transparent difference and percentage difference calculations
- Standardized deviations (z-scores) where sample variance is valid
- Documented rule-based anomaly interpretations (WITHIN_BASELINE, ELEVATED, HIGHLY_ELEVATED, BELOW_BASELINE, INSUFFICIENT_BASELINE)
- Clear data-integrity guards: Zero ML claims, zero predictive claims, zero synthetic values
"""

import datetime
import logging
import math
import os
import statistics
from typing import Dict, List, Optional, Tuple, Any

from historical_baseline import (
    historical_baseline_manager,
    MONITORING_REGION,
    GRID_RESOLUTION_DEG,
    SOURCE_DATASET,
    SOURCE_DATASET_TYPE
)

logger = logging.getLogger("agnivision.anomaly")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# =========================================================
# DOCUMENTED THRESHOLDS
# =========================================================

ANOMALY_THRESHOLDS = {
    "highly_elevated": {
        "brightness_pct_diff_min": 15.0,
        "brightness_z_score_min": 2.0,
        "frp_pct_diff_min": 50.0,
        "frp_z_score_min": 2.0
    },
    "elevated": {
        "brightness_pct_diff_min": 5.0,
        "brightness_z_score_min": 1.0,
        "frp_pct_diff_min": 25.0,
        "frp_z_score_min": 1.0
    },
    "below_baseline": {
        "brightness_pct_diff_max": -5.0,
        "brightness_z_score_max": -1.0
    },
    "min_observations_for_z_score": 3
}

DISCLAIMER_LIMITATIONS = [
    "Statistical thermal deviation only; does not infer combustion cause, fire confirmation, or physical spread.",
    "Historical reference period reflects NASA Standard Processing (SP) archival latency (~2.5 months) and differs from the active NRT observation window.",
    "0.1° spatial grid resolution (~11 km) encompasses local surroundings beyond the sub-pixel sensor footprint.",
    "Calculations are strictly deterministic statistical differences, not machine learning predictions or fire probabilities."
]


# =========================================================
# 1. CURRENT EVENT METRICS
# =========================================================

def calculate_event_metrics(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts and calculates normalized summary metrics from a current event's observations.
    """
    observations = event_data.get("observations") or []
    if not observations:
        return {
            "observation_count": 0,
            "mean_brightness": None,
            "median_brightness": None,
            "max_brightness": None,
            "mean_frp": None,
            "median_frp": None,
            "max_frp": None,
            "observation_days": 0,
            "persistence_days": 0
        }

    b_vals = []
    f_vals = []
    dates = set()

    for obs in observations:
        b = obs.get("bright_ti4") or obs.get("brightness")
        if b is not None:
            try:
                b_float = float(b)
                if b_float > 0:
                    b_vals.append(b_float)
            except (ValueError, TypeError):
                pass

        f = obs.get("frp")
        if f is not None and f != "":
            try:
                f_float = float(f)
                f_vals.append(f_float)
            except (ValueError, TypeError):
                pass

        d = obs.get("acq_date")
        if d:
            dates.add(str(d).strip())

    return {
        "observation_count": len(observations),
        "mean_brightness": round(statistics.mean(b_vals), 2) if b_vals else None,
        "median_brightness": round(statistics.median(b_vals), 2) if b_vals else None,
        "max_brightness": round(max(b_vals), 2) if b_vals else None,
        "mean_frp": round(statistics.mean(f_vals), 2) if f_vals else None,
        "median_frp": round(statistics.median(f_vals), 2) if f_vals else None,
        "max_frp": round(max(f_vals), 2) if f_vals else None,
        "observation_days": len(dates),
        "persistence_days": event_data.get("persistence_days", len(dates))
    }


# =========================================================
# 2. SPATIAL GRID MAPPING
# =========================================================

def get_event_spatial_grid_cell(
    lat: float,
    lon: float,
    region: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Maps an event centroid (lat, lon) to the corresponding 0.1° x 0.1° grid cell.
    Returns (cell_id, cell_metadata) or (None, None) if outside monitoring region.
    """
    target_region = region if (isinstance(region, dict) and isinstance(region.get("west"), (int, float))) else MONITORING_REGION
    west = target_region["west"]
    south = target_region["south"]
    east = target_region["east"]
    north = target_region["north"]

    if not (west <= lon <= east and south <= lat <= north):
        return None, None

    lat_idx = int(math.floor((lat - south) / GRID_RESOLUTION_DEG))
    lon_idx = int(math.floor((lon - west) / GRID_RESOLUTION_DEG))

    lat_min = round(south + (lat_idx * GRID_RESOLUTION_DEG), 2)
    lat_max = round(lat_min + GRID_RESOLUTION_DEG, 2)
    lon_min = round(west + (lon_idx * GRID_RESOLUTION_DEG), 2)
    lon_max = round(lon_min + GRID_RESOLUTION_DEG, 2)

    cell_id = f"grid_{round(lat_min, 1)}_{round(lon_min, 1)}"
    meta = {
        "cell_id": cell_id,
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
        "center_lat": round((lat_min + lat_max) / 2.0, 3),
        "center_lon": round((lon_min + lon_max) / 2.0, 3)
    }

    return cell_id, meta


# =========================================================
# 3. ANOMALY ANALYSIS ENGINE
# =========================================================

def analyze_event_anomaly(
    event_data: Dict[str, Any],
    baseline_mgr=None
) -> Dict[str, Any]:
    """
    Performs event-vs-historical-baseline anomaly comparison for a given thermal event.
    """
    if baseline_mgr is None:
        baseline_mgr = historical_baseline_manager

    mgr_reg = getattr(baseline_mgr, "region", None)
    target_region = mgr_reg if (isinstance(mgr_reg, dict) and isinstance(mgr_reg.get("west"), (int, float))) else MONITORING_REGION
    event_id = event_data.get("event_id", "UNKNOWN")

    # 1. Check baseline readiness
    if not baseline_mgr.is_loaded:
        return {
            "event_id": event_id,
            "status": "UNAVAILABLE",
            "interpretation": "INSUFFICIENT_BASELINE",
            "reason": baseline_mgr.error_message or "Historical baseline unavailable",
            "baseline_source": SOURCE_DATASET,
            "limitations": DISCLAIMER_LIMITATIONS
        }

    # 2. Extract current event metrics
    curr_metrics = calculate_event_metrics(event_data)
    centroid = (
        event_data.get("centroid") or
        (event_data.get("spatial_summary") or {}).get("centroid") or
        {}
    )

    try:
        lat = float(centroid.get("latitude"))
        lon = float(centroid.get("longitude"))
    except (ValueError, TypeError):
        return {
            "event_id": event_id,
            "status": "UNAVAILABLE",
            "interpretation": "INSUFFICIENT_BASELINE",
            "reason": "Event centroid coordinates unavailable or malformed",
            "baseline_source": SOURCE_DATASET,
            "current_metrics": curr_metrics,
            "limitations": DISCLAIMER_LIMITATIONS
        }

    # 3. Map centroid to spatial grid cell
    cell_id, cell_meta = get_event_spatial_grid_cell(lat, lon, region=target_region)
    if not cell_id:
        reg_name = target_region.get("name", "Monitoring Region")
        reg_bounds = f"{target_region.get('west', 67)}°E–{target_region.get('east', 98)}°E, {target_region.get('south', 7)}°N–{target_region.get('north', 38)}°N"
        return {
            "event_id": event_id,
            "status": "UNAVAILABLE",
            "interpretation": "INSUFFICIENT_BASELINE",
            "reason": f"Spatial historical baseline unavailable (event centroid lies outside the {reg_name} {reg_bounds} monitoring region)",
            "baseline_source": SOURCE_DATASET,
            "current_metrics": curr_metrics,
            "limitations": DISCLAIMER_LIMITATIONS
        }

    # 4. Retrieve historical observations for cell
    cell_obs = baseline_mgr.get_cell_observations(cell_id)
    cell_obs_count = len(cell_obs)

    is_fallback = False
    fallback_reason = None
    baseline_scope = "0.1_degree_spatial_grid"

    # Baseline metrics container
    base_metrics = {}
    base_b_std: Optional[float] = None
    base_frp_std: Optional[float] = None

    if cell_obs_count >= 1:
        # Spatial cell has observations
        b_vals = [o["bright_ti4"] for o in cell_obs if o.get("bright_ti4") is not None]
        f_vals = [o["frp"] for o in cell_obs if o.get("frp") is not None]

        base_metrics = {
            "observation_count": cell_obs_count,
            "mean_brightness": round(statistics.mean(b_vals), 2) if b_vals else None,
            "median_brightness": round(statistics.median(b_vals), 2) if b_vals else None,
            "max_brightness": round(max(b_vals), 2) if b_vals else None,
            "mean_frp": round(statistics.mean(f_vals), 2) if f_vals else None,
            "median_frp": round(statistics.median(f_vals), 2) if f_vals else None,
            "max_frp": round(max(f_vals), 2) if f_vals else None
        }

        if len(b_vals) >= ANOMALY_THRESHOLDS["min_observations_for_z_score"]:
            base_b_std = round(statistics.stdev(b_vals), 2)
        if len(f_vals) >= ANOMALY_THRESHOLDS["min_observations_for_z_score"]:
            base_frp_std = round(statistics.stdev(f_vals), 2)

    else:
        # Cell has 0 observations during reference period -> Explicit Regional Fallback
        is_fallback = True
        baseline_scope = "regional_fallback"
        fallback_reason = "Historical cell has no observed thermal activity during the reference period"

        regional_stats = baseline_mgr.overall_statistics
        regional_b = regional_stats.get("brightness_ti4") or {}
        regional_f = regional_stats.get("frp") or {}

        base_metrics = {
            "observation_count": regional_stats.get("observation_count", 0),
            "mean_brightness": regional_b.get("mean"),
            "median_brightness": regional_b.get("median"),
            "max_brightness": regional_b.get("max"),
            "mean_frp": regional_f.get("mean"),
            "median_frp": regional_f.get("median"),
            "max_frp": regional_f.get("max")
        }

        # Regional std dev
        all_obs = baseline_mgr.get_valid_observations()
        reg_b_vals = [o["bright_ti4"] for o in all_obs if o.get("bright_ti4") is not None]
        reg_f_vals = [o["frp"] for o in all_obs if o.get("frp") is not None]
        if len(reg_b_vals) >= 3:
            base_b_std = round(statistics.stdev(reg_b_vals), 2)
        if len(reg_f_vals) >= 3:
            base_frp_std = round(statistics.stdev(reg_f_vals), 2)

    # 5. Calculate Differences and Percentage Differences
    curr_b_mean = curr_metrics.get("mean_brightness")
    base_b_mean = base_metrics.get("mean_brightness")

    curr_f_mean = curr_metrics.get("mean_frp")
    base_f_mean = base_metrics.get("mean_frp")

    b_diff = None
    b_pct_diff = None
    if curr_b_mean is not None and base_b_mean is not None:
        b_diff = round(curr_b_mean - base_b_mean, 2)
        if base_b_mean > 0:
            b_pct_diff = round(((curr_b_mean - base_b_mean) / base_b_mean) * 100.0, 2)

    f_diff = None
    f_pct_diff = None
    if curr_f_mean is not None and base_f_mean is not None:
        f_diff = round(curr_f_mean - base_f_mean, 2)
        if base_f_mean > 0:
            f_pct_diff = round(((curr_f_mean - base_f_mean) / base_f_mean) * 100.0, 2)

    activity_ratio = None
    if base_metrics.get("observation_count") and base_metrics["observation_count"] > 0:
        activity_ratio = round(curr_metrics["observation_count"] / base_metrics["observation_count"], 2)

    # 6. Standardized Deviations (Z-Scores)
    b_z_score = None
    if curr_b_mean is not None and base_b_mean is not None and base_b_std is not None and base_b_std > 0:
        b_z_score = round((curr_b_mean - base_b_mean) / base_b_std, 2)

    f_z_score = None
    if curr_f_mean is not None and base_f_mean is not None and base_frp_std is not None and base_frp_std > 0:
        f_z_score = round((curr_f_mean - base_f_mean) / base_frp_std, 2)

    # 7. Documented Anomaly Interpretation
    if cell_obs_count > 0 and cell_obs_count < ANOMALY_THRESHOLDS["min_observations_for_z_score"] and not is_fallback:
        interpretation = "INSUFFICIENT_BASELINE"
        interpretation_summary = f"Spatial cell has only {cell_obs_count} historical observation(s); minimum 3 required for reliable statistical baseline comparison."
    elif b_pct_diff is not None:
        # Check highly elevated
        if b_pct_diff >= ANOMALY_THRESHOLDS["highly_elevated"]["brightness_pct_diff_min"] or (b_z_score is not None and b_z_score >= ANOMALY_THRESHOLDS["highly_elevated"]["brightness_z_score_min"]):
            interpretation = "HIGHLY_ELEVATED"
            z_str = f" (+{b_z_score}σ)" if b_z_score is not None else ""
            interpretation_summary = f"Mean brightness is {b_pct_diff}% above the historical baseline{z_str}, exceeding typical historical variance."
        elif b_pct_diff >= ANOMALY_THRESHOLDS["elevated"]["brightness_pct_diff_min"] or (b_z_score is not None and b_z_score >= ANOMALY_THRESHOLDS["elevated"]["brightness_z_score_min"]):
            interpretation = "ELEVATED"
            z_str = f" (+{b_z_score}σ)" if b_z_score is not None else ""
            interpretation_summary = f"Mean brightness is {b_pct_diff}% above the historical baseline{z_str}."
        elif b_pct_diff <= ANOMALY_THRESHOLDS["below_baseline"]["brightness_pct_diff_max"] and (b_z_score is None or b_z_score <= ANOMALY_THRESHOLDS["below_baseline"]["brightness_z_score_max"]):
            interpretation = "BELOW_BASELINE"
            z_str = f" ({b_z_score}σ)" if b_z_score is not None else ""
            interpretation_summary = f"Mean brightness is {abs(b_pct_diff)}% below the historical baseline{z_str}."
        else:
            interpretation = "WITHIN_BASELINE"
            z_str = f" ({b_z_score}σ)" if b_z_score is not None else ""
            interpretation_summary = f"Thermal measurements are within historical statistical baseline variance{z_str} ({b_pct_diff:+0.1f}%)."
    else:
        interpretation = "INSUFFICIENT_BASELINE"
        interpretation_summary = "Thermal difference could not be computed from available observations."

    return {
        "event_id": event_id,
        "status": "AVAILABLE",
        "baseline_source": SOURCE_DATASET,
        "baseline_dataset_type": SOURCE_DATASET_TYPE,
        "baseline_scope": baseline_scope,
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "fallback_label": "Regional fallback baseline" if is_fallback else None,
        "grid_cell": {
            **cell_meta,
            "observation_count": cell_obs_count
        },
        "historical_reference_period": {
            "start": baseline_mgr.quality_summary.get("period_start"),
            "end": baseline_mgr.quality_summary.get("period_end"),
            "days": baseline_mgr.quality_summary.get("requested_days")
        },
        "current_event_period": {
            "first_detected": event_data.get("first_detected"),
            "last_detected": event_data.get("last_detected"),
            "persistence_days": curr_metrics.get("persistence_days")
        },
        "current_metrics": curr_metrics,
        "baseline_metrics": base_metrics,
        "comparisons": {
            "brightness_difference": b_diff,
            "brightness_percent_difference": b_pct_diff,
            "frp_difference": f_diff,
            "frp_percent_difference": f_pct_diff,
            "observation_activity_ratio": activity_ratio
        },
        "standardized_deviation": {
            "brightness_z_score": b_z_score,
            "frp_z_score": f_z_score,
            "historical_brightness_std": base_b_std,
            "historical_frp_std": base_frp_std,
            "available": b_z_score is not None or f_z_score is not None,
            "note": "Standardized deviation unavailable: minimum 3 historical observations required" if (b_z_score is None and f_z_score is None) else None
        },
        "interpretation": interpretation,
        "interpretation_summary": interpretation_summary,
        "thresholds": {
            "within_baseline": "|diff%| < 5.0% and |z| < 1.0",
            "elevated": "diff% >= 5.0% or z >= 1.0",
            "highly_elevated": "diff% >= 15.0% or z >= 2.0",
            "below_baseline": "diff% <= -5.0% and z <= -1.0"
        },
        "limitations": DISCLAIMER_LIMITATIONS
    }
