import csv
from concurrent.futures import ThreadPoolExecutor
import datetime
import io
import json
import logging
import os
import sys
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

# Ensure local backend modules are discoverable regardless of execution cwd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from typing import Optional
from geo_validation import validate_geographic_domain
from event_engine import cluster_observations_into_events, get_event_history_payload
from historical_baseline import historical_baseline_manager, get_historical_baseline_manager, HistoricalBaselineManager
from anomaly_analysis import analyze_event_anomaly
from evidence_fusion import fuse_event_evidence
from classification_engine import classify_thermal_event
from india_firms import india_firms_manager
from weather_service import get_weather_for_location, enrich_observations_with_weather
from ml_model import ml_model_service
from event_assessment import assess_event

try:
    from data.firms import FIRMSDatabase, FIRMSIngestionService, FIRMSClient, DEFAULT_INDIA_BBOX, FIRMSAutoSyncScheduler, FIRMSSpatioTemporalClusteringService
except ImportError:
    from backend.data.firms import FIRMSDatabase, FIRMSIngestionService, FIRMSClient, DEFAULT_INDIA_BBOX, FIRMSAutoSyncScheduler, FIRMSSpatioTemporalClusteringService

firms_db = FIRMSDatabase(auto_seed=True)
firms_ingestion_service = FIRMSIngestionService(db=firms_db)
firms_sync_scheduler = FIRMSAutoSyncScheduler(ingestion_service=firms_ingestion_service)
firms_clustering_service = FIRMSSpatioTemporalClusteringService()

DEMO_EVENTS_CACHE = {
    "timestamp": 0.0,
    "events": [],
    "fires": []
}

INDIA_EVENTS_CACHE = {
    "timestamp": 0.0,
    "events": [],
    "fires": []
}

EVENTS_CACHE = DEMO_EVENTS_CACHE
EVENTS_CACHE_LOCK = threading.Lock()


def _ensure_events_cache():
    """
    Ensures both demo events cache (Eastern India 918 observations / 147 events)
    and India-wide events cache (2301 observations / 989 events) are initialized.
    """
    with EVENTS_CACHE_LOCK:
        # 1. Authoritative Eastern India Demo Cache
        if not DEMO_EVENTS_CACHE.get("events"):
            demo_data = india_firms_manager.get_eastern_india_dataset()
            if demo_data and "fires" in demo_data:
                events, clustered_fires = cluster_observations_into_events(demo_data["fires"])
                for ev in events:
                    try:
                        ev["system_classification"] = classify_thermal_event(ev).get("classification", "UNKNOWN")
                    except Exception:
                        ev["system_classification"] = "UNKNOWN"
                DEMO_EVENTS_CACHE["timestamp"] = time.time()
                DEMO_EVENTS_CACHE["events"] = events
                DEMO_EVENTS_CACHE["fires"] = clustered_fires
                logger.info(f"[EVENT_ENGINE] Initialized {len(events)} demo events from Eastern India dataset.")

        # 2. Authentic India-wide Events Cache
        if not INDIA_EVENTS_CACHE.get("events"):
            cached_events = india_firms_manager.load_cached_india_events()
            cached_obs = india_firms_manager.load_cached_india_observations()
            if cached_events and cached_obs:
                INDIA_EVENTS_CACHE["timestamp"] = time.time()
                INDIA_EVENTS_CACHE["events"] = cached_events
                INDIA_EVENTS_CACHE["fires"] = cached_obs.get("fires", [])
                logger.info(f"[EVENT_ENGINE] Loaded {len(cached_events)} India-wide events from disk cache.")
            elif cached_obs:
                events, clustered_fires = cluster_observations_into_events(cached_obs.get("fires", []))
                for ev in events:
                    try:
                        ev["system_classification"] = classify_thermal_event(ev).get("classification", "UNKNOWN")
                    except Exception:
                        ev["system_classification"] = "UNKNOWN"
                INDIA_EVENTS_CACHE["timestamp"] = time.time()
                INDIA_EVENTS_CACHE["events"] = events
                INDIA_EVENTS_CACHE["fires"] = clustered_fires
                india_firms_manager.save_india_events(events, total_observations=len(clustered_fires))
                logger.info(f"[EVENT_ENGINE] Clustered and saved {len(events)} India-wide events.")

        # Synchronize legacy reference
        EVENTS_CACHE["timestamp"] = DEMO_EVENTS_CACHE["timestamp"]
        EVENTS_CACHE["events"] = DEMO_EVENTS_CACHE["events"]
        EVENTS_CACHE["fires"] = DEMO_EVENTS_CACHE["fires"]


def find_event(clean_id: str, mode: Optional[str] = None) -> Optional[dict]:
    """
    Finds a persistent thermal event by event_id across active or demo data modes.
    Guarantees that demo landmark events (EVT-000029, EVT-000001, EVT-000002) remain 100% stable,
    while authentic India-wide events (EVT-000001..EVT-000989) are fully accessible.
    """
    _ensure_events_cache()
    sel_mode = (mode or "").strip().lower()

    with EVENTS_CACHE_LOCK:
        # Landmark EVT-000029 (Dhanbad Coal Belt, 133 observations) is the authoritative human-verified
        # landmark preserved with 133 observations across all modes
        if clean_id == "EVT-000029":
            for ev in DEMO_EVENTS_CACHE.get("events") or []:
                if ev.get("event_id") == "EVT-000029":
                    return ev

        if sel_mode in ("eastern_india", "demo", "east"):
            for ev in DEMO_EVENTS_CACHE.get("events") or []:
                if ev.get("event_id") == clean_id:
                    return ev
            return None

        if sel_mode in ("india", "all_india"):
            for ev in INDIA_EVENTS_CACHE.get("events") or []:
                if ev.get("event_id") == clean_id:
                    return ev
            # Fallback to demo cache if not found in India cache
            for ev in DEMO_EVENTS_CACHE.get("events") or []:
                if ev.get("event_id") == clean_id:
                    return ev
            return None

        # Mode unspecified:
        for ev in DEMO_EVENTS_CACHE.get("events") or []:
            if ev.get("event_id") == clean_id:
                return ev
        for ev in INDIA_EVENTS_CACHE.get("events") or []:
            if ev.get("event_id") == clean_id:
                return ev

        return None

# =========================================================
# CONFIGURATION & ENVIRONMENT
# =========================================================

# Load environment variables from backend/.env or current working directory
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=ENV_FILE)

logger = logging.getLogger("agnivision")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def get_firms_map_key() -> str:
    """Retrieve NASA FIRMS MAP_KEY from NASA_FIRMS_MAP_KEY or FIRMS_MAP_KEY."""
    return (os.environ.get("NASA_FIRMS_MAP_KEY") or os.environ.get("FIRMS_MAP_KEY") or "").strip()


def sanitize_log(message: str, key: str = "") -> str:
    """Sanitize strings to ensure the FIRMS MAP_KEY is never exposed in logs or errors."""
    if not message:
        return ""
    if key and key in message:
        message = message.replace(key, "[REDACTED_MAP_KEY]")
    active_key = get_firms_map_key()
    if active_key and active_key in message:
        message = message.replace(active_key, "[REDACTED_MAP_KEY]")
    return message


# =========================================================
# FASTAPI APP & CORS
# =========================================================

