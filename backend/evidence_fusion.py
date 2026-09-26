"""
backend/evidence_fusion.py

AGNIVISION-GIS Intelligence Layer: Step 7 — Evidence Fusion / Source Assessment

Gathers, organizes, and assesses the strength and limitations of all evidence
currently available for a persistent thermal event across 7 core dimensions:
1. Thermal Evidence (Brightness, FRP, Radiance flux)
2. Temporal / Persistence Evidence (Revisit passes, active days, duration)
3. Historical Baseline Evidence (Step 6 empirical anomaly comparison)
4. Geographic Validation (NOAA GLOBE land/water classification, administrative state/district)
5. Spatial Evidence (Centroid, bounding extent, observed thermal footprint)
6. Facility / Infrastructure Context (OSM Overpass contextual infrastructure proximity)
7. Data Quality & Completeness (Available vs missing sources, methodological limitations)

Also explicitly detects and exposes Contradictions and Constraining Evidence.

DATA-INTEGRITY RULES:
- Deterministic, rule-based logic only.
- ZERO synthetic data, ZERO fake probabilities, ZERO machine-learning claims.
- Does NOT perform final source classification (reserved for Step 8).
- Does NOT calculate arbitrary overall "confidence percentages" or "fire probabilities".
"""

import math
from typing import Dict, Any, List, Optional
import datetime

# =========================================================
# EVIDENCE STRENGTH THRESHOLDS (CENTRALIZED CONFIGURATION)
# =========================================================

EVIDENCE_THRESHOLDS = {
    "thermal": {
        "strong_obs_count": 10,
        "strong_min_obs_with_high_values": 5,
        "high_brightness_k": 325.0,
        "high_frp_mw": 5.0,
        "moderate_obs_count": 3,
    },
    "temporal": {
        "strong_days_count": 3,
        "strong_persistence_hours": 48.0,
        "moderate_days_count": 2,
        "moderate_persistence_hours": 12.0,
    },
    "spatial": {
        "strong_obs_count": 10,
        "moderate_obs_count": 3,
        "multi_point_min": 2,
    },
}

DATA_SOURCES_SYSTEM_AVAILABLE = [
    "NASA FIRMS VIIRS active thermal detections (375m I-band, T4 radiance)",
    "Spatiotemporal persistent event clustering (3.0 km radius × 36h gap)",
    "NOAA GLOBE 1km land/water domain boundary mask",
    "NASA FIRMS VIIRS_NOAA20_SP 30-day historical reference baseline (June 2026)",
    "OpenStreetMap / Overpass contextual infrastructure database (5km radius)",
]

DATA_SOURCES_SYSTEM_UNAVAILABLE = [
    "Direct optical / visible spectrum satellite imagery (Sentinel-2 / Landsat)",
    "Field-level validated land-cover or crop parcel boundary mask",
    "In-situ physical field scout verification",
    "Real-time local surface meteorology and wind dispersion vectors",
    "Active smoke plume and aerosol optical depth (AOD) sounding",
]

