"""
AGNIVISION-GIS: NASA FIRMS Spatio-Temporal Intelligence & Clustering Service (Stage 3)
Provides spatial grouping, temporal persistence tracking, and FRP intensity classification
for NASA FIRMS active fire satellite detections.
"""

import math
import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

# Configurable proximity and FRP thresholds
DEFAULT_SPATIAL_RADIUS_KM = 3.0
FRP_THRESHOLDS = {
    "LOW_MAX": 15.0,        # < 15 MW: LOW
    "MODERATE_MAX": 50.0,   # 15 to 50 MW: MODERATE
    "HIGH_MAX": 150.0       # 50 to 150 MW: HIGH, >= 150 MW: VERY_HIGH
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two geographic coordinates in kilometers."""
    R = 6371.0  # Earth mean radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def parse_datetime_utc(date_str: str, time_str: Optional[str] = None) -> datetime.datetime:
    """Parses date string (YYYY-MM-DD) and optional time string (HHMM) into UTC datetime."""
    t_clean = str(time_str or "0000").strip().zfill(4)
    try:
        hh = max(0, min(23, int(t_clean[:2])))
        mm = max(0, min(59, int(t_clean[2:4])))
    except (ValueError, TypeError):
        hh, mm = 0, 0

    try:
        parts = date_str.split("-")
        return datetime.datetime(int(parts[0]), int(parts[1]), int(parts[2]), hh, mm, tzinfo=datetime.timezone.utc)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def classify_frp_intensity(max_frp: float, mean_frp: Optional[float] = None) -> str:
    """
    Deterministic FRP thermal intensity classification:
    - LOW: max FRP < 15.0 MW
    - MODERATE: 15.0 MW <= max FRP < 50.0 MW
    - HIGH: 50.0 MW <= max FRP < 150.0 MW
    - VERY_HIGH: max FRP >= 150.0 MW
    """
    if max_frp >= FRP_THRESHOLDS["HIGH_MAX"]:
        return "VERY_HIGH"
    elif max_frp >= FRP_THRESHOLDS["MODERATE_MAX"]:
        return "HIGH"
    elif max_frp >= FRP_THRESHOLDS["LOW_MAX"]:
        return "MODERATE"
    else:
        return "LOW"


def classify_operational_state(obs_count: int = 1, duration_hours: float = 0.0, span_days: int = 1) -> str:
    """
    Classifies temporal persistence into descriptive operational states:
    - ISOLATED_ACTIVITY: 1 observation or short single-pass duration (< 1 hour).
    - REPEATED_ACTIVITY: multiple observations across passes within same day (1 to 24 hours).
    - PERSISTENT_ACTIVITY: continuous detections across multiple days or duration >= 24 hours.
    """
    if obs_count <= 1 or duration_hours < 1.0:
        return "ISOLATED_ACTIVITY"
    elif span_days > 1 or duration_hours >= 24.0:
        return "PERSISTENT_ACTIVITY"
    else:
        return "REPEATED_ACTIVITY"


class FIRMSSpatioTemporalClusteringService:
    """
    Deterministic spatial and temporal intelligence engine for FIRMS hotspot observations.
    Clusters observations within configurable spatial proximity, computes temporal persistence,
    and aggregates FRP intensity.
    """

    def __init__(self, default_radius_km: float = DEFAULT_SPATIAL_RADIUS_KM):
        self.default_radius_km = default_radius_km

    def cluster_hotspots(
        self,
        observations: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
        spatial_radius_km: Optional[float] = None,
        min_observations: int = 1
    ) -> Dict[str, Any]:
        """
        Executes spatial proximity clustering on the given list of FIRMS hotspot observations.
        Returns a structured dictionary of clusters with spatial, temporal, and FRP intelligence.
        """
        radius = float(spatial_radius_km) if spatial_radius_km is not None else self.default_radius_km
        if radius <= 0:
            radius = self.default_radius_km

        if not observations:
            return {
                "status": "success",
                "start_date": start_date,
                "end_date": end_date,
                "spatial_radius_km": radius,
                "total_observations": 0,
                "total_observations_analyzed": 0,
                "cluster_count": 0,
                "total_clusters": 0,
                "clusters": []
            }

        # 1. Parse and index observations with spatial coordinates
        valid_obs: List[Dict[str, Any]] = []
        for obs in observations:
            try:
                lat = float(obs.get("latitude", 0.0))
                lon = float(obs.get("longitude", 0.0))
                frp = float(obs.get("frp") or 0.0)
                acq_d = str(obs.get("acq_date") or start_date)
                acq_t = obs.get("acq_time")
                dt = parse_datetime_utc(acq_d, acq_t)
                valid_obs.append({
                    "raw": obs,
                    "id": obs.get("id"),
                    "lat": lat,
                    "lon": lon,
                    "frp": frp,
                    "dt": dt,
                    "acq_date": acq_d,
                    "satellite": str(obs.get("satellite") or "VIIRS"),
                    "source": str(obs.get("source") or "VIIRS_NRT")
                })
            except (ValueError, TypeError):
                continue

        n = len(valid_obs)
        if n == 0:
            return {
                "status": "success",
                "start_date": start_date,
                "end_date": end_date,
                "spatial_radius_km": radius,
                "total_observations": 0,
                "total_observations_analyzed": 0,
                "cluster_count": 0,
                "total_clusters": 0,
                "clusters": []
            }

        # 2. Spatial Grid Binning for efficient neighbor lookup
        # 1 degree latitude ~ 111 km. Grid cell size approx radius / 111.0 degrees
        cell_size = max(0.01, radius / 111.0)
        grid: Dict[Tuple[int, int], List[int]] = {}
        for idx, item in enumerate(valid_obs):
            cell_x = int(math.floor(item["lon"] / cell_size))
            cell_y = int(math.floor(item["lat"] / cell_size))
            grid.setdefault((cell_x, cell_y), []).append(idx)

        # 3. Adjacency Graph Construction
        adj: List[List[int]] = [[] for _ in range(n)]
        for idx, item in enumerate(valid_obs):
            cx = int(math.floor(item["lon"] / cell_size))
            cy = int(math.floor(item["lat"] / cell_size))
            # Search adjacent 3x3 grid cells
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor_cell = (cx + dx, cy + dy)
                    for nbr_idx in grid.get(neighbor_cell, []):
                        if nbr_idx > idx:
                            d_km = haversine_distance(item["lat"], item["lon"], valid_obs[nbr_idx]["lat"], valid_obs[nbr_idx]["lon"])
                            if d_km <= radius:
                                adj[idx].append(nbr_idx)
                                adj[nbr_idx].append(idx)

        # 4. Connected Components Detection (BFS)
        visited = [False] * n
        raw_components: List[List[int]] = []

        for i in range(n):
            if not visited[i]:
                comp: List[int] = []
                queue = [i]
                visited[i] = True
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for neighbor in adj[curr]:
                        if not visited[neighbor]:
                            visited[neighbor] = True
                            queue.append(neighbor)
                raw_components.append(comp)

        # 5. Pre-compute sorting keys for strict determinism
        # (earliest_dt, -obs_count, min_lat, min_lon)
        components_with_keys = []
        for comp in raw_components:
            earliest_dt = min(valid_obs[idx]["dt"] for idx in comp)
            min_lat = min(valid_obs[idx]["lat"] for idx in comp)
            min_lon = min(valid_obs[idx]["lon"] for idx in comp)
            components_with_keys.append((earliest_dt, len(comp), min_lat, min_lon, comp))

        components_with_keys.sort(key=lambda x: (x[0], -x[1], x[2], x[3]))

        # 6. Aggregate Spatial, Temporal & FRP Intelligence for each cluster
        date_prefix = start_date.replace("-", "")
        clusters: List[Dict[str, Any]] = []

        for seq, (_, count, _, _, comp) in enumerate(components_with_keys, start=1):
            if count < min_observations:
                continue

            comp_items = [valid_obs[idx] for idx in comp]
            lats = [item["lat"] for item in comp_items]
            lons = [item["lon"] for item in comp_items]
            frps = [item["frp"] for item in comp_items]
            dts = [item["dt"] for item in comp_items]
            distinct_dates = set(item["acq_date"] for item in comp_items)
            satellites = sorted(list(set(item["satellite"] for item in comp_items)))
            sources = sorted(list(set(item["source"] for item in comp_items)))

            centroid_lat = round(sum(lats) / count, 5)
            centroid_lon = round(sum(lons) / count, 5)

            tot_frp = round(sum(frps), 2)
            mean_frp = round(tot_frp / count, 2)
            max_frp = round(max(frps), 2)

            earliest_dt = min(dts)
            latest_dt = max(dts)
            duration_hours = round(max(0.0, (latest_dt - earliest_dt).total_seconds() / 3600.0), 2)
            span_days = len(distinct_dates)

            intensity_level = classify_frp_intensity(max_frp, mean_frp)
            operational_state = classify_operational_state(count, duration_hours, span_days)

            cluster_id = f"CLU-{date_prefix}-{seq:04d}"

            clusters.append({
                "cluster_id": cluster_id,
                "centroid_latitude": centroid_lat,
                "centroid_longitude": centroid_lon,
                "centroid": {"latitude": centroid_lat, "longitude": centroid_lon},
                "observation_count": count,
                "total_frp": tot_frp,
                "mean_frp": mean_frp,
                "max_frp": max_frp,
                "intensity_level": intensity_level,
                "frp_intensity": intensity_level,
                "first_detection": earliest_dt.isoformat(),
                "latest_detection": latest_dt.isoformat(),
                "first_detected": earliest_dt.isoformat(),
                "last_detected": latest_dt.isoformat(),
                "persistence_duration_hours": duration_hours,
                "temporal_span_days": span_days,
                "operational_state": operational_state,
                "satellites": satellites,
                "sources": sources,
                "bbox": {
                    "min_lat": round(min(lats), 5),
                    "max_lat": round(max(lats), 5),
                    "min_lon": round(min(lons), 5),
                    "max_lon": round(max(lons), 5)
                }
            })

        return {
            "status": "success",
            "start_date": start_date,
            "end_date": end_date,
            "spatial_radius_km": radius,
            "total_observations": len(valid_obs),
            "total_observations_analyzed": len(valid_obs),
            "cluster_count": len(clusters),
            "total_clusters": len(clusters),
            "clusters": clusters
        }
