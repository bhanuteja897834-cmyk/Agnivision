"""
AGNIVISION-GIS: Step 3 — Evidence-Based Event Assessment Layer

Synthesizes multiple operational signals to generate an explainable, multi-source
source and priority assessment for a persistent thermal event:
 1. Random Forest ML prediction & class probability distribution
 2. NASA FIRMS thermal radiance signals (brightness, FRP, observation counts)
 3. Spatiotemporal persistence & revisit dynamics (active days, duration, detections)
 4. Historical baseline anomaly comparison (statistical deviations from 0.1° reference baseline)
 5. OpenStreetMap contextual infrastructure (industrial, energy, substation proximity within 5km)
 6. NOAA GLOBE land/water geographic domain validation

ASSESSMENT CATEGORIES:
 - HIGH_PRIORITY_THERMAL_EVENT: Elevated radiative energy, high FRP/brightness, and/or multi-pass persistence
 - LIKELY_INDUSTRIAL_HEAT: Stationary multi-day persistence and/or mapped industrial infrastructure proximity
 - LIKELY_AGRICULTURAL_BURNING: Agricultural ML classification with episodic short duration on terrestrial land
 - LIKELY_WILDLAND_THERMAL_EVENT: Forest ML classification with active thermal radiance and terrestrial land domain
 - LOW_CONFIDENCE_THERMAL_ANOMALY: Single-pass, low FRP (<2.0 MW), within-baseline, low ML confidence (potential false alarm)
 - UNRESOLVED: Conflicting evidence, flat probability distribution, or critical data gaps

THRESHOLDS SOURCED STRICTLY FROM:
 - evidence_fusion.py: EVIDENCE_THRESHOLDS (high_frp: 5.0 MW, high_brightness: 325.0 K, strong_days: 3, strong_obs: 10)
 - classification_engine.py: CLASSIFICATION_THRESHOLDS (facility_radius: 5000m, min_industrial_obs: 3, min_days: 2, max_footprint: 400 km²)
 - anomaly_analysis.py: ANOMALY_THRESHOLDS (highly_elevated: FRP diff >= 50% / z >= 2.0, elevated: FRP diff >= 25% / z >= 1.0)
"""

import math
import logging
from typing import Dict, Any, List, Optional, Tuple

from evidence_fusion import EVIDENCE_THRESHOLDS, fuse_event_evidence
from classification_engine import CLASSIFICATION_THRESHOLDS
from anomaly_analysis import ANOMALY_THRESHOLDS, analyze_event_anomaly
from historical_baseline import get_historical_baseline_manager
from ml_model import ml_model_service

logger = logging.getLogger("agnivision.event_assessment")

# Approved 6 Operational Categories (Step 1 schema)
CATEGORY_FOREST_FIRE = "FOREST_FIRE"
CATEGORY_AGRICULTURAL_FIRE = "AGRICULTURAL_FIRE"
CATEGORY_GAS_FLARE = "GAS_FLARE"
CATEGORY_INDUSTRIAL_FIRE = "INDUSTRIAL_FIRE"
CATEGORY_OTHER_THERMAL_EVENT = "OTHER_THERMAL_EVENT"
CATEGORY_UNKNOWN = "UNKNOWN"

# Backward-compatibility aliases
ASSESSMENT_HIGH_PRIORITY = CATEGORY_FOREST_FIRE
ASSESSMENT_INDUSTRIAL_HEAT = CATEGORY_GAS_FLARE
ASSESSMENT_AGRICULTURAL = CATEGORY_AGRICULTURAL_FIRE
ASSESSMENT_WILDLAND = CATEGORY_FOREST_FIRE
ASSESSMENT_LOW_CONFIDENCE = CATEGORY_OTHER_THERMAL_EVENT
ASSESSMENT_UNRESOLVED = CATEGORY_UNKNOWN

# Sourced Threshold Constants
HIGH_FRP_MW = EVIDENCE_THRESHOLDS["thermal"]["high_frp_mw"]                 # 5.0 MW
HIGH_BRIGHTNESS_K = EVIDENCE_THRESHOLDS["thermal"]["high_brightness_k"]     # 325.0 K
MIN_ACTIVE_FRP_MW = CLASSIFICATION_THRESHOLDS["active_fire"]["min_frp_mw"]  # 1.0 MW
MIN_ACTIVE_BRIGHT_K = CLASSIFICATION_THRESHOLDS["active_fire"]["min_brightness_k"] # 315.0 K