app = FastAPI(title="AGNIVISION-GIS Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://10.44.86.31:5173",
        "http://10.44.86.31:5174",
        "http://10.44.86.31:5175",
        "http://10.44.86.31:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# RISK CALCULATION
# =========================================================

def calculate_risk(brightness, confidence):
    try:
        brightness = float(brightness)
    except (ValueError, TypeError):
        return 0

    confidence_map = {
        "l": 30,
        "n": 60,
        "h": 90,
        "low": 30,
        "nominal": 60,
        "high": 90
    }

    confidence_score = confidence_map.get(
        str(confidence).strip().lower(),
        0
    )

    intensity_score = max(
        0,
        min(
            100,
            (brightness - 300) * 2
        )
    )

    risk = (
        0.6 * intensity_score
        + 0.4 * confidence_score
    )

    return round(risk, 1)


# =========================================================
# CONFIDENCE LABEL
# =========================================================

def get_confidence_label(confidence):
    confidence_map = {
        "l": "Low",
        "n": "Nominal",
        "h": "High",
        "low": "Low",
        "nominal": "Nominal",
        "high": "High"
    }

    return confidence_map.get(
        str(confidence).strip().lower(),
        "Unknown"
    )


# =========================================================
# PERSISTENCE
# =========================================================

def calculate_persistence(fires):
    location_dates = {}

    for fire in fires:
        try:
            lat = float(fire["latitude"])
            lon = float(fire["longitude"])
        except (ValueError, TypeError, KeyError):
            continue

        date = fire.get("acq_date")
        if not date:
            continue

        lat_cell = round(lat, 2)
        lon_cell = round(lon, 2)
        key = (lat_cell, lon_cell)

        if key not in location_dates:
            location_dates[key] = set()

        location_dates[key].add(date)

    for fire in fires:
        try:
            lat = float(fire["latitude"])
            lon = float(fire["longitude"])
        except (ValueError, TypeError, KeyError):
            fire["persistence_days"] = 1
            continue

        lat_cell = round(lat, 2)
        lon_cell = round(lon, 2)
        key = (lat_cell, lon_cell)

        fire["persistence_days"] = len(
            location_dates.get(key, set())
        )


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():
    return {
        "message": "AGNIVISION backend is running"
    }


# =========================================================
# HUMAN VERIFICATION / TRAINING DATASET
# =========================================================

VERIFICATION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "verified_events.json"
)

VERIFICATION_LOCK = threading.Lock()

VERIFICATION_LABELS = {
    "ACTIVE_FIRE",
    "INDUSTRIAL_HEAT",
    "AGRICULTURAL_BURNING",
    "WILDLAND_FIRE",
    "UNKNOWN"
}


def load_verified_events():
    if not os.path.exists(VERIFICATION_FILE):
        return []

    try:
        with open(VERIFICATION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        # Normalize records so event_id, verified, notes, and ai_snapshot metadata are safely accessible
        for rec in data:
            if isinstance(rec, dict):
                rec["event_id"] = rec.get("event_id") or rec.get("features", {}).get("event_id")
                rec["verified"] = True
                if "notes" not in rec:
                    rec["notes"] = rec.get("features", {}).get("analyst_notes") or ""
                if "ai_snapshot" not in rec:
                    rec["ai_snapshot"] = None
                if "ai_snapshot_available" not in rec:
                    rec["ai_snapshot_available"] = bool(rec.get("ai_snapshot"))
                if "feature_vector_available" not in rec:
                    rec["feature_vector_available"] = bool(
                        rec.get("ai_snapshot", {}) and rec["ai_snapshot"].get("features_used") and len(rec["ai_snapshot"]["features_used"]) == 13
                    ) if rec.get("ai_snapshot") else False
        return data
    except Exception as e:
        logger.warning(f"[VERIFY] Dataset load skipped: {e}")
        return []


def save_verified_events(events):
    temp_file = VERIFICATION_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
    os.replace(temp_file, VERIFICATION_FILE)


VERIFIED_EVENTS = load_verified_events()


@app.get("/verified-events")
def get_verified_events():
    with VERIFICATION_LOCK:
        events = list(VERIFIED_EVENTS)

    ai_count = sum(1 for e in events if e.get("ai_snapshot_available") is True)
    fv_count = sum(1 for e in events if e.get("feature_vector_available") is True)

    return {
        "ok": True,
        "count": len(events),
        "ai_snapshots_count": ai_count,
        "feature_vectors_count": fv_count,
        "events": events
    }


@app.get("/verified-events/dataset")
def get_verified_dataset():
    """
    Step 5: Dedicated read-only ground-truth dataset endpoint for future model evaluation.
    Does NOT train or modify records.
    Segregates records with complete AI snapshots vs historical/incomplete records.
    """
    with VERIFICATION_LOCK:
        records = [dict(r) for r in VERIFIED_EVENTS]

    total = len(records)
    complete_ai = [r for r in records if r.get("ai_snapshot_available") is True]
    complete_fv = [r for r in records if r.get("feature_vector_available") is True]
    historical = [r for r in records if not r.get("ai_snapshot_available")]

    label_counts = {lbl: 0 for lbl in sorted(VERIFICATION_LABELS)}
    for r in records:
        lbl = r.get("label")
        if lbl in label_counts:
            label_counts[lbl] += 1
        else:
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

    return {
        "ok": True,
        "total_records": total,
        "complete_ai_snapshots": len(complete_ai),
        "complete_feature_vectors": len(complete_fv),
        "historical_incomplete_records": len(historical),
        "human_label_distribution": label_counts,
        "records": records
    }


@app.post("/verify-event")
def verify_event(payload: dict):
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid request body", "message": "Payload must be a JSON object"}
        )

    raw_label = payload.get("label")
    if not raw_label or not str(raw_label).strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Missing verification label",
                "message": f"Verification label is required and must be one of {sorted(VERIFICATION_LABELS)}",
                "allowed_labels": sorted(VERIFICATION_LABELS)
            }
        )

    label = str(raw_label).strip().upper()
    if label not in VERIFICATION_LABELS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid verification label",
                "message": f"Verification label must be one of {sorted(VERIFICATION_LABELS)}",
                "allowed_labels": sorted(VERIFICATION_LABELS)
            }
        )

    # Extract event_id if provided
    raw_event_id = payload.get("event_id") or payload.get("features", {}).get("event_id")
    clean_id = str(raw_event_id).strip().upper() if raw_event_id else None

    # If event_id is specified, validate that it exists
    target_event = None
    if clean_id:
        target_event = find_event(clean_id, mode=payload.get("mode"))
        if not target_event:
            raise HTTPException(
                status_code=404,
                detail=f"Persistent thermal event '{clean_id}' not found."
            )

    # Extract or infer coordinates
    raw_lat = payload.get("latitude")
    raw_lon = payload.get("longitude")
    if raw_lat is None and target_event:
        raw_lat = target_event.get("centroid", {}).get("latitude")
    if raw_lon is None and target_event:
        raw_lon = target_event.get("centroid", {}).get("longitude")

    if raw_lat is None or raw_lon is None:
        raise HTTPException(
            status_code=400,
            detail="Either a valid event_id or valid (latitude, longitude) coordinates must be provided."
        )

    try:
        latitude = float(raw_lat)
        longitude = float(raw_lon)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="latitude and longitude must be valid numbers"
        )

    features = payload.get("features", {})
    if not isinstance(features, dict):
        raise HTTPException(
            status_code=400,
            detail="features must be an object"
        )

    # Clean free-text notes
    notes = str(payload.get("notes") or features.get("analyst_notes") or "").strip()[:2000]
    # Update notes inside features for schema compatibility
    features["analyst_notes"] = notes
    if clean_id and "event_id" not in features:
        features["event_id"] = clean_id

    # System classification at time of review
    system_class = payload.get("system_classification_at_review")
    if not system_class and target_event:
        system_class = target_event.get("classification")

    source_context = str(payload.get("source_context") or features.get("source") or "AGNIVISION Event Evaluation Station")
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Step 5: Capture complete AI snapshot at the time of human verification
    ai_snapshot = None
    ai_snapshot_available = False
    feature_vector_available = False

    if target_event:
        # 1. ML inference
        ml_class = None
        ml_conf = None
        ml_probs = None
        features_used = None
        try:
            ml_pred = ml_model_service.predict_event(target_event)
            if isinstance(ml_pred, dict) and ml_pred.get("status") == "ready":
                ml_class = ml_pred.get("predicted_class")
                ml_conf = ml_pred.get("confidence")
                ml_probs = ml_pred.get("probabilities")
                features_used = ml_pred.get("features_used")
        except Exception as e:
            logger.warning(f"[VERIFY] Could not capture ML prediction for {clean_id}: {e}")

        # 2. Contextual OSM asset data & baseline
        asset_data = None
        try:
            c = target_event.get("centroid") or {}
            c_lat = c.get("latitude") or latitude
            c_lon = c.get("longitude") or longitude
            if c_lat is not None and c_lon is not None:
                key = asset_cache_key(float(c_lat), float(c_lon), 5000)
                with ASSET_CACHE_LOCK:
                    cached_asset = ASSET_CACHE.get(key)
                if cached_asset:
                    asset_data = cached_asset.get("data")
        except Exception:
            pass

        # 3. Multi-source event assessment
        assessment_label = None
        assessment_conf = None
        assessment_exp = None
        evidence_data = None
        try:
            mgr = get_historical_baseline_manager(payload.get("mode"))
            assessment_res = assess_event(target_event, asset_data=asset_data, baseline_manager=mgr)
            if isinstance(assessment_res, dict) and "assessment" in assessment_res:
                assessment_label = assessment_res.get("assessment")
                assessment_conf = assessment_res.get("assessment_confidence")
                assessment_exp = assessment_res.get("explanation")
                evidence_data = assessment_res.get("evidence")
        except Exception as e:
            logger.warning(f"[VERIFY] Could not capture assessment for {clean_id}: {e}")

        # Evaluate feature vector completeness (exact 13 features)
        fv_required = [
            "brightness", "bright_t31", "frp", "detections_same_cell",
            "active_days_same_cell", "mean_frp_same_cell", "max_frp_same_cell",
            "frp_vs_local_mean", "temperature_c", "u10", "v10",
            "wind_speed_mps", "precipitation_mm"
        ]
        feature_vector_available = bool(features_used and all(k in features_used for k in fv_required))
        ai_snapshot_available = bool(ml_class is not None or assessment_label is not None)

        if ai_snapshot_available:
            ai_snapshot = {
                "ml_class": ml_class,
                "ml_confidence": ml_conf,
                "ml_probabilities": ml_probs,
                "assessment": assessment_label,
                "assessment_confidence": assessment_conf,
                "assessment_explanation": assessment_exp,
                "evidence": evidence_data,
                "features_used": features_used
            }

    with VERIFICATION_LOCK:
        replaced_index = -1
        for index, existing in enumerate(VERIFIED_EVENTS):
            ex_eid = existing.get("event_id") or existing.get("features", {}).get("event_id")
            if clean_id and ex_eid and ex_eid.strip().upper() == clean_id:
                replaced_index = index
                break
            if not clean_id or not ex_eid:
                old_event = existing.get("event", {})
                if (
                    abs(float(old_event.get("latitude", 999)) - latitude) < 0.0001
                    and abs(float(old_event.get("longitude", 999)) - longitude) < 0.0001
                    and old_event.get("acq_date") == payload.get("acq_date")
                    and old_event.get("acq_time") == payload.get("acq_time")
                ):
                    replaced_index = index
                    break

        if replaced_index != -1:
            old_rec = VERIFIED_EVENTS[replaced_index]
            record = {
                "event_id": clean_id or old_rec.get("event_id"),
                "label": label,
                "verified": True,
                "verified_at": old_rec.get("verified_at") or now_iso,
                "updated_at": now_iso,
                "notes": notes,
                "system_classification_at_review": system_class or old_rec.get("system_classification_at_review"),
                "source_context": source_context,
                "ai_snapshot_available": ai_snapshot_available if ai_snapshot is not None else old_rec.get("ai_snapshot_available", False),
                "feature_vector_available": feature_vector_available if ai_snapshot is not None else old_rec.get("feature_vector_available", False),
                "ai_snapshot": ai_snapshot if ai_snapshot is not None else old_rec.get("ai_snapshot"),
                "event": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "acq_date": payload.get("acq_date") or old_rec.get("event", {}).get("acq_date"),
                    "acq_time": payload.get("acq_time") or old_rec.get("event", {}).get("acq_time"),
                    "source": payload.get("source") or old_rec.get("event", {}).get("source", "NASA FIRMS")
                },
                "features": features
            }
            VERIFIED_EVENTS[replaced_index] = record
            replaced = True
        else:
            record = {
                "event_id": clean_id,
                "label": label,
                "verified": True,
                "verified_at": now_iso,
                "updated_at": None,
                "notes": notes,
                "system_classification_at_review": system_class,
                "source_context": source_context,
                "ai_snapshot_available": ai_snapshot_available,
                "feature_vector_available": feature_vector_available,
                "ai_snapshot": ai_snapshot,
                "event": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "acq_date": payload.get("acq_date"),
                    "acq_time": payload.get("acq_time"),
                    "source": payload.get("source", "NASA FIRMS")
                },
                "features": features
            }
            VERIFIED_EVENTS.append(record)
            replaced = False

        save_verified_events(VERIFIED_EVENTS)
        dataset_count = len(VERIFIED_EVENTS)

    return {
        "ok": True,
        "status": "VERIFIED",
        "event_id": clean_id,
        "label": label,
        "replaced_existing": replaced,
        "dataset_count": dataset_count,
        "record": record,
        "saved_to": "verified_events.json"
    }


