"""
AGNIVISION-GIS: NASA FIRMS Normalizer & Data Quality Validator
Validates observation values, standardizes temporal timestamps (acq_date, acq_time, acquisition_datetime),
standardizes satellite/instrument codes, and calculates deterministic SHA-256 deduplication hashes.
"""

import math
import hashlib
import logging
import datetime
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("agnivision.firms.normalizer")

# Canonical satellite name mapping
SATELLITE_NAME_MAP = {
    "N20": "NOAA-20",
    "NOAA20": "NOAA-20",
    "NOAA-20": "NOAA-20",
    "N21": "NOAA-21",
    "NOAA21": "NOAA-21",
    "NOAA-21": "NOAA-21",
    "NPP": "S-NPP",
    "SNPP": "S-NPP",
    "S-NPP": "S-NPP",
    "1": "S-NPP",
    "A": "Aqua",
    "T": "Terra"
}


def parse_float_safe(val: Any) -> Optional[float]:
    """Safely parses float, returning None for invalid or infinite values."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f if not math.isnan(f) and not math.isinf(f) else None
    except (ValueError, TypeError):
        return None


def normalize_acq_time(raw_time: Any) -> Optional[str]:
    """
    Standardizes FIRMS acquisition time into a 4-digit HHMM representation.
    E.g.: '718' -> '0718', '1425' -> '1425', 718 -> '0718'.
    """
    if raw_time is None or raw_time == "":
        return None
    time_str = str(raw_time).strip()
    if not time_str.isdigit():
        return None
    # FIRMS can omit leading zeros, so '718' represents '0718'
    padded = time_str.zfill(4)
    if len(padded) != 4:
        return None
    hour = int(padded[:2])
    minute = int(padded[2:])
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return padded
    return None


def calculate_raw_hash(
    source: str,
    satellite: str,
    latitude: float,
    longitude: float,
    acq_date: str,
    acq_time: str,
    daynight: str,
    scan: Optional[float],
    track: Optional[float]
) -> str:
    """
    Constructs a deterministic unique SHA-256 hash for a FIRMS observation.
    Uses canonical 5-decimal spatial precision (~1.1 meter) and observation attributes.
    """
    scan_val = f"{scan:.2f}" if scan is not None else "0.00"
    track_val = f"{track:.2f}" if track is not None else "0.00"
    key_str = (
        f"{source.strip().upper()}|"
        f"{satellite.strip().upper()}|"
        f"{latitude:.5f}|"
        f"{longitude:.5f}|"
        f"{acq_date.strip()}|"
        f"{acq_time.strip()}|"
        f"{daynight.strip().upper()}|"
        f"{scan_val}|"
        f"{track_val}"
    )
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def normalize_firms_record(
    raw_row: Dict[str, Any],
    source: str,
    source_request_date: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates and standardizes a single raw FIRMS row.
    Returns:
        Tuple[Optional[Dict[str, Any]], Optional[str]]: (normalized_record, rejection_reason)
    """
    # 1. Coordinates validation
    raw_lat = raw_row.get("latitude")
    raw_lon = raw_row.get("longitude")
    lat = parse_float_safe(raw_lat)
    lon = parse_float_safe(raw_lon)
    if lat is None or lon is None:
        return None, "invalid_coordinates"
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, "out_of_range_coordinates"

    # 2. Date validation (YYYY-MM-DD)
    raw_date = raw_row.get("acq_date")
    if not raw_date:
        return None, "missing_acq_date"
    try:
        parsed_date = datetime.datetime.strptime(str(raw_date).strip(), "%Y-%m-%d").date()
        acq_date = parsed_date.strftime("%Y-%m-%d")
    except ValueError:
        return None, "invalid_acq_date_format"

    # 3. Time validation (HHMM)
    raw_time = raw_row.get("acq_time")
    acq_time = normalize_acq_time(raw_time)
    if not acq_time:
        return None, "invalid_acq_time"

    # 4. Canonical ISO 8601 acquisition datetime (UTC)
    hour = int(acq_time[:2])
    minute = int(acq_time[2:])
    acq_dt = datetime.datetime(parsed_date.year, parsed_date.month, parsed_date.day, hour, minute, tzinfo=datetime.timezone.utc)
    acquisition_datetime = acq_dt.strftime("%Y-%m-%dT%H:%M:00Z")

    # 5. Satellite & Instrument
    raw_sat = str(raw_row.get("satellite") or "UNKNOWN").strip()
    satellite = SATELLITE_NAME_MAP.get(raw_sat.upper(), raw_sat)
    instrument = str(raw_row.get("instrument") or "VIIRS").strip()

    # 6. Thermal Channels & FRP
    # VIIRS uses bright_ti4 and bright_ti5, fallback to brightness / bright_t31
    bright_ti4 = parse_float_safe(raw_row.get("bright_ti4") or raw_row.get("brightness"))
    bright_ti5 = parse_float_safe(raw_row.get("bright_ti5") or raw_row.get("bright_t31"))
    if bright_ti4 is not None and bright_ti4 <= 0:
        return None, "invalid_brightness_value"

    raw_frp = raw_row.get("frp")
    frp = parse_float_safe(raw_frp)
    if frp is not None and frp < 0:
        return None, "negative_frp"

    scan = parse_float_safe(raw_row.get("scan"))
    track = parse_float_safe(raw_row.get("track"))

    # 7. Day / Night & Confidence
    daynight = str(raw_row.get("daynight") or "D").strip().upper()
    if daynight not in ("D", "N"):
        daynight = "D" if (6 <= hour < 18) else "N"

    raw_conf = raw_row.get("confidence")
    confidence = str(raw_conf).strip() if raw_conf is not None else None
    version = str(raw_row.get("version") or "").strip() or None

    # 8. Deterministic Hash
    raw_hash = calculate_raw_hash(
        source=source,
        satellite=satellite,
        latitude=lat,
        longitude=lon,
        acq_date=acq_date,
        acq_time=acq_time,
        daynight=daynight,
        scan=scan,
        track=track
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    normalized = {
        "raw_hash": raw_hash,
        "source": source,
        "satellite": satellite,
        "instrument": instrument,
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "bright_ti4": round(bright_ti4, 2) if bright_ti4 is not None else None,
        "bright_ti5": round(bright_ti5, 2) if bright_ti5 is not None else None,
        "scan": round(scan, 2) if scan is not None else None,
        "track": round(track, 2) if track is not None else None,
        "acq_date": acq_date,
        "acq_time": acq_time,
        "acquisition_datetime": acquisition_datetime,
        "confidence": confidence,
        "frp": round(frp, 2) if frp is not None else None,
        "daynight": daynight,
        "version": version,
        "ingested_at": now_iso,
        "source_request_date": source_request_date,
        "source_dataset": source
    }

    return normalized, None