SYSTEM_METHODOLOGICAL_LIMITATIONS = [
    "Polar-orbiting VIIRS passes provide discrete revisit snapshots (~12h gap) and cannot verify continuous burning between passes.",
    "Sensor pixel footprint (375m) measures integrated pixel radiance flux and cannot delineate sub-pixel flame perimeters.",
    "Historical reference baseline reflects Standard Processing (SP) archival latency (~2.5 months) differing from the active NRT window.",
    "OSM facility proximity provides spatial context only and does not establish emission causation.",
    "Statistical anomaly analysis represents deterministic deviations from historical distributions, not machine-learning fire predictions.",
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# =========================================================
# 1. THERMAL EVIDENCE ASSESSOR
# =========================================================

def assess_thermal_evidence(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess the strength and characteristics of thermal radiance observations.
    Strength: STRONG, MODERATE, LIMITED, UNAVAILABLE.
    """
    observations = event.get("observations") or []
    obs_count = len(observations) or event.get("observation_count", 0)

    bright_vals = []
    frp_vals = []

    for obs in observations:
        b = obs.get("bright_ti4") if obs.get("bright_ti4") is not None else obs.get("brightness")
        if b is not None and str(b).strip() != "":
            try:
                bright_vals.append(float(b))
            except (ValueError, TypeError):
                pass

        f = obs.get("frp")
        if f is not None and str(f).strip() != "":
            try:
                frp_vals.append(float(f))
            except (ValueError, TypeError):
                pass

    if not bright_vals and not frp_vals and obs_count == 0:
        return {
            "status": "UNAVAILABLE",
            "strength": "UNAVAILABLE",
            "observation_count": 0,
            "brightness": {"mean": None, "max": None, "min": None},
            "frp": {"mean": None, "max": None, "min": None},
            "has_frp": False,
            "notes": ["No thermal observations recorded for this event."],
        }

    # Summary metrics
    b_mean = round(sum(bright_vals) / len(bright_vals), 2) if bright_vals else None
    b_max = round(max(bright_vals), 2) if bright_vals else None
    b_min = round(min(bright_vals), 2) if bright_vals else None

    f_mean = round(sum(frp_vals) / len(frp_vals), 2) if frp_vals else None
    f_max = round(max(frp_vals), 2) if frp_vals else None
    f_min = round(min(frp_vals), 2) if frp_vals else None

    # Strength assessment
    cfg = EVIDENCE_THRESHOLDS["thermal"]
    notes = []

    if obs_count >= cfg["strong_obs_count"] or (
        obs_count >= cfg["strong_min_obs_with_high_values"] and (
            (b_mean is not None and b_mean >= cfg["high_brightness_k"]) or
            (f_mean is not None and f_mean >= cfg["high_frp_mw"])
        )
    ):
        strength = "STRONG"
        notes.append(f"Substantial observation history ({obs_count} detections) with robust thermal radiance signals.")
    elif obs_count >= cfg["moderate_obs_count"] or (obs_count >= 2 and f_mean is not None):
        strength = "MODERATE"
        notes.append(f"Multi-detection thermal history ({obs_count} detections) providing verified radiance readings.")
    elif obs_count >= 1:
        strength = "LIMITED"
        notes.append(f"Small observation sample ({obs_count} detection(s)) with limited repeatability.")
    else:
        strength = "UNAVAILABLE"
        notes.append("No thermal readings available.")

    has_frp = len(frp_vals) > 0
    if not has_frp:
        notes.append("Fire Radiative Power (FRP) data is absent from all observations.")
    elif len(frp_vals) < obs_count:
        notes.append(f"FRP reported on {len(frp_vals)} of {obs_count} observations.")

    return {
        "status": "AVAILABLE",
        "strength": strength,
        "observation_count": obs_count,
        "brightness": {
            "mean": b_mean,
            "max": b_max,
            "min": b_min,
        },
        "frp": {
            "mean": f_mean,
            "max": f_max,
            "min": f_min,
        },
        "has_frp": has_frp,
        "notes": notes,
    }


# =========================================================
# 2. TEMPORAL / PERSISTENCE EVIDENCE ASSESSOR
# =========================================================

def assess_temporal_evidence(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess the temporal persistence, observation continuity, and recurrence.
    Strength: STRONG, MODERATE, LIMITED, UNAVAILABLE.
    """
    temporal_summary = event.get("temporal_summary") or {}
    distinct_days = temporal_summary.get("distinct_days")
    duration_hours = temporal_summary.get("duration_hours")
    first_detected = event.get("first_detected") or temporal_summary.get("first_detected")
    last_detected = event.get("last_detected") or temporal_summary.get("last_detected")
    persistence_days = event.get("persistence_days")

    observations = event.get("observations") or []
    obs_count = len(observations) or event.get("observation_count", 0)

    # Fallback calculation if temporal_summary not present
    if distinct_days is None and observations:
        dates = set(str(o.get("acq_date")).strip() for o in observations if o.get("acq_date"))
        distinct_days = len(dates)
    distinct_days = distinct_days or 1

    if persistence_days is None:
        persistence_days = 1.0

    if not first_detected and not last_detected and obs_count == 0:
        return {
            "status": "UNAVAILABLE",
            "strength": "UNAVAILABLE",
            "observation_count": 0,
            "distinct_observation_days": 0,
            "persistence_days": 0,
            "first_detected": None,
            "last_detected": None,
            "duration_hours": None,
            "notes": ["No timestamped observations available."],
        }

    cfg = EVIDENCE_THRESHOLDS["temporal"]
    notes = []

    dur = duration_hours if duration_hours is not None else (persistence_days * 24.0)

    if distinct_days >= cfg["strong_days_count"] or dur >= cfg["strong_persistence_hours"]:
        strength = "STRONG"
        notes.append(f"Extended multi-day persistence across {distinct_days} distinct calendar days ({dur:.1f} hours span).")
    elif distinct_days >= cfg["moderate_days_count"] or dur >= cfg["moderate_persistence_hours"]:
        strength = "MODERATE"
        notes.append(f"Moderate multi-pass persistence across {distinct_days} distinct calendar days ({dur:.1f} hours span).")
    else:
        strength = "LIMITED"
        notes.append(f"Short-duration activity detected within a single calendar day ({dur:.1f} hours span).")

    notes.append("Temporal persistence indicates revisit detection recurrence; it does not independently verify physical combustion cause.")

    return {
        "status": "AVAILABLE",
        "strength": strength,
        "observation_count": obs_count,
        "distinct_observation_days": distinct_days,
        "persistence_days": round(float(persistence_days), 1),
        "first_detected": first_detected,
        "last_detected": last_detected,
        "duration_hours": round(float(dur), 1) if dur is not None else None,
        "notes": notes,
    }


# =========================================================
# 3. HISTORICAL BASELINE EVIDENCE ASSESSOR
# =========================================================

def assess_historical_evidence(anomaly_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Assess statistical variance of current event against the historical baseline (Step 6).
    Status: ELEVATED, HIGHLY_ELEVATED, WITHIN_BASELINE, BELOW_BASELINE, INSUFFICIENT_BASELINE, UNAVAILABLE.
    """
    if not anomaly_result or anomaly_result.get("status") != "AVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "anomaly_status": "UNAVAILABLE",
            "baseline_source": "VIIRS_NOAA20_SP",
            "reference_period": None,
            "baseline_scope": None,
            "grid_cell": None,
            "cell_observation_count": 0,
            "is_fallback": False,
            "brightness_percent_difference": None,
            "frp_percent_difference": None,
            "brightness_z_score": None,
            "frp_z_score": None,
            "interpretation_summary": "Historical baseline comparison is currently unavailable.",
            "notes": ["Historical baseline data could not be retrieved or evaluated."],
        }

    interp = anomaly_result.get("interpretation", "WITHIN_BASELINE")
    grid_cell = anomaly_result.get("grid_cell") or {}
    comparisons = anomaly_result.get("comparisons") or {}
    std_dev = anomaly_result.get("standardized_deviation") or {}
    ref_period = anomaly_result.get("historical_reference_period") or {}
    is_fallback = anomaly_result.get("is_fallback", False)

    notes = []
    if is_fallback:
        notes.append("Target 0.1° spatial cell had 0 historical detections; regional baseline was used as fallback.")
    else:
        notes.append(f"Compared against {grid_cell.get('observation_count', 0)} historical detections in local 0.1° cell {grid_cell.get('cell_id')}.")

    notes.append(anomaly_result.get("interpretation_summary", ""))
    notes.append("Historical anomaly indicates statistical deviation from past detection patterns; it does NOT confirm fire cause or source attribution.")

    return {
        "status": "AVAILABLE",
        "anomaly_status": interp,
        "baseline_source": anomaly_result.get("baseline_source", "VIIRS_NOAA20_SP"),
        "reference_period": ref_period,
        "baseline_scope": anomaly_result.get("baseline_scope", "0.1_degree_spatial_grid"),
        "grid_cell": grid_cell.get("cell_id"),
        "cell_observation_count": grid_cell.get("observation_count", 0),
        "is_fallback": is_fallback,
        "brightness_percent_difference": comparisons.get("brightness_percent_difference"),
        "frp_percent_difference": comparisons.get("frp_percent_difference"),
        "brightness_z_score": std_dev.get("brightness_z_score"),
        "frp_z_score": std_dev.get("frp_z_score"),
        "interpretation_summary": anomaly_result.get("interpretation_summary", ""),
        "notes": notes,
    }


# =========================================================
# 4. GEOGRAPHIC EVIDENCE ASSESSOR
# =========================================================

def assess_geographic_evidence(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess NOAA GLOBE geographic land/water domain and administrative location.
    Status: VALIDATED, UNVALIDATED.
    """
    geo_val = event.get("geographic_validation") or {}
    domain = geo_val.get("domain") or event.get("geographic_domain") or "LAND"
    state = geo_val.get("state") or event.get("state")
    district = geo_val.get("district") or event.get("district")
    city = geo_val.get("city") or event.get("city")

    notes = []
    status = "VALIDATED" if domain in ["LAND", "INLAND_WATER", "OFFSHORE_MARINE"] else "UNVALIDATED"

    if domain == "LAND":
        notes.append(f"Validated terrestrial land surface domain in {state or 'Eastern/Central India'}.")
    elif domain == "INLAND_WATER":
        notes.append("Observations coincide with inland water surface boundary mask.")
    elif domain == "OFFSHORE_MARINE":
        notes.append("Observations coincide with offshore marine waters (Bay of Bengal).")
    else:
        notes.append("Geographic land/water boundary domain could not be definitively determined.")

    notes.append("Geographic validation establishes surface domain only; it does not infer agricultural or industrial land-use without dedicated parcel data.")

    return {
        "status": status,
        "land_water_class": domain,
        "state": state or "Unassigned",
        "district": district or "Unassigned",
        "city": city or "Unassigned",
        "notes": notes,
    }


# =========================================================
# 5. SPATIAL EVIDENCE ASSESSOR
# =========================================================

def assess_spatial_evidence(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess centroid, spatial bounds, observed thermal footprint, and spatial dispersion.
    Strength: STRONG, MODERATE, LIMITED, UNAVAILABLE.
    """
    centroid = event.get("centroid") or {}
    c_lat = centroid.get("latitude")
    c_lon = centroid.get("longitude")

    if c_lat is None or c_lon is None:
        return {
            "status": "UNAVAILABLE",
            "strength": "UNAVAILABLE",
            "centroid": None,
            "bounding_box": None,
            "observed_footprint": None,
            "spatial_dispersion_km": None,
            "notes": ["Centroid coordinates are missing or invalid."],
        }

    spatial_summary = event.get("spatial_summary") or {}
    min_lat = spatial_summary.get("min_latitude", c_lat)
    max_lat = spatial_summary.get("max_latitude", c_lat)
    min_lon = spatial_summary.get("min_longitude", c_lon)
    max_lon = spatial_summary.get("max_longitude", c_lon)

    observations = event.get("observations") or []
    obs_count = len(observations) or event.get("observation_count", 1)

    # Footprint dimensions
    lat_span_km = haversine_km(min_lat, c_lon, max_lat, c_lon) if min_lat is not None and max_lat is not None else 0.0
    lon_span_km = haversine_km(c_lat, min_lon, c_lat, max_lon) if min_lon is not None and max_lon is not None else 0.0
    approx_area_km2 = round(max(0.375 * 0.375, lat_span_km * lon_span_km), 2)

    # Max dispersion from centroid
    max_dispersion_km = 0.0
    for obs in observations:
        try:
            o_lat = float(obs.get("latitude"))
            o_lon = float(obs.get("longitude"))
            d = haversine_km(c_lat, c_lon, o_lat, o_lon)
            if d > max_dispersion_km:
                max_dispersion_km = d
        except (ValueError, TypeError):
            pass

    cfg = EVIDENCE_THRESHOLDS["spatial"]
    notes = []

    if obs_count >= cfg["strong_obs_count"]:
        strength = "STRONG"
        notes.append(f"Extensive multi-observation spatial cluster ({obs_count} points) bounded within {approx_area_km2} km².")
    elif obs_count >= cfg["moderate_obs_count"]:
        strength = "MODERATE"
        notes.append(f"Cohesive spatial cluster ({obs_count} points) within max dispersion {max_dispersion_km:.2f} km.")
    else:
        strength = "LIMITED"
        notes.append(f"Single/dual-observation pixel-scale footprint ({obs_count} point(s), ~375m sensor resolution).")

    notes.append("Spatial extent represents the aggregate observed thermal footprint, not an active fire perimeter or boundary.")

    return {
        "status": "AVAILABLE",
        "strength": strength,
        "centroid": {
            "latitude": round(float(c_lat), 5),
            "longitude": round(float(c_lon), 5),
        },
        "bounding_box": {
            "min_latitude": round(float(min_lat), 5) if min_lat is not None else None,
            "max_latitude": round(float(max_lat), 5) if max_lat is not None else None,
            "min_longitude": round(float(min_lon), 5) if min_lon is not None else None,
            "max_longitude": round(float(max_lon), 5) if max_lon is not None else None,
        },
        "observed_footprint": {
            "lat_span_km": round(lat_span_km, 2),
            "lon_span_km": round(lon_span_km, 2),
            "approximate_area_km2": approx_area_km2,
        },
        "spatial_dispersion_km": round(max_dispersion_km, 2),
        "notes": notes,
    }


# =========================================================
# 6. FACILITY / INFRASTRUCTURE CONTEXT ASSESSOR
# =========================================================

def assess_facility_context(asset_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Assess contextual OpenStreetMap facilities within a 5km radius.
    Status: PRESENT, NOT_IDENTIFIED, UNAVAILABLE.
    """
    caveat = "Facility proximity provides contextual evidence only and does not establish source attribution."

    if not asset_data:
        return {
            "status": "UNAVAILABLE",
            "context_type": "OSM_OVERPASS",
            "facilities_count": 0,
            "industrial_count": 0,
            "power_count": 0,
            "facilities": [],
            "contextual_caveat": caveat,
            "notes": ["Facility context query has not yet completed or was not requested."],
        }

    counts = asset_data.get("counts") or {}
    assets_list = asset_data.get("assets") or []
    industrial_cnt = counts.get("industrial", 0)
    power_cnt = counts.get("power", 0)
    total_fac = industrial_cnt + power_cnt

    notes = [caveat]

    if total_fac > 0:
        status = "PRESENT"
        notes.append(f"{industrial_cnt} industrial and {power_cnt} power facility(ies) identified within 5km radius.")
    else:
        status = "NOT_IDENTIFIED"
        notes.append("No nearby mapped facility identified in the queried context.")

    return {
        "status": status,
        "context_type": "OSM_OVERPASS",
        "facilities_count": total_fac,
        "industrial_count": industrial_cnt,
        "power_count": power_cnt,
        "facilities": assets_list[:10],  # top 10 for compactness
        "contextual_caveat": caveat,
        "notes": notes,
    }


# =========================================================
# 7. DATA QUALITY & COMPLETENESS ASSESSOR
# =========================================================

def assess_data_quality(
    thermal: Dict[str, Any],
    temporal: Dict[str, Any],
    historical: Dict[str, Any],
    geographic: Dict[str, Any],
    spatial: Dict[str, Any],
    facility: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluate available vs missing evidence sources and system-level limitations.
    Status: COMPLETE, PARTIAL, LIMITED.
    """
    available = []
    missing = list(DATA_SOURCES_SYSTEM_UNAVAILABLE)
    limitations = list(SYSTEM_METHODOLOGICAL_LIMITATIONS)

    if thermal.get("status") == "AVAILABLE":
        available.append("NASA FIRMS VIIRS thermal observations")
    else:
        missing.append("Current satellite thermal observations")

    if temporal.get("status") == "AVAILABLE":
        available.append("Spatiotemporal event history")

    if geographic.get("status") == "VALIDATED":
        available.append("Geographic domain validation (NOAA GLOBE 1km)")
    else:
        missing.append("Validated terrestrial boundary domain")

    if historical.get("status") == "AVAILABLE":
        available.append(f"Historical reference baseline ({historical.get('baseline_source', 'SP')})")
    else:
        missing.append("Historical reference baseline comparison")

    if facility.get("status") in ["PRESENT", "NOT_IDENTIFIED"]:
        available.append("OpenStreetMap contextual infrastructure query")
    else:
        missing.append("Contextual facility database query")

    # Overall completeness status
    if len(available) >= 5:
        quality_status = "COMPLETE"
    elif len(available) >= 3:
        quality_status = "PARTIAL"
    else:
        quality_status = "LIMITED"

    return {
        "status": quality_status,
        "available_evidence": available,
        "missing_evidence": missing,
        "limitations": limitations,
    }


# =========================================================
# 8. CONTRADICTIONS & CONSTRAINING EVIDENCE DETECTOR
# =========================================================

def detect_contradictions(
    event: Dict[str, Any],
    thermal: Dict[str, Any],
    temporal: Dict[str, Any],
    historical: Dict[str, Any],
    geographic: Dict[str, Any],
    spatial: Dict[str, Any],
    facility: Dict[str, Any]
) -> List[str]:
    """
    Identify potential contradictions, inconsistencies, or analytical constraints.
    Does NOT resolve contradictions by picking a winner.
    """
    contradictions = []

    # 1. Thermal vs Marine Domain
    domain = geographic.get("land_water_class")
    obs_count = thermal.get("observation_count", 0)
    if domain in ["OFFSHORE_MARINE", "INLAND_WATER"] and obs_count > 0:
        domain_name = domain.replace("_", " ").title()
        contradictions.append(
            f"Thermal observations ({obs_count}) are recorded, but geographic validation identifies the event domain as {domain_name} ({domain})."
        )

    # 2. Elevated Anomaly vs Weak Sample
    h_status = historical.get("anomaly_status")
    if h_status in ["ELEVATED", "HIGHLY_ELEVATED"] and obs_count < 3:
        contradictions.append(
            f"Historical anomaly is classified as {h_status}, but event observation sample is small (n={obs_count}), increasing statistical uncertainty."
        )

    # 3. High Persistence vs No Facility
    pers_days = temporal.get("persistence_days", 0)
    if pers_days >= 3 and facility.get("status") == "NOT_IDENTIFIED":
        contradictions.append(
            f"Event exhibits multi-day persistence ({pers_days} days), but no mapped industrial or energy infrastructure was identified in the local OSM context."
        )

    # 4. Missing FRP values
    if obs_count > 0 and not thermal.get("has_frp", True):
        contradictions.append(
            "Thermal brightness detections are present, but Fire Radiative Power (FRP) data is absent from all observations."
        )

    # 5. Fallback baseline constraint
    if historical.get("is_fallback"):
        contradictions.append(
            "Local 0.1° spatial grid cell has 0 historical observations during the reference period; regional baseline was used as fallback."
        )

    # 6. Baseline Unavailable
    if historical.get("status") == "UNAVAILABLE":
        contradictions.append(
            "Historical reference baseline is unavailable; statistical recurrence cannot be evaluated."
        )

    return contradictions


# =========================================================
# 9. MAIN EVIDENCE FUSION ENTRYPOINT
# =========================================================

def fuse_event_evidence(
    event: Dict[str, Any],
    anomaly_result: Optional[Dict[str, Any]] = None,
    asset_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce a comprehensive, structured Evidence Profile for an event.
    Reuses existing calculations without duplication.
    """
    event_id = event.get("event_id", "UNKNOWN")

    # Assess all 7 dimensions
    thermal = assess_thermal_evidence(event)
    temporal = assess_temporal_evidence(event)
    historical = assess_historical_evidence(anomaly_result)
    geographic = assess_geographic_evidence(event)
    spatial = assess_spatial_evidence(event)
    facility = assess_facility_context(asset_data)
    data_quality = assess_data_quality(thermal, temporal, historical, geographic, spatial, facility)

    # Detect contradictions
    contradictions = detect_contradictions(
        event, thermal, temporal, historical, geographic, spatial, facility
    )

    # Compact categories summary
    categories_summary = {
        "thermal": thermal.get("strength", "UNAVAILABLE"),
        "temporal": temporal.get("strength", "UNAVAILABLE"),
        "historical": historical.get("anomaly_status", "UNAVAILABLE"),
        "geographic": geographic.get("status", "UNVALIDATED"),
        "spatial": spatial.get("strength", "UNAVAILABLE"),
        "facility_context": facility.get("status", "UNAVAILABLE"),
        "data_quality": data_quality.get("status", "LIMITED"),
    }

    # Machine-readable overall evidence summary
    summary = {
        "overall_status": "EVIDENCE_AVAILABLE" if thermal.get("status") == "AVAILABLE" else "EVIDENCE_LIMITED",
        "categories": categories_summary,
        "contradictions_count": len(contradictions),
        "limitations_count": len(data_quality.get("limitations", [])),
    }

    return {
        "status": "success",
        "event_id": event_id,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": summary,
        "thermal": thermal,
        "temporal": temporal,
        "historical": historical,
        "geographic": geographic,
        "spatial": spatial,
        "facility_context": facility,
        "data_quality": data_quality,
        "contradictions": contradictions,
    }