@app.get("/events/{event_id}/verification")
def get_event_verification(event_id: str, mode: Optional[str] = None):
    """
    Step 9: Human Verification State
    Returns the current human verification status and audit record
    for a specific persistent thermal event.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(
            status_code=404,
            detail=f"Persistent thermal event '{clean_id}' not found."
        )

    with VERIFICATION_LOCK:
        matching_rec = None
        for rec in VERIFIED_EVENTS:
            r_eid = rec.get("event_id") or rec.get("features", {}).get("event_id")
            if r_eid and r_eid.strip().upper() == clean_id:
                matching_rec = rec
                break
            if not r_eid:
                c = target_event.get("centroid") or {}
                e_lat = rec.get("event", {}).get("latitude")
                e_lon = rec.get("event", {}).get("longitude")
                if e_lat is not None and e_lon is not None and c.get("latitude") is not None:
                    if abs(float(e_lat) - float(c["latitude"])) < 0.03 and abs(float(e_lon) - float(c["longitude"])) < 0.03:
                        matching_rec = rec
                        break

    if matching_rec:
        return {
            "event_id": clean_id,
            "status": "VERIFIED",
            "verified": True,
            "label": matching_rec.get("label"),
            "verified_at": matching_rec.get("verified_at"),
            "updated_at": matching_rec.get("updated_at"),
            "notes": matching_rec.get("notes") or matching_rec.get("features", {}).get("analyst_notes") or "",
            "system_classification_at_review": matching_rec.get("system_classification_at_review"),
            "ai_snapshot": matching_rec.get("ai_snapshot"),
            "ai_snapshot_available": matching_rec.get("ai_snapshot_available", False),
            "feature_vector_available": matching_rec.get("feature_vector_available", False),
            "record": matching_rec
        }
    else:
        return {
            "event_id": clean_id,
            "status": "UNVERIFIED",
            "verified": False,
            "label": None,
            "verified_at": None,
            "updated_at": None,
            "notes": "",
            "system_classification_at_review": None,
            "ai_snapshot": None,
            "ai_snapshot_available": False,
            "feature_vector_available": False,
            "record": None
        }


# =========================================================
# GEOGRAPHIC DOMAIN VALIDATION
# =========================================================

@app.get("/geo-validate")
def geo_validate(lat: str = "", lon: str = "", resolve_detailed: bool = False):
    """
    Validate and classify the geographic & land-cover domain of an observation coordinate.
    Accepts latitude and longitude as query parameters.
    Returns domain, status, administrative attribution (state, district, city), and source.
    """
    return validate_geographic_domain(lat, lon, resolve_detailed=resolve_detailed)


# =========================================================
# ATMOSPHERIC WEATHER & WIND (OPEN-METEO)
# =========================================================

@app.get("/weather")
def get_weather_endpoint(lat: float, lon: float):
    """
    Step 1: Test/debug endpoint to retrieve authentic atmospheric weather
    and wind data from Open-Meteo for a given latitude and longitude.
    """
    return get_weather_for_location(lat, lon)


# =========================================================
# FIRMS FIRE DATA
# =========================================================

@app.get("/fires")
def get_fires(mode: Optional[str] = None, region: Optional[str] = None):
    selected_mode = (mode or region or "india").strip().lower()

    # PRESERVED EASTERN INDIA DEMO MODE (West 82, South 20, East 90, North 27)
    if selected_mode in ("eastern_india", "demo", "east"):
        total_start = time.time()
        demo_data = india_firms_manager.get_eastern_india_dataset()
        if demo_data and "fires" in demo_data:
            fires_list = demo_data["fires"]
            enrich_observations_with_weather(fires_list)
            return {
                "mode": "eastern_india",
                "region": "Eastern India Demo Region",
                "bbox": "82,20,90,27",
                "source": "VIIRS_NOAA20_NRT",
                "count": len(fires_list),
                "fires": fires_list,
                "timing": {
                    "total_seconds": round(time.time() - total_start, 2)
                }
            }

    # DEFAULT: INDIA-WIDE NATIONAL COVERAGE (Bounding box: West 67, South 7, East 98, North 38)
    if selected_mode == "india" or selected_mode not in ("eastern_india", "demo", "east"):
        total_start = time.time()
        india_data = india_firms_manager.load_cached_india_observations()
        if not india_data:
            map_key = get_firms_map_key()
            if not map_key:
                raise HTTPException(
                    status_code=500,
                    detail="FIRMS_MAP_KEY is missing or not configured on the server. Please set FIRMS_MAP_KEY in backend/.env"
                )
            india_data = india_firms_manager.fetch_and_cache_india_observations(
                map_key,
                validate_geo_func=validate_geographic_domain,
                calc_risk_func=calculate_risk,
                conf_label_func=get_confidence_label
            )

        fires_list = india_data.get("fires", [])
        enrich_observations_with_weather(fires_list)
        return {
            "mode": "india",
            "region": "India-wide National Coverage",
            "bbox": "67,7,98,38",
            "source": "VIIRS_NOAA20_NRT",
            "count": india_data.get("count", len(fires_list)),
            "observations_outside_eastern_bbox": india_data.get("observations_outside_eastern_bbox", 0),
            "retrieved_at": india_data.get("retrieved_at"),
            "fires": fires_list,
            "timing": {
                "total_seconds": round(time.time() - total_start, 2)
            }
        }

    # FALLBACK / FETCH EASTERN INDIA DEMO MODE (West 82, South 20, East 90, North 27)
    total_start = time.time()
    map_key = get_firms_map_key()

    if not map_key:
        logger.error("[FIRMS] FIRMS_MAP_KEY environment variable is not configured.")
        raise HTTPException(
            status_code=500,
            detail="FIRMS_MAP_KEY is missing or not configured on the server. Please set FIRMS_MAP_KEY in backend/.env"
        )

    # Source and bounding box: VIIRS NOAA-20 NRT, India bounding box (West 82, South 20, East 90, North 27, 10-day range)
    source = "VIIRS_NOAA20_NRT"
    bbox = "82,20,90,27"

    # NASA FIRMS Area API allows a maximum of 5 days per single query (day_range [1..5]).
    # To cover a full 10-day NRT window without gaps, we retrieve two contiguous 5-day intervals:
    # 1. 5 days starting 9 days ago (acq_dates t-9 through t-5)
    # 2. Most recent 5 days up to today (acq_dates t-4 through t)
    today = datetime.date.today()
    start_date_earlier = (today - datetime.timedelta(days=9)).strftime("%Y-%m-%d")

    target_urls = [
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{bbox}/5/{start_date_earlier}",
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{bbox}/5"
    ]

    firms_start = time.time()
    raw_texts = []

    for url in target_urls:
        redacted_url = sanitize_log(url, map_key)
        logger.info(f"[FIRMS] Fetching observations from: {redacted_url}")

        try:
            response = requests.get(url, timeout=15)
        except requests.Timeout:
            logger.error(f"[FIRMS] Request timed out after 15s when querying FIRMS ({redacted_url})")
            raise HTTPException(
                status_code=504,
                detail="NASA FIRMS request timed out after 15 seconds. NASA servers may be experiencing high latency."
            )
        except requests.RequestException as e:
            safe_error = sanitize_log(str(e), map_key)
            logger.error(f"[FIRMS] Network exception connecting to NASA FIRMS: {safe_error}")
            raise HTTPException(
                status_code=502,
                detail=f"Could not connect to NASA FIRMS: {safe_error}"
            )

        if response.status_code != 200:
            safe_body = sanitize_log(response.text[:300], map_key).strip()
            logger.error(f"[FIRMS] NASA API returned HTTP {response.status_code}: {safe_body}")

            if response.status_code == 400 and "invalid map_key" in response.text.lower():
                raise HTTPException(
                    status_code=401,
                    detail="NASA FIRMS rejected the MAP_KEY as invalid. Please verify FIRMS_MAP_KEY in backend/.env."
                )

            raise HTTPException(
                status_code=502,
                detail=f"NASA FIRMS API returned HTTP {response.status_code}: {safe_body}"
            )

        raw_text = response.text.strip()
        if raw_text.startswith("<!DOCTYPE") or raw_text.startswith("<html"):
            logger.error("[FIRMS] NASA FIRMS returned HTML instead of CSV.")
            raise HTTPException(
                status_code=502,
                detail="NASA FIRMS returned an unexpected HTML response instead of CSV data."
            )

        if raw_text:
            raw_texts.append(raw_text)

    firms_time = round(time.time() - firms_start, 2)

    # Empty FIRMS response handling
    if not raw_texts:
        logger.warning("[FIRMS] NASA FIRMS returned an empty response body.")
        return {
            "count": 0,
            "fires": [],
            "timing": {
                "firms_request_seconds": firms_time,
                "persistence_seconds": 0.0,
                "risk_calculation_seconds": 0.0,
                "total_seconds": round(time.time() - total_start, 2)
            }
        }

    raw_rows = []
    headers = []
    for raw_text in raw_texts:
        try:
            csv_file = io.StringIO(raw_text)
            reader = csv.reader(csv_file)
            batch_headers = [h.strip() for h in next(reader, [])]
            if not headers and batch_headers:
                headers = batch_headers
            for row in reader:
                if len(row) == len(batch_headers):
                    raw_rows.append(dict(zip(batch_headers, [col.strip() for col in row])))
        except Exception as e:
            logger.error(f"[FIRMS] Failed to parse CSV: {e}")
            raise HTTPException(
                status_code=502,
                detail="NASA FIRMS returned a malformed CSV response."
            )

    if not headers or "latitude" not in headers or "longitude" not in headers:
        logger.error(f"[FIRMS] Malformed CSV from NASA FIRMS. Header: {headers}")
        raise HTTPException(
            status_code=502,
            detail="NASA FIRMS returned malformed CSV data without coordinate columns."
        )

    # Deduplicate strictly across overlapping observation intervals
    seen = set()
    fires = []
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

        # Preserve actual FIRMS observation fields across sensors (MODIS / VIIRS)
        # VIIRS provides bright_ti4 (4µm) and bright_ti5 (11µm); MODIS provides brightness
        if "brightness" not in fire and "bright_ti4" in fire:
            fire["brightness"] = fire["bright_ti4"]
        elif "bright_ti4" not in fire and "brightness" in fire:
            fire["bright_ti4"] = fire["brightness"]

        if "type" not in fire:
            fire["type"] = None

        fires.append(fire)

    # Geographic Domain Validation
    # Evaluates land-cover domain (LAND, INLAND_WATER, COASTAL_NEAR_SHORE, OFFSHORE_MARINE, UNKNOWN_UNRESOLVED)
    # Uses in-memory spatial index and reuse cache to prevent expensive or redundant reverse geocoding
    geo_start = time.time()
    batch_geo_cache = {}
    for fire in fires:
        lat_val = fire.get("latitude")
        lon_val = fire.get("longitude")
        try:
            cache_key = (round(float(lat_val), 4), round(float(lon_val), 4))
        except (ValueError, TypeError):
            cache_key = None

        if cache_key and cache_key in batch_geo_cache:
            fire["geographic_validation"] = dict(batch_geo_cache[cache_key])
        else:
            validation_result = validate_geographic_domain(lat_val, lon_val, resolve_detailed=False)
            fire["geographic_validation"] = validation_result
            if cache_key:
                batch_geo_cache[cache_key] = validation_result

    geo_time = round(time.time() - geo_start, 2)

    # Persistence calculation
    persistence_start = time.time()
    calculate_persistence(fires)
    persistence_time = round(time.time() - persistence_start, 2)

    # Risk calculation
    risk_start = time.time()
    for fire in fires:
        raw_confidence = fire.get("confidence") or ""
        fire["confidence_label"] = get_confidence_label(raw_confidence)

        base_risk = calculate_risk(
            fire.get("bright_ti4"),
            raw_confidence
        )

        persistence = fire.get("persistence_days", 1)
        if persistence >= 3:
            persistence_bonus = 20
        elif persistence == 2:
            persistence_bonus = 10
        else:
            persistence_bonus = 0

        final_risk = min(100, base_risk + persistence_bonus)
        fire["risk_score"] = round(final_risk, 1)

        if fire["risk_score"] >= 80:
            fire["risk_level"] = "Critical"
        elif fire["risk_score"] >= 60:
            fire["risk_level"] = "High"
        elif fire["risk_score"] >= 30:
            fire["risk_level"] = "Moderate"
        else:
            fire["risk_level"] = "Low"

    risk_time = round(time.time() - risk_start, 2)

    # Event Clustering
    # Groups discrete FIRMS observations into persistent spatiotemporal Events
    cluster_start = time.time()
    events, fires = cluster_observations_into_events(fires)
    cluster_time = round(time.time() - cluster_start, 2)

    for ev in events:
        try:
            ev["system_classification"] = classify_thermal_event(ev).get("classification", "UNKNOWN")
        except Exception:
            ev["system_classification"] = "UNKNOWN"

    with EVENTS_CACHE_LOCK:
        DEMO_EVENTS_CACHE["timestamp"] = time.time()
        DEMO_EVENTS_CACHE["events"] = events
        DEMO_EVENTS_CACHE["fires"] = fires
        EVENTS_CACHE["timestamp"] = time.time()
        EVENTS_CACHE["events"] = events
        EVENTS_CACHE["fires"] = fires

    total_time = round(time.time() - total_start, 2)

    # Asynchronously prefetch top-priority OSM assets in the background
    prefetch_assets(fires)

    # Persist Eastern India snapshot to disk for immutable demo stability
    india_firms_manager.save_eastern_india_snapshot(fires)

    # Enrich observations with authentic Open-Meteo atmospheric features
    enrich_observations_with_weather(fires)

    return {
        "count": len(fires),
        "fires": fires,
        "timing": {
            "firms_request_seconds": firms_time,
            "geo_validation_seconds": geo_time,
            "persistence_seconds": persistence_time,
            "risk_calculation_seconds": risk_time,
            "clustering_seconds": cluster_time,
            "total_seconds": total_time
        }
    }


@app.get("/fires/india")
def get_india_fires():
    """
    Dedicated endpoint for authentic India-wide NASA FIRMS VIIRS NOAA-20 NRT observations.
    Bounding box: West 67, South 7, East 98, North 38.
    """
    return get_fires(mode="india")


@app.get("/fires/modes")
def get_fires_modes():
    """
    Returns available FIRMS data modes and metadata:
    - eastern_india: Eastern India demo region (bbox 82,20,90,27, 918 observations)
    - india: Full-India national coverage (bbox 67,7,98,38, 2301 observations)
    """
    return india_firms_manager.get_status()


@app.get("/fires/demo")
def get_demo_fires():
    """
    Dedicated endpoint for the authoritative 918-observation Eastern India demo dataset.
    Bounding box: West 82, South 20, East 90, North 27.
    """
    return get_fires(mode="eastern_india")


# =========================================================
# EVENTS INTELLIGENCE LAYER
# =========================================================

@app.get("/events")
def get_events(mode: Optional[str] = None):
    """
    Retrieve persistent thermal events generated from NASA FIRMS observations
    via rule-based spatiotemporal clustering.
    Supports mode='eastern_india' (147 demo events) or mode='india' (989 events).
    """
    _ensure_events_cache()
    selected_mode = (mode or "").strip().lower()
    with EVENTS_CACHE_LOCK:
        if selected_mode in ("eastern_india", "demo", "east"):
            ev_list = DEMO_EVENTS_CACHE["events"]
            fi_list = DEMO_EVENTS_CACHE["fires"]
        elif selected_mode in ("india", "all_india"):
            ev_list = INDIA_EVENTS_CACHE["events"]
            fi_list = INDIA_EVENTS_CACHE["fires"]
        else:
            if INDIA_EVENTS_CACHE["events"]:
                ev_list = INDIA_EVENTS_CACHE["events"]
                fi_list = INDIA_EVENTS_CACHE["fires"]
            else:
                ev_list = DEMO_EVENTS_CACHE["events"]
                fi_list = DEMO_EVENTS_CACHE["fires"]

        return {
            "count": len(ev_list),
            "total_observations": len(fi_list),
            "events": ev_list
        }


@app.get("/ml/predict")
def ml_predict(
    event_id: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    brightness: Optional[float] = None,
    bright_t31: Optional[float] = None,
    frp: Optional[float] = None,
    mode: Optional[str] = None,
    model_version: Optional[str] = None
):
    """
    ML Model Inference Endpoint supporting:
      - V1: 25-feature production model (legacy fallback)
      - V2: 28-feature Candidate B model (enhanced with context distances)
    Returns: status, predicted_class, confidence, probabilities, features_used, model_version, and feature_schema_version.
    """
    if event_id:
        clean_id = event_id.strip().upper()
        target_event = find_event(clean_id, mode=mode)
        if not target_event:
            raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")
        result = ml_model_service.predict_event(target_event, model_version=model_version)
        result["event_id"] = clean_id
        return result

    if lat is not None and lon is not None:
        obs = {
            "latitude": lat,
            "longitude": lon,
            "brightness": brightness,
            "bright_t31": bright_t31,
            "frp": frp
        }
        return ml_model_service.predict_observation(obs, model_version=model_version)

    raise HTTPException(
        status_code=400,
        detail="Please provide either 'event_id' (e.g. ?event_id=EVT-000029) or coordinates ('lat' and 'lon')."
    )


@app.get("/ml/metadata")
def ml_metadata(version: Optional[str] = None):
    """
    Returns diagnostic inspection metadata for the trained Random Forest classifier.
    Pass version='v2' for the 28-feature Candidate B model metadata, or 'v1' for legacy production model.
    """
    return ml_model_service.get_model_metadata(version=version)


@app.get("/events/{event_id}")
def get_event_by_id(event_id: str, mode: Optional[str] = None):
    """
    Retrieve details, aggregated metadata, and all member observations for a specific persistent thermal event.
    Enriched safely with ML Random Forest classification prediction.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")
    
    event_copy = dict(target_event)
    try:
        event_copy["ml_prediction"] = ml_model_service.predict_event(target_event)
        if ml_model_service.is_ready("v2"):
            event_copy["ml_prediction_v2"] = ml_model_service.predict_event(target_event, model_version="v2")
        if ml_model_service.is_ready("v3"):
            event_copy["ml_prediction_v3"] = ml_model_service.predict_event(target_event, model_version="v3")
    except Exception as e:
        logger.warning(f"[ML_MODEL] Could not compute ML prediction for event {clean_id}: {e}")
        event_copy["ml_prediction"] = {"status": "unavailable", "reason": str(e)}

    # Contextual OSM asset data if available
    asset_data = None
    centroid = target_event.get("centroid") or {}
    c_lat = centroid.get("latitude")
    c_lon = centroid.get("longitude")
    if c_lat is not None and c_lon is not None:
        try:
            key = asset_cache_key(float(c_lat), float(c_lon), 5000)
            with ASSET_CACHE_LOCK:
                cached_asset = ASSET_CACHE.get(key)
            if cached_asset:
                asset_data = cached_asset.get("data")
        except (ValueError, TypeError):
            pass

    # Safely attach multi-source event assessment
    try:
        mgr = get_historical_baseline_manager(mode)
        event_copy["event_assessment"] = assess_event(target_event, asset_data=asset_data, baseline_manager=mgr)
    except Exception as e:
        logger.warning(f"[ASSESSMENT] Could not compute assessment for event {clean_id}: {e}")
        event_copy["event_assessment"] = None

    return event_copy