STRONG_DAYS_COUNT = EVIDENCE_THRESHOLDS["temporal"]["strong_days_count"]     # 3 days
MODERATE_DAYS_COUNT = EVIDENCE_THRESHOLDS["temporal"]["moderate_days_count"] # 2 days
STRONG_PERSIST_HOURS = EVIDENCE_THRESHOLDS["temporal"]["strong_persistence_hours"] # 48.0 h
MODERATE_PERSIST_HOURS = EVIDENCE_THRESHOLDS["temporal"]["moderate_persistence_hours"] # 12.0 h

STRONG_OBS_COUNT = EVIDENCE_THRESHOLDS["thermal"]["strong_obs_count"]        # 10 detections
MODERATE_OBS_COUNT = EVIDENCE_THRESHOLDS["thermal"]["moderate_obs_count"]    # 3 detections

MAX_INDUSTRIAL_FOOTPRINT_KM2 = CLASSIFICATION_THRESHOLDS["industrial"]["max_footprint_km2"] # 400.0 km²
FACILITY_RADIUS_M = CLASSIFICATION_THRESHOLDS["industrial"]["facility_radius_m"]           # 5000 m

LOW_CONFIDENCE_FRP_MAX_MW = 2.0  # Documented threshold for marginal/sub-threshold thermal emission


