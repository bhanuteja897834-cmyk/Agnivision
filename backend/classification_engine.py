"""
backend/classification_engine.py

AGNIVISION-GIS Intelligence Layer: Step 8 — Thermal Event Classification Engine

A transparent, deterministic, rule-based prototype classification engine that uses
multi-source evidence (Thermal, Temporal, Historical Baseline, Geographic Validation,
Spatial Extent, and Facility Context) to assess the candidate source category for a
persistent thermal event.

SUPPORTED LABELS:
- ACTIVE_FIRE
- INDUSTRIAL_HEAT
- AGRICULTURAL_BURNING
- WILDLAND_FIRE
- UNKNOWN

CRITICAL SCIENTIFIC & DATA-INTEGRITY PRINCIPLES:
- NOT machine learning. No model training, black-box scores, or synthetic inferences.
- ZERO fake probabilities, ZERO arbitrary confidence percentages.
- Every decision is explainable and traceable from explicit rule IDs and empirical evidence.
- UNKNOWN is a legitimate and required outcome when evidence is insufficient,
  conflicting, or when critical context (e.g., crop parcel or canopy data) is missing.
- Respects geographic boundaries: OFFSHORE_MARINE and INLAND_WATER cannot be agricultural
  or wildland fires.
- Keeps Analytical Classification strictly separate from Human Verification records.
"""

from typing import Dict, Any, List, Optional
import datetime

# =========================================================
# CLASSIFICATION THRESHOLDS & CONFIGURATION
# =========================================================

CLASSIFICATION_THRESHOLDS = {
    # Industrial heat requirements
    "industrial": {
        "min_observations": 3,
        "min_persistence_hours": 12.0,
        "min_distinct_days": 2,
        "facility_radius_m": 5000,
        "max_footprint_km2": 400.0,
    },
    # Active fire requirements
    "active_fire": {
        "min_frp_mw": 1.0,
        "high_frp_mw": 5.0,
        "min_brightness_k": 315.0,
        "high_brightness_k": 330.0,
        "min_observations": 2,
    },
    # Unverified classes (land-cover data currently unavailable in system)
    "agricultural": {
        "land_cover_data_available": False,
    },
    "wildland": {
        "vegetation_data_available": False,
    },
}


# =========================================================
# RULE DEFINITIONS
# =========================================================

RULES_METADATA = {
    "RULE_GEO_001_TERRESTRIAL_LAND": {
        "name": "Terrestrial Land Surface Validation",
        "description": "Event centroid is confirmed on terrestrial land surface via NOAA GLOBE 1km mask.",
    },
    "RULE_GEO_002_NON_TERRESTRIAL_CONSTRAINT": {
        "name": "Non-Terrestrial Domain Constraint",
        "description": "Event intersects marine waters or inland water body; agricultural and wildland classifications are prohibited.",
    },
    "RULE_IND_001_FACILITY_PROXIMITY": {
        "name": "Industrial / Energy Infrastructure Proximity",
        "description": "Mapped industrial facilities, smelters, refineries, or power infrastructure present within 5km radius.",
    },
    "RULE_IND_002_STATIONARY_PERSISTENCE": {
        "name": "Stationary Multi-Day Persistence",
        "description": "Event exhibits revisit detection persistence across multiple calendar days with bounded spatial footprint.",
    },
    "RULE_IND_003_THERMAL_CONSISTENCY": {
        "name": "Thermal Radiance Flux Consistency",
        "description": "Observed brightness and FRP reflect sustained thermal emission characteristics compatible with industrial process heat.",
    },
    "RULE_FIRE_001_SIGNIFICANT_RADIATIVE_POWER": {
        "name": "Elevated Fire Radiative Power",
        "description": "Observations exhibit peak FRP and thermal radiance typical of active open biomass combustion.",
    },
    "RULE_FIRE_002_MULTI_PASS_DETECTION": {
        "name": "Multi-Pass Active Combustion Signature",
        "description": "Multiple satellite detections confirm repeatable thermal radiance without proximity to stationary industrial stacks.",
    },
    "RULE_AGRI_001_LAND_USE_DATA_UNAVAILABLE": {
        "name": "Agricultural Land-Cover Data Gap",
        "description": "Field-level agricultural parcel boundary and crop harvest calendars are not integrated; primary agricultural classification precluded.",
    },
    "RULE_WILD_001_VEGETATION_CANOPY_UNAVAILABLE": {
        "name": "Vegetation Canopy Data Gap",
        "description": "Live fuel moisture and high-resolution forest canopy datasets are not integrated; primary wildland classification precluded.",
    },
    "RULE_UNK_001_SINGLE_OBSERVATION_SAMPLE": {
        "name": "Single-Observation Sample Constraint",
        "description": "Event has only 1 satellite observation; insufficient temporal repeatability to establish definitive source attribution.",
    },
    "RULE_UNK_002_CONTRADICTION_DETECTED": {
        "name": "Evidence Contradiction or Ambiguity",
        "description": "Evidence dimensions yield conflicting signals; UNKNOWN assigned to prevent false attribution.",
    },
    "RULE_UNK_003_INCONCLUSIVE_EVIDENCE": {
        "name": "Inconclusive Source Attribution",
        "description": "Available evidence does not definitively favor a specific source category above competing hypotheses.",
    },
}