@app.get("/events/{event_id}/assessment")
def get_event_assessment(event_id: str, mode: Optional[str] = None):
    """
    Step 3: Evidence-Based Event Assessment Layer
    Synthesizes ML prediction, FIRMS thermal radiance, persistence, historical anomaly,
    and contextual OSM infrastructure into an explainable assessment.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")

    mgr = get_historical_baseline_manager(mode)
    _ensure_historical_baseline(mgr)

    asset_data = None
    centroid = target_event.get("centroid") or {}
    c_lat = centroid.get("latitude")
    c_lon = centroid.get("longitude")
    if c_lat is not None and c_lon is not None:
        try:
            key = asset_cache_key(float(c_lat), float(c_lon), 5000)
            with ASSET_CACHE_LOCK:
                cached_asset = ASSET_CACHE.get(key)
            if cached_asset:
                asset_data = cached_asset.get("data")
        except (ValueError, TypeError):
            pass

    return assess_event(target_event, asset_data=asset_data, baseline_manager=mgr)


@app.get("/events/{event_id}/history")
def get_event_history(event_id: str, mode: Optional[str] = None):
    """
    Retrieve the chronological observation history and spatiotemporal summaries
    for a specific persistent thermal event.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")
    return get_event_history_payload(target_event)


@app.get("/events/{event_id}/anomaly")
def get_event_anomaly(event_id: str, mode: Optional[str] = None):
    """
    Step 6: Event-vs-Historical-Baseline Anomaly Analysis
    Compares the selected persistent thermal event against the 0.1° historical baseline.
    """
    mgr = get_historical_baseline_manager(mode)
    _ensure_historical_baseline(mgr)
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")
    return analyze_event_anomaly(target_event, mgr)