def assess_event(
    event: Dict[str, Any],
    anomaly_result: Optional[Dict[str, Any]] = None,
    asset_data: Optional[Dict[str, Any]] = None,
    baseline_manager=None
) -> Dict[str, Any]:
    """
    Evaluates multi-source evidence across ML, FIRMS thermal signals, temporal persistence,
    historical anomaly comparison, and contextual OSM infrastructure to produce an
    explainable event assessment.
    """
    event_id = event.get("event_id") or "UNKNOWN_EVENT"

    # 1. ML Prediction
    ml_result = ml_model_service.predict_event(event)
    ml_class = ml_result.get("predicted_class") or "UNAVAILABLE"
    ml_confidence = ml_result.get("confidence") or 0.0
    ml_probs = ml_result.get("probabilities") or {}

    # 2. Historical Baseline Anomaly
    if anomaly_result is None:
        mgr = baseline_manager or get_historical_baseline_manager()
        try:
            if mgr.is_loaded:
                anomaly_result = analyze_event_anomaly(event, mgr)
        except Exception as e:
            logger.warning(f"[ASSESSMENT] Could not run anomaly analysis for {event_id}: {e}")
            anomaly_result = None

    anomaly_category = (anomaly_result or {}).get("interpretation") or "UNAVAILABLE"
    anomaly_status = (anomaly_result or {}).get("status") or "UNAVAILABLE"
    frp_diff_pct = (anomaly_result or {}).get("comparisons", {}).get("frp", {}).get("percent_difference")

    # 3. FIRMS Thermal Metrics
    observations = event.get("observations") or []
    obs_count = len(observations) or int(event.get("observation_count") or 1)
    
    frp_summary = event.get("frp_summary") or {}
    max_frp = float(frp_summary.get("max") or (observations[0].get("frp") if observations else 0.0) or 0.0)
    mean_frp = float(frp_summary.get("mean") or max_frp)

    brightness_summary = event.get("brightness_summary") or {}
    max_brightness = float(brightness_summary.get("max") or (observations[0].get("brightness") if observations else 0.0) or 0.0)
    mean_brightness = float(brightness_summary.get("mean") or max_brightness)

    # 4. Temporal & Persistence Metrics
    persistence_days = float(event.get("persistence_days") or 1.0)
    distinct_dates = set()
    for o in observations:
        if o.get("acq_date"):
            distinct_dates.add(o["acq_date"])
    distinct_days = max(len(distinct_dates), int(persistence_days), 1)

    duration_hours = 0.0
    first_det = event.get("first_detected")
    last_det = event.get("last_detected")
    if first_det and last_det:
        try:
            import datetime
            dt1 = datetime.datetime.fromisoformat(first_det.replace("Z", "+00:00"))
            dt2 = datetime.datetime.fromisoformat(last_det.replace("Z", "+00:00"))
            duration_hours = max(0.0, (dt2 - dt1).total_seconds() / 3600.0)
        except Exception:
            duration_hours = (persistence_days - 1.0) * 24.0

    # 5. Spatial Footprint
    footprint_km2 = float(event.get("spatial_summary", {}).get("observed_footprint", {}).get("approximate_area_km2") or 0.0)
    if not footprint_km2 and observations:
        footprint_km2 = float(event.get("spatial_summary", {}).get("approximate_area_km2") or 0.0)

    # 6. OSM Infrastructure Proximity
    ind_count = 0
    power_count = 0
    if asset_data and isinstance(asset_data, dict):
        ind_count = len(asset_data.get("industrial", []))
        power_count = len(asset_data.get("power", []))
    total_infra_count = ind_count + power_count

    # 7. Geographic Domain
    geo_val = event.get("geographic_validation") or {}
    land_water_class = geo_val.get("land_water_class") or geo_val.get("domain") or "LAND"
    state = geo_val.get("state") or event.get("state") or "India"

    # Assemble Evidence Dictionary
    evidence_dict = {
        "thermal": {
            "observation_count": obs_count,
            "max_frp_mw": round(max_frp, 2),
            "mean_frp_mw": round(mean_frp, 2),
            "max_brightness_k": round(max_brightness, 2),
            "mean_brightness_k": round(mean_brightness, 2),
            "high_frp_threshold_mw": HIGH_FRP_MW,
            "high_brightness_threshold_k": HIGH_BRIGHTNESS_K,
        },
        "temporal": {
            "distinct_days": distinct_days,
            "persistence_days": persistence_days,
            "duration_hours": round(duration_hours, 1),
            "multi_pass_confirmed": obs_count >= 2,
        },
        "historical_anomaly": {
            "status": anomaly_status,
            "category": anomaly_category,
            "frp_difference_pct": round(frp_diff_pct, 1) if frp_diff_pct is not None else None,
        },
        "osm_context": {
            "search_radius_m": FACILITY_RADIUS_M,
            "industrial_facility_count": ind_count,
            "power_infrastructure_count": power_count,
            "total_infrastructure_count": total_infra_count,
        },
        "geographic": {
            "land_water_class": land_water_class,
            "state": state,
        },
        "ml_inference": {
            "predicted_class": ml_class,
            "confidence": ml_confidence,
            "probabilities": ml_probs,
        }
    }

    # =======================================================================
    # MULTI-SOURCE ASSESSMENT RULE ENGINE (6 OPERATIONAL CATEGORIES)
    # =======================================================================

    # Case 1: Non-terrestrial Domain Constraint (Water / Marine)
    if land_water_class in ["OFFSHORE_MARINE", "INLAND_WATER"]:
        if total_infra_count > 0 or (distinct_days >= MODERATE_DAYS_COUNT and obs_count >= 3):
            assessment = CATEGORY_GAS_FLARE
            confidence = "MODERATE"
            explanation = (
                f"Event is located in non-terrestrial marine/water domain ({land_water_class}) "
                f"with persistent multi-pass detections characteristic of offshore gas flaring or extraction platforms."
            )
        else:
            assessment = CATEGORY_OTHER_THERMAL_EVENT
            confidence = "HIGH"
            explanation = (
                f"Event is located in non-terrestrial domain ({land_water_class}). "
                f"Thermal emission likely represents sun glint, offshore reflection, or non-combustion thermal artifact."
            )

    # Case 2: Stationary Industrial Heat / Gas Flaring / Industrial Fire
    # Triggered by physical infrastructure proximity OR overwhelming multi-day stationary revisit recurrence
    elif (
        (total_infra_count > 0 and (obs_count >= MODERATE_OBS_COUNT or distinct_days >= MODERATE_DAYS_COUNT))
        or (distinct_days >= STRONG_DAYS_COUNT and obs_count >= STRONG_OBS_COUNT and duration_hours >= STRONG_PERSIST_HOURS)
        or (ml_class in ["INDUSTRIAL_HEAT", "Industrial", "GAS_FLARE", "INDUSTRIAL_FIRE"] and ml_confidence >= 0.40 and obs_count >= 2)
    ):
        # Sub-branch: Acute Industrial Fire Emergency vs Stationary Gas Flaring / Process Heat
        if max_frp >= 15.0 or (anomaly_category == "HIGHLY_ELEVATED" and duration_hours < 48.0 and obs_count >= 5):
            assessment = CATEGORY_INDUSTRIAL_FIRE
            confidence = "HIGH" if max_frp >= 15.0 else "MODERATE"
            explanation = (
                f"Acute elevated thermal emission (peak FRP {max_frp:.1f} MW) detected at or adjacent to mapped "
                f"industrial/power infrastructure ({total_infra_count} facilities within {FACILITY_RADIUS_M}m buffer). "
                f"Thermal intensity significantly exceeds routine furnace baselines, indicating an active industrial fire incident."
            )
        else:
            assessment = CATEGORY_GAS_FLARE
            if total_infra_count > 0 or (distinct_days >= 4 and obs_count >= 20):
                confidence = "HIGH"
            else:
                confidence = "MODERATE"

            reasons = []
            if total_infra_count > 0:
                reasons.append(f"{total_infra_count} industrial/power facilities mapped within {FACILITY_RADIUS_M}m buffer")
            if distinct_days >= MODERATE_DAYS_COUNT:
                reasons.append(f"multi-day revisit persistence ({distinct_days} distinct calendar days, {duration_hours:.1f}h duration)")
            if obs_count >= STRONG_OBS_COUNT:
                reasons.append(f"high observation recurrence ({obs_count} detections)")
            if footprint_km2 > 0 and footprint_km2 <= MAX_INDUSTRIAL_FOOTPRINT_KM2:
                reasons.append(f"bounded cluster footprint ({footprint_km2:.1f} km²)")
            if ml_class in ["INDUSTRIAL_HEAT", "Industrial", "GAS_FLARE", "INDUSTRIAL_FIRE"]:
                reasons.append(f"Random Forest Industrial/Flare prediction ({ml_class}, conf {ml_confidence:.3f})")
            elif ml_class in ["WILDLAND_FIRE", "Forest", "FOREST_FIRE", "AGRICULTURAL_BURNING", "Agricultural", "AGRICULTURAL_FIRE"]:
                reasons.append(
                    f"stationary recurrence outweighs atmospheric/spectral ML prediction ({ml_class}, conf {ml_confidence:.3f})"
                )

            explanation = (
                f"Event exhibits sustained stationary thermal characteristics: {', '.join(reasons)}. "
                f"Indicates persistent industrial heat / gas flaring / blast furnace bleed activity rather than an advancing landscape fire."
            )

    # Case 3: High Priority Thermal Event (Intense radiative power and/or multi-pass confirmation)
    elif (
        (max_frp >= HIGH_FRP_MW and max_brightness >= HIGH_BRIGHTNESS_K)
        and (obs_count >= MODERATE_OBS_COUNT or duration_hours >= MODERATE_PERSIST_HOURS or anomaly_category in ["ELEVATED", "HIGHLY_ELEVATED"] or max_frp >= 6.0)
    ):
        if total_infra_count > 0:
            assessment = CATEGORY_INDUSTRIAL_FIRE
        else:
            assessment = CATEGORY_FOREST_FIRE

        confidence = "HIGH" if (obs_count >= MODERATE_OBS_COUNT and max_frp >= 6.0) else "MODERATE"
        
        reasons = [
            f"peak FRP of {max_frp:.1f} MW (threshold >= {HIGH_FRP_MW} MW)",
            f"thermal brightness of {max_brightness:.1f} K (threshold >= {HIGH_BRIGHTNESS_K} K)",
        ]
        if obs_count >= 2:
            reasons.append(f"multi-pass satellite verification ({obs_count} detections across {distinct_days} days)")
        if anomaly_category in ["ELEVATED", "HIGHLY_ELEVATED"]:
            reasons.append(f"statistically {anomaly_category.lower().replace('_', ' ')} historical baseline anomaly")
        if ml_class != "UNAVAILABLE":
            reasons.append(f"ML source class '{ml_class}' (conf {ml_confidence:.3f})")

        explanation = (
            f"High-intensity active thermal event confirmed by {', '.join(reasons)}. "
            f"Radiative energy and satellite persistence require priority monitoring and response."
        )

    # Case 4: Low Confidence Thermal Anomaly / Potential False Alarm
    elif (
        obs_count == 1
        and persistence_days <= 1.0
        and max_frp < LOW_CONFIDENCE_FRP_MAX_MW
        and (max_brightness < MIN_ACTIVE_BRIGHT_K or ml_confidence < 0.50)
        and anomaly_category in ["WITHIN_BASELINE", "BELOW_BASELINE", "UNAVAILABLE"]
        and total_infra_count == 0
    ):
        assessment = CATEGORY_OTHER_THERMAL_EVENT
        confidence = "MODERATE"
        explanation = (
            f"Isolated single-pass observation ({obs_count} detection) with marginal Fire Radiative Power "
            f"({max_frp:.1f} MW < {LOW_CONFIDENCE_FRP_MAX_MW} MW threshold) and thermal levels within historical baseline bounds. "
            f"Lacks multi-pass temporal corroboration or infrastructure association; represents a low-confidence thermal "
            f"anomaly / potential false alarm."
        )

    # Case 5: Likely Agricultural Burning
    elif (
        (ml_class in ["AGRICULTURAL_BURNING", "Agricultural", "AGRICULTURAL_FIRE"] or ml_probs.get("AGRICULTURAL_BURNING", 0) >= 0.40 or ml_probs.get("AGRICULTURAL_FIRE", 0) >= 0.40)
        and ml_confidence >= 0.35
        and land_water_class == "LAND"
        and distinct_days <= MODERATE_DAYS_COUNT
        and total_infra_count == 0
    ):
        assessment = CATEGORY_AGRICULTURAL_FIRE
        confidence = "MODERATE"
        explanation = (
            f"Short-lived episodic thermal detection on terrestrial land ({state}) with Random Forest "
            f"Agricultural Burning classification (confidence {ml_confidence:.3f}). "
            f"Transient duration ({distinct_days} day(s), {obs_count} detection(s)) and absence of stationary "
            f"industrial infrastructure are characteristic of agricultural crop residue / field burning. "
            f"(Note: field-level crop parcel boundaries are not integrated; assessment is indicative)."
        )

    # Case 6: Likely Wildland / Forest Fire
    elif (
        (ml_class in ["WILDLAND_FIRE", "Forest", "FOREST_FIRE"] or ml_probs.get("WILDLAND_FIRE", 0) >= 0.35 or ml_probs.get("FOREST_FIRE", 0) >= 0.35)
        and land_water_class == "LAND"
        and (max_brightness >= MIN_ACTIVE_BRIGHT_K or max_frp >= MIN_ACTIVE_FRP_MW)
    ):
        assessment = CATEGORY_FOREST_FIRE
        confidence = "MODERATE"
        reasons = [
            f"Random Forest Wildland Fire classification (confidence {ml_confidence:.3f})",
            f"active thermal radiance (peak FRP {max_frp:.1f} MW, brightness {max_brightness:.1f} K)",
            f"terrestrial land surface ({state})",
        ]
        if obs_count >= 2:
            reasons.append(f"{obs_count} detection(s) across {distinct_days} day(s)")

        explanation = (
            f"Thermal event exhibits wildland/forest fire characteristics: {', '.join(reasons)}. "
            f"Absence of nearby industrial infrastructure and thermal profile are consistent with vegetative combustion. "
            f"(Note: real-time canopy inventory data is not integrated; assessment is indicative)."
        )

    # Case 7: Unresolved / Unknown
    else:
        assessment = CATEGORY_UNKNOWN
        confidence = "LOW"
        ml_dist_str = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(ml_probs.items(), key=lambda x: -x[1]))
        explanation = (
            f"Multi-source evidence is insufficient or dispersed to classify reliably. "
            f"Observations: {obs_count}, Distinct days: {distinct_days}, Peak FRP: {max_frp:.1f} MW, "
            f"Historical anomaly: {anomaly_category}. "
            f"ML probability distribution is divided ({ml_dist_str}). "
            f"Requires additional satellite revisit passes or manual analyst review."
        )

    return {
        "event_id": event_id,
        "ml_class": ml_class,
        "ml_confidence": ml_confidence,
        "assessment": assessment,
        "assessment_confidence": confidence,
        "evidence": evidence_dict,
        "explanation": explanation
    }