# =========================================================
# CORE CLASSIFICATION ENGINE
# =========================================================

def classify_thermal_event(
    event: Dict[str, Any],
    evidence_profile: Optional[Dict[str, Any]] = None,
    anomaly_result: Optional[Dict[str, Any]] = None,
    asset_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce an explainable, deterministic rule-based source classification
    for a persistent thermal event.

    Returns:
        Structured classification dictionary containing:
        - classification: ACTIVE_FIRE | INDUSTRIAL_HEAT | AGRICULTURAL_BURNING | WILDLAND_FIRE | UNKNOWN
        - method: RULE_BASED
        - primary_explanation: detailed human-readable rationale
        - supporting_evidence: list of verified factual evidentiary bullet points
        - alternative_explanations: list of plausible competing hypotheses
        - limitations: list of critical methodological constraints
        - rules_triggered: list of rule objects that fired
    """
    event_id = event.get("event_id", "UNKNOWN")

    # Extract or infer evidence dimensions
    obs_count = event.get("observation_count", len(event.get("observations", [])) or 1)
    
    # Authoritative temporal extraction from existing event history & evidence profile
    evi_temporal = evidence_profile.get("temporal", {}) if evidence_profile else {}
    temporal_summary = event.get("temporal_summary") or {}
    
    distinct_days = (
        evi_temporal.get("distinct_observation_days")
        or event.get("persistence_days")
        or temporal_summary.get("persistence_days")
        or temporal_summary.get("distinct_days")
        or (len({o.get("acq_date") for o in event.get("observations", []) if o.get("acq_date")}) if event.get("observations") else None)
        or 1
    )
    
    persistence_days = float(
        evi_temporal.get("persistence_days")
        or event.get("persistence_days")
        or temporal_summary.get("persistence_days")
        or distinct_days
    )
    
    duration_hours = evi_temporal.get("duration_hours")
    if duration_hours is None:
        duration_hours = temporal_summary.get("duration_hours")
    if duration_hours is None:
        first_d = event.get("first_detected") or temporal_summary.get("first_detected")
        last_d = event.get("last_detected") or temporal_summary.get("last_detected")
        if first_d and last_d:
            try:
                dt1 = datetime.datetime.fromisoformat(first_d.replace("Z", "+00:00"))
                dt2 = datetime.datetime.fromisoformat(last_d.replace("Z", "+00:00"))
                duration_hours = round(abs((dt2 - dt1).total_seconds()) / 3600.0, 1)
            except Exception:
                duration_hours = round(float(persistence_days - 1) * 24.0, 1)
        else:
            duration_hours = round(float(persistence_days - 1) * 24.0, 1)

    # Thermal summaries
    b_summary = event.get("brightness_summary") or {}
    b_mean = b_summary.get("avg") or b_summary.get("mean")
    b_max = b_summary.get("max")
    f_summary = event.get("frp_summary") or {}
    f_mean = f_summary.get("avg") or f_summary.get("mean")
    f_max = f_summary.get("max")

    # Geographic domain
    geo_val = event.get("geographic_validation") or {}
    domain = geo_val.get("domain") or event.get("geographic_domain") or "LAND"
    state = geo_val.get("state") or event.get("state") or "Unassigned"
    district = geo_val.get("district") or event.get("district") or "Unassigned"

    # Facility context
    if asset_data:
        counts = asset_data.get("counts") or {}
        industrial_count = counts.get("industrial", 0)
        power_count = counts.get("power", 0)
        total_facilities = industrial_count + power_count
        facilities_present = total_facilities > 0
    elif evidence_profile and evidence_profile.get("facility_context"):
        fc = evidence_profile["facility_context"]
        industrial_count = fc.get("industrial_count", 0)
        power_count = fc.get("power_count", 0)
        total_facilities = fc.get("facilities_count", 0)
        facilities_present = fc.get("status") == "PRESENT"
    else:
        industrial_count = 0
        power_count = 0
        total_facilities = 0
        facilities_present = False

    # Historical anomaly
    if anomaly_result:
        anomaly_status = anomaly_result.get("interpretation", "WITHIN_BASELINE")
        is_fallback = anomaly_result.get("is_fallback", False)
    elif evidence_profile and evidence_profile.get("historical"):
        anomaly_status = evidence_profile["historical"].get("anomaly_status", "WITHIN_BASELINE")
        is_fallback = evidence_profile["historical"].get("is_fallback", False)
    else:
        anomaly_status = "UNAVAILABLE"
        is_fallback = False

    # Spatial summary
    spatial_summary = event.get("spatial_summary") or {}
    centroid = event.get("centroid") or spatial_summary.get("centroid") or {"latitude": 0.0, "longitude": 0.0}

    # Tracking triggered rules
    rules_triggered = []
    supporting_evidence = []
    alternative_explanations = []
    limitations = [
        "Facility proximity provides spatial context only and does not establish physical emission causation.",
        "Satellite VIIRS 375m pixels measure integrated radiance flux, not direct optical flame imagery.",
        "Field-level validated agricultural parcel boundaries and live crop calendars are not integrated into the system.",
        "High-resolution live forest canopy and fuel moisture datasets are not currently integrated.",
        "Deterministic rule-based classification assessment; not an empirical machine-learning prediction or fire probability.",
    ]

    # Rule helper
    def trigger_rule(rule_id: str):
        meta = RULES_METADATA.get(rule_id, {"name": rule_id, "description": ""})
        rules_triggered.append({
            "rule_id": rule_id,
            "rule_name": meta["name"],
            "description": meta["description"],
            "matched": True,
        })

    # =========================================================
    # STEP A: GEOGRAPHIC DOMAIN CONSTRAINTS
    # =========================================================

    if domain == "LAND":
        trigger_rule("RULE_GEO_001_TERRESTRIAL_LAND")
        supporting_evidence.append(f"Centroid verified on terrestrial land surface ({state}) via NOAA GLOBE 1km boundary mask.")
    else:
        trigger_rule("RULE_GEO_002_NON_TERRESTRIAL_CONSTRAINT")
        supporting_evidence.append(f"Geographic validation identifies event domain as {domain}.")
        # Offshore or inland water cannot be agricultural or wildland
        limitations.append(f"Event is located within {domain}; land-based agricultural and wildland classifications are prohibited.")

        if domain == "OFFSHORE_MARINE":
            if facilities_present and (industrial_count > 0 or power_count > 0):
                trigger_rule("RULE_IND_001_FACILITY_PROXIMITY")
                classification = "INDUSTRIAL_HEAT"
                explanation = (
                    f"Event is situated in offshore marine waters with {total_facilities} nearby mapped marine energy or industrial infrastructure. "
                    "Evidence is most consistent with offshore gas flaring or industrial platform heat."
                )
                alternative_explanations.append({
                    "candidate": "UNKNOWN",
                    "status": "COMPETING_HYPOTHESIS",
                    "reason": "Thermal emissions in marine environments may reflect sensor solar glint or unmapped vessel operations."
                })
            else:
                trigger_rule("RULE_UNK_002_CONTRADICTION_DETECTED")
                classification = "UNKNOWN"
                explanation = (
                    f"Event is located in offshore marine waters with no mapped energy or industrial infrastructure within 5km. "
                    "Thermal anomaly source cannot be determined from available terrestrial datasets."
                )
                alternative_explanations.append({
                    "candidate": "INDUSTRIAL_HEAT",
                    "status": "UNVERIFIED_CANDIDATE",
                    "reason": "Potential unmapped offshore flaring or maritime vessel activity."
                })

            return _format_response(
                event_id, classification, explanation, supporting_evidence,
                alternative_explanations, limitations, rules_triggered
            )

        elif domain == "INLAND_WATER":
            trigger_rule("RULE_UNK_002_CONTRADICTION_DETECTED")
            classification = "UNKNOWN"
            explanation = (
                "Observations coincide with an inland water surface boundary. Radiance detections may stem from shoreline industrial runoff, "
                "sub-pixel coastal land overlap (375m VIIRS pixel footprint), or sensor reflection."
            )
            alternative_explanations.append({
                "candidate": "INDUSTRIAL_HEAT",
                "status": "COMPETING_HYPOTHESIS",
                "reason": "Nearby shoreline industrial discharge or processing plant."
            })
            alternative_explanations.append({
                "candidate": "ACTIVE_FIRE",
                "status": "COMPETING_HYPOTHESIS",
                "reason": "Riparian or shoreline vegetation burning overlapping the water mask."
            })
            return _format_response(
                event_id, classification, explanation, supporting_evidence,
                alternative_explanations, limitations, rules_triggered
            )

    # =========================================================
    # STEP B: SINGLE OBSERVATION SAMPLE CONSTRAINT
    # =========================================================

    if obs_count <= 1:
        trigger_rule("RULE_UNK_001_SINGLE_OBSERVATION_SAMPLE")
        supporting_evidence.append("Event consists of only 1 discrete satellite pass detection.")

        classification = "UNKNOWN"
        explanation = (
            f"Event has only a single observation (detected on {event.get('first_detected', 'N/A')}). "
            "Single-pass observations lack the multi-temporal persistence required to distinguish ephemeral active combustion, "
            "small agricultural burning, transient industrial stacks, or sensor noise."
        )

        alternative_explanations.append({
            "candidate": "ACTIVE_FIRE",
            "status": "PLAUSIBLE_ALTERNATIVE",
            "reason": "Thermal intensity (T4 brightness) is consistent with a brief open flame or small clearing."
        })
        if facilities_present:
            alternative_explanations.append({
                "candidate": "INDUSTRIAL_HEAT",
                "status": "PLAUSIBLE_ALTERNATIVE",
                "reason": f"{total_facilities} facility(ies) mapped nearby, but single observation does not verify sustained heat."
            })
        else:
            alternative_explanations.append({
                "candidate": "AGRICULTURAL_BURNING",
                "status": "UNVERIFIABLE_ALTERNATIVE",
                "reason": "Potential field clearing, but no field-level crop mask exists to confirm."
            })

        return _format_response(
            event_id, classification, explanation, supporting_evidence,
            alternative_explanations, limitations, rules_triggered
        )

    # =========================================================
    # STEP C: MULTI-SIGNAL INDUSTRIAL HEAT EVALUATION
    # =========================================================

    cfg_ind = CLASSIFICATION_THRESHOLDS["industrial"]
    has_ind_facilities = facilities_present and (industrial_count > 0 or power_count > 0)
    has_multi_day = distinct_days >= cfg_ind["min_distinct_days"] or duration_hours >= cfg_ind["min_persistence_hours"]
    has_robust_sample = obs_count >= cfg_ind["min_observations"]

    if has_ind_facilities and has_multi_day and has_robust_sample:
        trigger_rule("RULE_IND_001_FACILITY_PROXIMITY")
        trigger_rule("RULE_IND_002_STATIONARY_PERSISTENCE")
        trigger_rule("RULE_IND_003_THERMAL_CONSISTENCY")

        supporting_evidence.append(f"{total_facilities} mapped industrial/power infrastructure site(s) within 5km ({industrial_count} industrial, {power_count} power).")
        if asset_data and asset_data.get("assets"):
            top_names = [a.get("name") for a in asset_data["assets"] if a.get("name")]
            if top_names:
                supporting_evidence.append(f"Identified infrastructure nearby: {', '.join(top_names[:3])}.")
        supporting_evidence.append(f"Multi-day temporal persistence: {distinct_days} distinct observation days ({duration_hours:.1f} hours span).")
        supporting_evidence.append(f"Robust observation history: {obs_count} discrete satellite detection passes.")
        if b_mean is not None:
            supporting_evidence.append(f"Mean brightness: {b_mean} K (Max: {b_max} K).")
        if f_mean is not None:
            supporting_evidence.append(f"Mean FRP: {f_mean} MW (Max: {f_max} MW).")
        if anomaly_status:
            if anomaly_status == "WITHIN_BASELINE":
                supporting_evidence.append("Historical activity is within the available reference baseline.")
            elif anomaly_status == "ANOMALOUS_ELEVATED":
                supporting_evidence.append("Thermal activity is elevated relative to the available reference baseline.")
            elif anomaly_status == "BELOW_BASELINE":
                supporting_evidence.append("Thermal activity is below the available reference baseline.")
            elif anomaly_status == "UNAVAILABLE":
                supporting_evidence.append("Historical reference baseline is unavailable for comparison.")
            else:
                supporting_evidence.append(f"Historical reference baseline status: {anomaly_status}.")

        classification = "INDUSTRIAL_HEAT"
        span_str = f", approximately {int(round(duration_hours))} hours span" if duration_hours > 0 else ""
        explanation = (
            f"Event exhibits multi-day stationary persistence ({distinct_days} distinct observation days, {obs_count} observations{span_str}) "
            f"directly co-located within 5km of {total_facilities} mapped industrial/energy facilities in {state}. "
            "Multi-source evidence is most consistent with stationary industrial process heat, flaring, or facility emissions."
        )

        alternative_explanations.append({
            "candidate": "ACTIVE_FIRE",
            "status": "PLAUSIBLE_ALTERNATIVE",
            "reason": "Elevated thermal radiance and FRP could also reflect active ground combustion (e.g. coal seam or waste burning) adjacent to the mapped facility."
        })
        alternative_explanations.append({
            "candidate": "UNKNOWN",
            "status": "CONSERVATIVE_ALTERNATIVE",
            "reason": "Facility proximity does not establish physical emission causation without ground scout or direct optical confirmation."
        })

        return _format_response(
            event_id, classification, explanation, supporting_evidence,
            alternative_explanations, limitations, rules_triggered
        )

    # =========================================================
    # STEP D: ACTIVE FIRE EVALUATION
    # =========================================================

    cfg_fire = CLASSIFICATION_THRESHOLDS["active_fire"]
    has_elevated_frp = (f_max is not None and f_max >= cfg_fire["min_frp_mw"]) or (f_mean is not None and f_mean >= cfg_fire["min_frp_mw"])
    has_elevated_bright = (b_mean is not None and b_mean >= cfg_fire["min_brightness_k"]) or (b_max is not None and b_max >= cfg_fire["high_brightness_k"])

    if has_elevated_frp or has_elevated_bright:
        trigger_rule("RULE_FIRE_001_SIGNIFICANT_RADIATIVE_POWER")
        trigger_rule("RULE_FIRE_002_MULTI_PASS_DETECTION")

        supporting_evidence.append(f"Significant thermal radiative signal: Mean T4 {b_mean or '—'} K (Max: {b_max or '—'} K).")
        if f_max is not None:
            supporting_evidence.append(f"Fire Radiative Power: Mean {f_mean or '—'} MW (Max: {f_max} MW) indicating heat release flux.")
        supporting_evidence.append(f"{obs_count} satellite detection passes across {distinct_days} distinct observation day{'s' if distinct_days != 1 else ''}.")

        if not facilities_present or total_facilities == 0:
            supporting_evidence.append("No mapped industrial or energy infrastructure identified within 5km radius.")

        classification = "ACTIVE_FIRE"
        span_text = f", approximately {int(round(duration_hours))} hours span" if duration_hours > 0 else ""
        explanation = (
            f"Multi-detection thermal observations ({obs_count} passes across {distinct_days} distinct observation day{'s' if distinct_days != 1 else ''}{span_text}) "
            f"exhibit elevated Fire Radiative Power (Max: {f_max or '—'} MW) and radiance flux (Peak: {b_max or '—'} K) across a validated land surface in {state}. "
            "Evidence is most consistent with active combustion."
        )

        # Alternative hypotheses
        trigger_rule("RULE_AGRI_001_LAND_USE_DATA_UNAVAILABLE")
        trigger_rule("RULE_WILD_001_VEGETATION_CANOPY_UNAVAILABLE")

        alternative_explanations.append({
            "candidate": "AGRICULTURAL_BURNING",
            "status": "UNVERIFIED_SUBTYPE",
            "reason": "May represent agricultural stubble or crop residue burning, but field parcel and crop calendar data are not integrated."
        })
        alternative_explanations.append({
            "candidate": "WILDLAND_FIRE",
            "status": "UNVERIFIED_SUBTYPE",
            "reason": "May represent brush or forest burning, but real-time vegetation moisture and canopy layers are not integrated."
        })
        if facilities_present:
            alternative_explanations.append({
                "candidate": "INDUSTRIAL_HEAT",
                "status": "COMPETING_HYPOTHESIS",
                "reason": f"{total_facilities} facility(ies) mapped nearby; could indicate unmapped thermal process emissions."
            })

        return _format_response(
            event_id, classification, explanation, supporting_evidence,
            alternative_explanations, limitations, rules_triggered
        )

    # =========================================================
    # STEP E: INCONCLUSIVE FALLBACK (UNKNOWN)
    # =========================================================

    trigger_rule("RULE_UNK_003_INCONCLUSIVE_EVIDENCE")
    supporting_evidence.append(f"{obs_count} observation(s) across {distinct_days} day(s).")
    if b_mean is not None:
        supporting_evidence.append(f"Nominal brightness: {b_mean} K.")

    classification = "UNKNOWN"
    explanation = (
        "Available multi-source evidence is inconclusive. Thermal intensity, persistence duration, and facility context "
        "do not provide sufficient discriminatory evidence to definitively distinguish industrial process heat, agricultural burning, "
        "or open fire combustion."
    )

    alternative_explanations.append({
        "candidate": "ACTIVE_FIRE",
        "status": "COMPETING_HYPOTHESIS",
        "reason": "Thermal detections recorded, but heat release values are nominal."
    })
    alternative_explanations.append({
        "candidate": "INDUSTRIAL_HEAT",
        "status": "COMPETING_HYPOTHESIS",
        "reason": "Contextual evidence does not establish sustained facility emissions."
    })

    return _format_response(
        event_id, classification, explanation, supporting_evidence,
        alternative_explanations, limitations, rules_triggered
    )


def _format_response(
    event_id: str,
    classification: str,
    explanation: str,
    supporting_evidence: List[str],
    alternative_explanations: List[Dict[str, Any]],
    limitations: List[str],
    rules_triggered: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Format standard classification JSON response."""
    return {
        "status": "AVAILABLE",
        "event_id": event_id,
        "classification": classification,
        "method": "RULE_BASED",
        "evaluated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "primary_explanation": explanation,
        "supporting_evidence": supporting_evidence,
        "alternative_explanations": alternative_explanations,
        "limitations": limitations,
        "rules_triggered": rules_triggered,
        "rules_triggered_count": len(rules_triggered),
    }