@app.get("/events/{event_id}/evidence")
def get_event_evidence(event_id: str, mode: Optional[str] = None):
    """
    Step 7: Evidence Fusion / Source Assessment
    Collects, organizes, and assesses the strength and limitations of all evidence
    available for the selected persistent thermal event across 7 dimensions.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")

    # 1. Step 6 Historical Anomaly Analysis (reusing existing baseline engine)
    mgr = get_historical_baseline_manager(mode)
    anomaly_result = None
    try:
        if mgr.is_loaded:
            anomaly_result = analyze_event_anomaly(target_event, mgr)
        else:
            map_key = get_firms_map_key()
            if map_key:
                mgr.load_or_fetch(map_key)
                if mgr.is_loaded:
                    anomaly_result = analyze_event_anomaly(target_event, mgr)
    except Exception as e:
        logger.warning(f"[EVIDENCE_FUSION] Historical baseline anomaly query error: {sanitize_log(str(e))}")

    # 2. Contextual OSM facility lookup
    centroid = target_event.get("centroid") or {}
    c_lat = centroid.get("latitude")
    c_lon = centroid.get("longitude")
    asset_data = None

    if c_lat is not None and c_lon is not None:
        try:
            lat_f = float(c_lat)
            lon_f = float(c_lon)
            key = asset_cache_key(lat_f, lon_f, 5000)
            with ASSET_CACHE_LOCK:
                cached_asset = ASSET_CACHE.get(key)
            if cached_asset:
                asset_data = cached_asset.get("data")
            else:
                with ASSET_CACHE_LOCK:
                    inflight = key in ASSET_INFLIGHT
                if not inflight:
                    ASSET_EXECUTOR.submit(fetch_and_cache_assets, lat_f, lon_f, 5000)
        except (ValueError, TypeError):
            pass

    # 3. Fuse evidence profile
    return fuse_event_evidence(target_event, anomaly_result=anomaly_result, asset_data=asset_data)


@app.get("/events/{event_id}/classification")
def get_event_classification(event_id: str, mode: Optional[str] = None):
    """
    Step 8: Thermal Event Classification Engine
    Produces a transparent, deterministic rule-based source classification
    for a persistent thermal event.
    """
    clean_id = event_id.strip().upper()
    target_event = find_event(clean_id, mode=mode)
    if not target_event:
        raise HTTPException(status_code=404, detail=f"Persistent thermal event '{clean_id}' not found.")

    # 1. Historical Anomaly lookup
    mgr = get_historical_baseline_manager(mode)
    anomaly_result = None
    try:
        if mgr.is_loaded:
            anomaly_result = analyze_event_anomaly(target_event, mgr)
        else:
            map_key = get_firms_map_key()
            if map_key:
                mgr.load_or_fetch(map_key)
                if mgr.is_loaded:
                    anomaly_result = analyze_event_anomaly(target_event, mgr)
    except Exception as e:
        logger.warning(f"[CLASSIFICATION] Historical baseline anomaly query error: {sanitize_log(str(e))}")

    # 2. Contextual OSM facility lookup
    centroid = target_event.get("centroid") or {}
    c_lat = centroid.get("latitude")
    c_lon = centroid.get("longitude")
    asset_data = None

    if c_lat is not None and c_lon is not None:
        try:
            lat_f = float(c_lat)
            lon_f = float(c_lon)
            key = asset_cache_key(lat_f, lon_f, 5000)
            with ASSET_CACHE_LOCK:
                cached_asset = ASSET_CACHE.get(key)
            if cached_asset:
                asset_data = cached_asset.get("data")
            else:
                with ASSET_CACHE_LOCK:
                    inflight = key in ASSET_INFLIGHT
                if not inflight:
                    ASSET_EXECUTOR.submit(fetch_and_cache_assets, lat_f, lon_f, 5000)
        except (ValueError, TypeError):
            pass

    # 3. Fuse evidence profile
    evidence_profile = fuse_event_evidence(target_event, anomaly_result=anomaly_result, asset_data=asset_data)

    # 4. Classify event
    return classify_thermal_event(
        event=target_event,
        evidence_profile=evidence_profile,
        anomaly_result=anomaly_result,
        asset_data=asset_data
    )


# =========================================================
# OPENSTREETMAP ASSETS
# =========================================================

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

ASSET_CACHE = {}
ASSET_CACHE_TTL = 600  # 10 minutes
ASSET_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "asset_cache.json"
)

ASSET_CACHE_LOCK = threading.Lock()
ASSET_INFLIGHT = set()
ASSET_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def empty_asset_counts():
    return {
        "hospitals": 0,
        "schools": 0,
        "buildings": 0,
        "roads": 0,
        "power": 0,
        "industrial": 0
    }


def asset_cache_key(lat, lon, radius):
    return (round(lat, 3), round(lon, 3), radius)


def asset_cache_key_string(key):
    return f"{key[0]:.3f},{key[1]:.3f},{key[2]}"


def load_asset_cache():
    if not os.path.exists(ASSET_CACHE_FILE):
        return

    try:
        with open(ASSET_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        with ASSET_CACHE_LOCK:
            for key_string, entry in raw.items():
                lat, lon, radius = key_string.split(",")
                ASSET_CACHE[(float(lat), float(lon), int(radius))] = entry
    except Exception as e:
        logger.warning(f"[ASSETS] Cache load skipped: {e}")


def save_asset_cache():
    try:
        with ASSET_CACHE_LOCK:
            raw = {
                asset_cache_key_string(key): value
                for key, value in ASSET_CACHE.items()
            }

        temp_file = ASSET_CACHE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.replace(temp_file, ASSET_CACHE_FILE)
    except Exception as e:
        logger.warning(f"[ASSETS] Cache save skipped: {e}")


load_asset_cache()


def build_asset_query(lat, lon, radius):
    return f"""
    [out:json][timeout:25];

    (
        nwr["amenity"="hospital"]
            (around:{radius},{lat},{lon});

        nwr["amenity"="school"]
            (around:{radius},{lat},{lon});

        nwr["building"]
            (around:{radius},{lat},{lon});

        nwr["power"="substation"]
            (around:{radius},{lat},{lon});

        nwr["power"="plant"]
            (around:{radius},{lat},{lon});

        nwr["industrial"]
            (around:{radius},{lat},{lon});

        nwr["highway"~"^(primary|secondary|tertiary)$"]
            (around:{radius},{lat},{lon});
    );

    out center;
    """


def query_overpass(lat, lon, radius):
    query = build_asset_query(lat, lon, radius)

    headers = {
        "User-Agent": "AGNIVISION-GIS/1.0",
        "Accept": "application/json"
    }

    last_error = None

    for overpass_url in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(
                overpass_url,
                data=query,
                headers=headers,
                timeout=7
            )

            if response.status_code == 200:
                try:
                    return response.json(), None
                except ValueError:
                    last_error = "Invalid JSON response"
            else:
                last_error = f"HTTP {response.status_code}"

        except requests.RequestException as e:
            last_error = str(e)

    return None, last_error


LOCAL_OSM_DF_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "osm_industrial_facilities.joblib"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ml_training_v2", "context", "osm_industrial_facilities.parquet"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "context", "osm_industrial_facilities.parquet"),
]
_LOCAL_OSM_DF = None
_LOCAL_OSM_DF_LOCK = threading.Lock()


def _get_local_osm_df():
    global _LOCAL_OSM_DF
    with _LOCAL_OSM_DF_LOCK:
        if _LOCAL_OSM_DF is not None:
            return _LOCAL_OSM_DF
        for path in LOCAL_OSM_DF_PATHS:
            if os.path.exists(path):
                try:
                    if path.endswith(".joblib"):
                        import joblib
                        _LOCAL_OSM_DF = joblib.load(path)
                    else:
                        import pandas as pd
                        _LOCAL_OSM_DF = pd.read_parquet(path)
                    logger.info(f"[ASSETS] Loaded local OSM industrial dataframe: {len(_LOCAL_OSM_DF)} rows")
                    return _LOCAL_OSM_DF
                except Exception as e:
                    logger.warning(f"[ASSETS] Failed loading local OSM dataframe {path}: {e}")
        return None


def get_local_osm_fallback(lat, lon, radius=5000):
    """
    Safe offline/local fallback when Overpass is unavailable, slow, or times out.
    Queries the pre-compiled static OSM industrial facilities spatial index.

    SAFETY & ACCURACY GUARANTEES:
    - Queries the validated 47,660 OSM industrial facilities index.
    - Preserves 5km radius semantics.
    - Only populates industrial count and facilities supported by the local index.
    - Does NOT fabricate buildings, hospitals, schools, roads, or power-grid counts;
      those unsupported categories strictly remain 0.
    """
    counts = empty_asset_counts()
    assets = []

    try:
        from ml_context import context_registry_manager, to_km_coords_single
        if context_registry_manager.is_ready:
            radius_km = float(radius) / 1000.0
            q = to_km_coords_single(float(lat), float(lon))
            indices = context_registry_manager._osm_tree.query_ball_point(q[0], radius_km)
            counts["industrial"] = len(indices)

            df = _get_local_osm_df()
            if df is not None and len(indices) > 0:
                for idx in indices[:50]:
                    try:
                        row = df[idx] if isinstance(df, list) else df.iloc[idx]
                        name = str(row.get("name", "") if isinstance(row, dict) else row["name"]).strip()
                        if name == "nan":
                            name = ""
                        feat = str(row.get("feature_type", "industrial") if isinstance(row, dict) else row.get("feature_type", "industrial"))
                        if not name:
                            name = feat.replace("landuse:", "").replace("man_made:", "").capitalize() or "Industrial Facility"
                        assets.append({
                            "type": "industrial",
                            "name": name,
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"])
                        })
                    except Exception:
                        continue
    except Exception as e:
        logger.warning(f"[ASSETS] Local OSM fallback query failed: {e}")

    return {
        "ok": True,
        "center": {
            "latitude": lat,
            "longitude": lon
        },
        "radius_m": radius,
        "counts": counts,
        "assets": assets,
        "source": "OpenStreetMap / Local Offline Fallback",
        "cached": False,
        "fallback": True
    }


def parse_asset_response(lat, lon, radius, data):
    elements = data.get("elements", [])
    assets = []
    counts = empty_asset_counts()

    for element in elements:
        tags = element.get("tags", {})

        asset_lat = element.get("lat")
        asset_lon = element.get("lon")

        if asset_lat is None:
            center = element.get("center", {})
            asset_lat = center.get("lat")
            asset_lon = center.get("lon")

        if asset_lat is None or asset_lon is None:
            continue

        asset_type = "other"

        if tags.get("amenity") == "hospital":
            asset_type = "hospital"
            counts["hospitals"] += 1
        elif tags.get("amenity") == "school":
            asset_type = "school"
            counts["schools"] += 1
        elif "industrial" in tags:
            asset_type = "industrial"
            counts["industrial"] += 1
        elif tags.get("power") in ["substation", "plant"]:
            asset_type = "power"
            counts["power"] += 1
        elif tags.get("highway"):
            asset_type = "road"
            counts["roads"] += 1
        elif "building" in tags:
            asset_type = "building"
            counts["buildings"] += 1

        assets.append({
            "type": asset_type,
            "name": tags.get("name", "Unnamed"),
            "latitude": asset_lat,
            "longitude": asset_lon
        })

    # Keep all infrastructure, cap dense building markers for browser performance
    buildings = [a for a in assets if a["type"] == "building"]
    important_assets = [a for a in assets if a["type"] != "building"]

    assets = important_assets + buildings[:250]

    return {
        "ok": True,
        "center": {
            "latitude": lat,
            "longitude": lon
        },
        "radius_m": radius,
        "counts": counts,
        "assets": assets,
        "source": "OpenStreetMap / Overpass",
        "cached": False
    }


def fetch_and_cache_assets(lat, lon, radius=5000):
    key = asset_cache_key(lat, lon, radius)

    with ASSET_CACHE_LOCK:
        if key in ASSET_INFLIGHT:
            return
        ASSET_INFLIGHT.add(key)

    try:
        logger.info(f"[ASSETS] Background fetch started: {key}")
        data, error = query_overpass(lat, lon, radius)

        if data is not None:
            result = parse_asset_response(lat, lon, radius, data)
            logger.info(f"[ASSETS] Overpass query succeeded: {key} -> {result['counts']}")
        else:
            logger.warning(f"[ASSETS] Overpass unavailable ({error}). Engaging local OSM fallback: {key}")
            result = get_local_osm_fallback(lat, lon, radius)
            logger.info(f"[ASSETS] Local fallback used: {key} -> {result['counts']}")

        with ASSET_CACHE_LOCK:
            ASSET_CACHE[key] = {
                "timestamp": time.time(),
                "data": result
            }

        save_asset_cache()
        logger.info(f"[ASSETS] Cached: {key} -> {result['counts']}")

    finally:
        with ASSET_CACHE_LOCK:
            ASSET_INFLIGHT.discard(key)


def prefetch_assets(fires, radius=5000):
    candidates = []

    for fire in fires:
        try:
            lat = float(fire["latitude"])
            lon = float(fire["longitude"])
            risk = float(fire.get("risk_score", 0))
        except (ValueError, TypeError, KeyError):
            continue

        candidates.append((risk, lat, lon))

    # Only prefetch the five highest-risk events to prevent Overpass overload
    candidates.sort(reverse=True)
    candidates = candidates[:5]

    for _, lat, lon in candidates:
        key = asset_cache_key(lat, lon, radius)

        with ASSET_CACHE_LOCK:
            cached = ASSET_CACHE.get(key)
            fresh = (
                cached is not None
                and time.time() - cached["timestamp"] < ASSET_CACHE_TTL
            )
            already_running = key in ASSET_INFLIGHT

        if fresh or already_running:
            continue

        ASSET_EXECUTOR.submit(
            fetch_and_cache_assets,
            lat,
            lon,
            radius
        )


@app.get("/assets")
def get_assets(
    lat: float,
    lon: float,
    radius: int = 5000
):
    key = asset_cache_key(lat, lon, radius)

    with ASSET_CACHE_LOCK:
        cached = ASSET_CACHE.get(key)
        inflight = key in ASSET_INFLIGHT

    if cached:
        age = time.time() - cached["timestamp"]
        result = cached["data"].copy()
        result["cached"] = True
        result["cache_age_seconds"] = round(age)

        if age >= ASSET_CACHE_TTL and not inflight:
            ASSET_EXECUTOR.submit(
                fetch_and_cache_assets,
                lat,
                lon,
                radius
            )
            result["refreshing"] = True

        return result

    if not inflight:
        ASSET_EXECUTOR.submit(
            fetch_and_cache_assets,
            lat,
            lon,
            radius
        )

    return {
        "ok": True,
        "status": "loading",
        "center": {
            "latitude": lat,
            "longitude": lon
        },
        "radius_m": radius,
        "counts": empty_asset_counts(),
        "assets": [],
        "source": "OpenStreetMap / Overpass",
        "cached": False
    }


# =========================================================
# HISTORICAL BASELINE FOUNDATION (STEP 5)
# =========================================================

def _ensure_historical_baseline(mgr: Optional[HistoricalBaselineManager] = None):
    """Ensure the historical baseline is loaded, fetching on-demand if necessary."""
    target_mgr = mgr or historical_baseline_manager
    if not target_mgr.is_loaded:
        map_key = get_firms_map_key()
        if not map_key:
            raise HTTPException(
                status_code=500,
                detail="FIRMS_MAP_KEY is missing or not configured on the server. Please set FIRMS_MAP_KEY in backend/.env"
            )
        try:
            target_mgr.load_or_fetch(map_key)
        except Exception as e:
            safe_err = sanitize_log(str(e))
            logger.error(f"[HISTORICAL] Error loading historical baseline: {safe_err}")
            raise HTTPException(
                status_code=502,
                detail=f"Failed to retrieve NASA FIRMS historical baseline: {safe_err}"
            )


@app.on_event("startup")
def startup_services():
    """Start background services on server startup."""
    # 1. Preload historical baseline in background if MAP_KEY is present
    map_key = get_firms_map_key()
    if map_key:
        def _bg_load():
            try:
                historical_baseline_manager.load_or_fetch(map_key)
            except Exception as e:
                logger.warning(f"[HISTORICAL] Background baseline preload warning: {sanitize_log(str(e))}")
        threading.Thread(target=_bg_load, daemon=True).start()

    # 2. Start NASA FIRMS periodic automatic synchronization scheduler (Stage 2C)
    try:
        firms_sync_scheduler.start()
    except Exception as e:
        logger.error(f"[FIRMS_SYNC] Failed to start automatic sync scheduler: {e}")


@app.on_event("shutdown")
def shutdown_services():
    """Cleanly terminate background scheduler on server shutdown."""
    try:
        firms_sync_scheduler.stop()
    except Exception as e:
        logger.warning(f"[FIRMS_SYNC] Error stopping scheduler during shutdown: {e}")


@app.get("/historical-baseline/summary")
def get_historical_baseline_summary(mode: Optional[str] = None):
    mgr = get_historical_baseline_manager(mode)
    _ensure_historical_baseline(mgr)
    return mgr.get_summary()


@app.get("/historical-baseline/daily")
def get_historical_baseline_daily(mode: Optional[str] = None):
    mgr = get_historical_baseline_manager(mode)
    _ensure_historical_baseline(mgr)
    return mgr.get_daily()


@app.get("/historical-baseline/grid")
def get_historical_baseline_grid(mode: Optional[str] = None):
    mgr = get_historical_baseline_manager(mode)
    _ensure_historical_baseline(mgr)
    return mgr.get_grid()


@app.get("/historical-baseline/status")
def get_historical_baseline_status(mode: Optional[str] = None):
    mgr = get_historical_baseline_manager(mode)
    if not mgr.is_loaded:
        map_key = get_firms_map_key()
        if map_key:
            try:
                mgr.load_or_fetch(map_key)
            except Exception as e:
                logger.warning(f"[HISTORICAL] Status check could not initialize baseline: {sanitize_log(str(e))}")
    return mgr.get_status()


# Pre-warm events intelligence layer from authoritative demo snapshot
try:
    _ensure_events_cache()
except Exception as e:
    logger.warning(f"[EVENTS] Pre-warm failed: {e}")


# =========================================================
# NASA FIRMS TEMPORAL HOTSPOT DATA PIPELINE ENDPOINTS
# =========================================================

@app.get("/api/v1/hotspots")
def get_temporal_hotspots(
    start_date: str,
    end_date: str,
    source: Optional[str] = None,
    satellite: Optional[str] = None,
    bbox: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
    sort: str = "ASC"
):
    """
    Retrieves authentic NASA FIRMS hotspot observations strictly within the inclusive date range [start_date, end_date].
    Supports optional filtering by source, satellite, bounding box (W,S,E,N), and pagination.
    """
    if not start_date or not end_date:
        raise HTTPException(
            status_code=400,
            detail="Both 'start_date' and 'end_date' query parameters are required (format: YYYY-MM-DD)."
        )

    try:
        d_start = datetime.datetime.strptime(str(start_date).strip(), "%Y-%m-%d").date()
        d_end = datetime.datetime.strptime(str(end_date).strip(), "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: must be YYYY-MM-DD ({e})"
        )

    if d_start > d_end:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({start_date}) must be prior or equal to end_date ({end_date})"
        )

    bbox_dict = None
    if bbox:
        try:
            parts = [float(p.strip()) for p in bbox.split(",")]
            if len(parts) == 4:
                bbox_dict = {"west": parts[0], "south": parts[1], "east": parts[2], "north": parts[3]}
            else:
                raise ValueError("bbox must contain 4 comma-separated coordinates: west,south,east,north")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bbox parameter '{bbox}': {e}"
            )

    safe_limit = max(1, min(int(limit), 10000))
    safe_offset = max(0, int(offset))

    total_matching, records = firms_db.query_hotspots(
        start_date=d_start.strftime("%Y-%m-%d"),
        end_date=d_end.strftime("%Y-%m-%d"),
        source=source,
        satellite=satellite,
        bbox=bbox_dict,
        limit=safe_limit,
        offset=safe_offset,
        sort_order=sort
    )

    return {
        "status": "success",
        "start_date": d_start.strftime("%Y-%m-%d"),
        "end_date": d_end.strftime("%Y-%m-%d"),
        "total": total_matching,
        "total_matching": total_matching,
        "limit": safe_limit,
        "offset": safe_offset,
        "count": len(records),
        "hotspots": records,
        "observations": records
    }


@app.get("/api/v1/hotspots/clusters")
def get_temporal_hotspot_clusters(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD) inclusive"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD) inclusive"),
    spatial_radius_km: float = Query(3.0, ge=0.1, le=50.0, description="Spatial proximity radius in km"),
    min_observations: int = Query(1, ge=1, le=1000, description="Minimum observations to form a cluster"),
    source: Optional[str] = Query(None, description="Filter by FIRMS source"),
    satellite: Optional[str] = Query(None, description="Filter by satellite"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'")
):
    """
    Stage 3 Spatio-Temporal Intelligence:
    Aggregates discrete FIRMS hotspot detections into spatial clusters,
    computes temporal persistence, and classifies FRP thermal intensity.
    """
    try:
        d_start = datetime.datetime.strptime(str(start_date).strip(), "%Y-%m-%d").date()
        d_end = datetime.datetime.strptime(str(end_date).strip(), "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format. Expected YYYY-MM-DD: {e}"
        )

    if d_start > d_end:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({start_date}) must be prior or equal to end_date ({end_date})"
        )

    bbox_dict = None
    if bbox:
        try:
            parts = [float(x.strip()) for x in bbox.split(",")]
            if len(parts) == 4:
                bbox_dict = {"west": parts[0], "south": parts[1], "east": parts[2], "north": parts[3]}
            else:
                raise ValueError("bbox must contain 4 comma-separated coordinates: west,south,east,north")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bbox parameter '{bbox}': {e}"
            )

    # Fetch observations across requested range (up to 10,000 observations)
    _, records = firms_db.query_hotspots(
        start_date=d_start.strftime("%Y-%m-%d"),
        end_date=d_end.strftime("%Y-%m-%d"),
        source=source,
        satellite=satellite,
        bbox=bbox_dict,
        limit=10000,
        offset=0,
        sort_order="ASC"
    )

    result = firms_clustering_service.cluster_hotspots(
        observations=records,
        start_date=d_start.strftime("%Y-%m-%d"),
        end_date=d_end.strftime("%Y-%m-%d"),
        spatial_radius_km=spatial_radius_km,
        min_observations=min_observations
    )

    return result



@app.get("/api/v1/hotspots/sync/status")
def get_temporal_hotspots_sync_status():
    """
    Returns the operational status of the automatic NASA FIRMS periodic synchronization service (Stage 2C).
    Includes last sync execution metrics, next scheduled execution time, and error states.
    """
    return firms_sync_scheduler.get_status()


@app.post("/api/v1/hotspots/sync")
def sync_temporal_hotspots(payload: Optional[dict] = None):
    """
    Triggers an on-demand synchronization of NASA FIRMS observations into SQLite.
    Accepts either 'days' (e.g. recent 3 days) or specific 'start_date' and 'end_date'.
    Protected by concurrency locks to prevent overlap with automatic sync.
    """
    payload = payload or {}
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    days = payload.get("days")
    sources = payload.get("sources")
    bbox = payload.get("bbox")

    key = get_firms_map_key()
    if not key:
        raise HTTPException(
            status_code=500,
            detail="NASA_FIRMS_MAP_KEY is missing or not configured on the server. Please configure NASA_FIRMS_MAP_KEY in backend/.env"
        )

    res = firms_sync_scheduler.trigger_sync(
        is_manual=True,
        days=int(days) if days else None,
        start_date=start_date,
        end_date=end_date,
        sources=sources,
        bbox=bbox
    )

    if res.get("status") == "busy":
        raise HTTPException(
            status_code=409,
            detail="A FIRMS synchronization job is already in progress. Please retry after completion."
        )

    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("error"))

    return res


@app.get("/api/v1/hotspots/stats")
def get_temporal_hotspots_stats():
    """Returns overview statistics of stored NASA FIRMS temporal observations in SQLite."""
    return {
        "status": "success",
        "database": firms_db.db_path,
        "stats": firms_db.get_stats()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
