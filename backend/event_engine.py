"""
backend/event_engine.py

AGNIVISION-GIS Event Intelligence Layer: Step 1 - Persistent Event IDs

This module implements rule-based spatiotemporal event clustering.
It groups discrete NASA FIRMS VIIRS satellite thermal observations into persistent Event abstractions.

ARCHITECTURAL RULES:
1. An Event is NOT a new FIRMS observation. It is a logical grouping of related FIRMS observations.
2. Rule-based spatiotemporal clustering is transparent and explainable. It does NOT use ML or heuristics that hallucinate data.
3. Every original FIRMS observation is preserved intact, with an added 'event_id'.
4. Geographic domain boundaries (e.g. LAND vs OFFSHORE_MARINE vs INLAND_WATER) are strictly respected.
"""

import datetime
import logging
import math
import os
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("agnivision.event_engine")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# =========================================================
# CONFIGURABLE SPATIOTEMPORAL THRESHOLDS
# =========================================================

# Maximum spatial distance in kilometers between two observations to be considered part of the same event
EVENT_SPATIAL_RADIUS_KM = float(os.getenv("EVENT_SPATIAL_RADIUS_KM", "3.0"))

# Maximum allowable temporal gap in hours between consecutive linked observations in an event
EVENT_TEMPORAL_GAP_HOURS = float(os.getenv("EVENT_TEMPORAL_GAP_HOURS", "36.0"))


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points on Earth in kilometers using Haversine formula.
    """
    R = 6371.0  # Earth mean radius in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))


def parse_observation_datetime(obs: Dict[str, Any]) -> Optional[datetime.datetime]:
    """
    Parse acquisition date and acquisition time from a FIRMS observation into a UTC datetime.
    Supports formats like acq_date='2026-09-21', acq_time='650' or '1925' or 650.
    Falls back gracefully to midnight or None for missing/malformed fields.
    """
    date_str = obs.get("acq_date")
    if not date_str or not isinstance(date_str, str):
        return None

    raw_time = obs.get("acq_time")
    if raw_time is None:
        time_str = "0000"
    else:
        time_str = str(raw_time).strip().zfill(4)

    try:
        hh = int(time_str[:2])
        mm = int(time_str[2:4])
        # Clamp invalid hours/minutes to valid range
        hh = max(0, min(23, hh))
        mm = max(0, min(59, mm))
        return datetime.datetime.fromisoformat(f"{date_str}T{hh:02d}:{mm:02d}:00").replace(
            tzinfo=datetime.timezone.utc
        )
    except Exception:
        try:
            return datetime.datetime.fromisoformat(f"{date_str}T00:00:00").replace(
                tzinfo=datetime.timezone.utc
            )
        except Exception:
            return None


def get_geographic_domain(obs: Dict[str, Any]) -> str:
    """
    Extract the validated geographic domain from observation metadata.
    Defaults to 'UNKNOWN' if geographic validation is missing.
    """
    geo = obs.get("geographic_validation")
    if isinstance(geo, dict):
        return geo.get("domain") or "UNKNOWN"
    return "UNKNOWN"


def observation_sort_key(obs: Dict[str, Any]):
    """
    Deterministic chronological sorting key for observations.
    Primary key: acquisition datetime (acq_date + acq_time).
    Secondary keys: latitude, longitude, satellite, scan, track.
    """
    dt = parse_observation_datetime(obs)
    dt_val = dt if dt is not None else datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    try:
        lat = round(float(obs.get("latitude", 0.0)), 5)
        lon = round(float(obs.get("longitude", 0.0)), 5)
    except (ValueError, TypeError):
        lat, lon = 0.0, 0.0
    sat = str(obs.get("satellite", ""))
    scan = str(obs.get("scan", ""))
    track = str(obs.get("track", ""))
    return (dt_val, lat, lon, sat, scan, track)


def cluster_observations_into_events(
    fires: List[Dict[str, Any]],
    spatial_radius_km: float = EVENT_SPATIAL_RADIUS_KM,
    temporal_gap_hours: float = EVENT_TEMPORAL_GAP_HOURS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Rule-based spatiotemporal event clustering engine.

    Groups discrete FIRMS observations into persistent Events based on:
    1. Geographic domain consistency (LAND is never merged with OFFSHORE_MARINE or INLAND_WATER).
    2. Temporal gap between detections <= temporal_gap_hours.
    3. Spatial distance between detections <= spatial_radius_km.

    Returns:
        (events, fires_with_event_ids)
    """
    total_obs = len(fires)
    if total_obs == 0:
        logger.info("[EVENT_ENGINE] FIRMS observations: 0 | Generated events: 0 | Average observations/event: 0.00 | Largest event: N/A with 0 observations")
        return [], []

    # 1. Extract valid coordinates, parsed datetimes, and domains
    valid_records = []
    unclusterable_indices = []

    for idx, obs in enumerate(fires):
        try:
            lat = float(obs.get("latitude"))
            lon = float(obs.get("longitude"))
            dt = parse_observation_datetime(obs)
            domain = get_geographic_domain(obs)

            if dt is None:
                unclusterable_indices.append(idx)
            else:
                valid_records.append((idx, lat, lon, dt, domain))
        except (ValueError, TypeError):
            unclusterable_indices.append(idx)

    num_valid = len(valid_records)

    # 2. Build adjacency graph for valid records
    adj = [[] for _ in range(num_valid)]

    # 1 degree of latitude is approx 111.0 km
    lat_threshold_deg = spatial_radius_km / 110.0

    for i in range(num_valid):
        idx_i, lat_i, lon_i, dt_i, dom_i = valid_records[i]
        cos_lat = max(0.1, math.cos(math.radians(lat_i)))
        lon_threshold_deg = spatial_radius_km / (110.0 * cos_lat)

        for j in range(i + 1, num_valid):
            idx_j, lat_j, lon_j, dt_j, dom_j = valid_records[j]

            # Rule 1: Geographic domain must match exactly
            if dom_i != dom_j:
                continue

            # Rule 2: Temporal difference must be within threshold
            dt_diff_hours = abs((dt_i - dt_j).total_seconds()) / 3600.0
            if dt_diff_hours > temporal_gap_hours:
                continue

            # Fast bounding-box check
            if abs(lat_i - lat_j) > lat_threshold_deg:
                continue
            if abs(lon_i - lon_j) > lon_threshold_deg:
                continue

            # Rule 3: Great-circle spatial distance within threshold
            dist_km = haversine_distance(lat_i, lon_i, lat_j, lon_j)
            if dist_km <= spatial_radius_km:
                adj[i].append(j)
                adj[j].append(i)

    # 3. Connected components traversal (Breadth-First Search)
    visited = [False] * num_valid
    raw_clusters = []

    for i in range(num_valid):
        if not visited[i]:
            visited[i] = True
            component = [valid_records[i][0]]  # store original index in fires
            queue = [i]
            while queue:
                curr = queue.pop(0)
                for neighbor in adj[curr]:
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        component.append(valid_records[neighbor][0])
                        queue.append(neighbor)
            raw_clusters.append(component)

    # Add unclusterable observations as standalone single-observation events
    for u_idx in unclusterable_indices:
        raw_clusters.append([u_idx])

    # 4. Pre-compute cluster sorting keys for strict determinism
    # Key: (first_detected_iso, -len(comp), min_lat, min_lon)
    cluster_sort_data = []
    for comp in raw_clusters:
        comp_fires = [fires[i] for i in comp]

        # Gather dates/times
        dts = [parse_observation_datetime(f) for f in comp_fires]
        valid_dts = [d for d in dts if d is not None]
        if valid_dts:
            earliest_dt = min(valid_dts)
        else:
            earliest_dt = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

        # Gather lats and lons
        lats = []
        lons = []
        for f in comp_fires:
            try:
                lats.append(float(f.get("latitude")))
                lons.append(float(f.get("longitude")))
            except (ValueError, TypeError):
                pass

        min_lat = min(lats) if lats else 0.0
        min_lon = min(lons) if lons else 0.0

        cluster_sort_data.append((earliest_dt, len(comp), min_lat, min_lon, comp))

    # Sort deterministically
    cluster_sort_data.sort(key=lambda x: (x[0], -x[1], x[2], x[3]))

    # 5. Construct Event objects and assign deterministic IDs (EVT-000001, ...)
    events = []
    for seq_num, (_, _, _, _, comp) in enumerate(cluster_sort_data, start=1):
        event_id = f"EVT-{seq_num:06d}"
        comp_fires = [fires[i] for i in comp]

        # Tag every observation with the event_id
        for f in comp_fires:
            f["event_id"] = event_id

        # Sort member observations strictly chronologically
        comp_fires.sort(key=observation_sort_key)

        # Calculate timestamps
        dts = [parse_observation_datetime(f) for f in comp_fires]
        valid_dts = [d for d in dts if d is not None]
        if valid_dts:
            first_detected = min(valid_dts).strftime("%Y-%m-%dT%H:%M:%SZ")
            last_detected = max(valid_dts).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            first_detected = comp_fires[0].get("acq_date") or ""
            last_detected = comp_fires[-1].get("acq_date") or ""

        # Persistence days (number of distinct calendar dates)
        dates_set = {f.get("acq_date") for f in comp_fires if f.get("acq_date")}
        persistence_days = max(1, len(dates_set))

        # Spatial Coordinates and Bounds
        lats = []
        lons = []
        for f in comp_fires:
            try:
                raw_lat = f.get("latitude")
                raw_lon = f.get("longitude")
                if raw_lat is not None and str(raw_lat).strip() != "":
                    lats.append(float(raw_lat))
                if raw_lon is not None and str(raw_lon).strip() != "":
                    lons.append(float(raw_lon))
            except (ValueError, TypeError):
                pass

        if lats and lons:
            centroid_lat = round(sum(lats) / len(lats), 5)
            centroid_lon = round(sum(lons) / len(lons), 5)
            min_lat = round(min(lats), 5)
            max_lat = round(max(lats), 5)
            min_lon = round(min(lons), 5)
            max_lon = round(max(lons), 5)
        else:
            centroid_lat = 0.0
            centroid_lon = 0.0
            min_lat = None
            max_lat = None
            min_lon = None
            max_lon = None

        spatial_summary = {
            "centroid": {
                "latitude": centroid_lat,
                "longitude": centroid_lon,
            },
            "min_latitude": min_lat,
            "max_latitude": max_lat,
            "min_longitude": min_lon,
            "max_longitude": max_lon,
        }

        # Temporal Summary
        temporal_summary = {
            "first_detected": first_detected,
            "last_detected": last_detected,
            "persistence_days": persistence_days,
            "observation_count": len(comp_fires),
        }

        # Brightness Summary (Kelvin)
        brightness_vals = []
        for f in comp_fires:
            raw_b = f.get("bright_ti4") if f.get("bright_ti4") is not None else f.get("brightness")
            try:
                if raw_b is not None and str(raw_b).strip() != "":
                    brightness_vals.append(float(raw_b))
            except (ValueError, TypeError):
                pass

        if brightness_vals:
            brightness_summary = {
                "min": round(min(brightness_vals), 2),
                "max": round(max(brightness_vals), 2),
                "avg": round(sum(brightness_vals) / len(brightness_vals), 2),
            }
        else:
            brightness_summary = {
                "min": None,
                "max": None,
                "avg": None,
            }

        # FRP Summary (MW)
        frp_vals = []
        for f in comp_fires:
            raw_frp = f.get("frp")
            try:
                if raw_frp is not None and str(raw_frp).strip() != "":
                    frp_vals.append(float(raw_frp))
            except (ValueError, TypeError):
                pass

        if frp_vals:
            frp_summary = {
                "min": round(min(frp_vals), 2),
                "max": round(max(frp_vals), 2),
                "avg": round(sum(frp_vals) / len(frp_vals), 2),
            }
        else:
            frp_summary = {
                "min": None,
                "max": None,
                "avg": None,
            }

        # Domain
        domain = get_geographic_domain(comp_fires[0])

        # State, District, City
        state = None
        district = None
        city = None
        for f in comp_fires:
            geo = f.get("geographic_validation")
            if isinstance(geo, dict):
                if not state and geo.get("state"):
                    state = geo.get("state")
                if not district and geo.get("district"):
                    district = geo.get("district")
                if not city and geo.get("city"):
                    city = geo.get("city")

        geographic_summary = {
            "domain": domain,
            "state": state,
            "district": district,
            "city": city,
        }

        # Maximum risk score and risk level
        risk_scores = []
        for f in comp_fires:
            try:
                risk_scores.append(float(f.get("risk_score", 0.0)))
            except (ValueError, TypeError):
                pass

        max_risk_score = round(max(risk_scores), 1) if risk_scores else 0.0

        if max_risk_score >= 80:
            risk_level = "Critical"
        elif max_risk_score >= 60:
            risk_level = "High"
        elif max_risk_score >= 30:
            risk_level = "Moderate"
        else:
            risk_level = "Low"

        event_obj = {
            "event_id": event_id,
            "observation_count": len(comp_fires),
            "first_detected": first_detected,
            "last_detected": last_detected,
            "persistence_days": persistence_days,
            "centroid": {
                "latitude": centroid_lat,
                "longitude": centroid_lon,
            },
            "spatial_summary": spatial_summary,
            "temporal_summary": temporal_summary,
            "brightness_summary": brightness_summary,
            "frp_summary": frp_summary,
            "geographic_validation": geographic_summary,
            "geographic_domain": domain,
            "state": state,
            "district": district,
            "city": city,
            "risk_level": risk_level,
            "risk_score": max_risk_score,
            "observations": comp_fires,
        }
        events.append(event_obj)

    # 6. Structured Logging
    total_events = len(events)
    avg_obs = (total_obs / total_events) if total_events > 0 else 0.0
    largest_event = max(events, key=lambda e: e["observation_count"]) if events else None
    largest_id = largest_event["event_id"] if largest_event else "N/A"
    largest_count = largest_event["observation_count"] if largest_event else 0

    logger.info(
        f"[EVENT_ENGINE] FIRMS observations: {total_obs} | "
        f"Generated events: {total_events} | "
        f"Average observations/event: {avg_obs:.2f} | "
        f"Largest event: {largest_id} with {largest_count} observations"
    )

    return events, fires


def get_event_history_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a persistent thermal event into the official Event History payload schema.
    Guarantees chronological ordering and complete preservation of all member observations.
    """
    observations = list(event.get("observations", []))
    observations.sort(key=observation_sort_key)

    return {
        "event_id": event["event_id"],
        "observation_count": event.get("observation_count", len(observations)),
        "first_detected": event.get("first_detected"),
        "last_detected": event.get("last_detected"),
        "persistence_days": event.get("persistence_days"),
        "spatial_summary": event.get("spatial_summary", {
            "centroid": event.get("centroid"),
            "min_latitude": event.get("min_latitude"),
            "max_latitude": event.get("max_latitude"),
            "min_longitude": event.get("min_longitude"),
            "max_longitude": event.get("max_longitude"),
        }),
        "temporal_summary": event.get("temporal_summary", {
            "first_detected": event.get("first_detected"),
            "last_detected": event.get("last_detected"),
            "persistence_days": event.get("persistence_days"),
            "observation_count": event.get("observation_count", len(observations)),
        }),
        "brightness_summary": event.get("brightness_summary"),
        "frp_summary": event.get("frp_summary"),
        "geographic_validation": event.get("geographic_validation"),
        "risk_level": event.get("risk_level"),
        "risk_score": event.get("risk_score"),
        "observations": observations,
    }
