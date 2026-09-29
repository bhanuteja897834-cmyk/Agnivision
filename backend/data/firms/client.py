"""
AGNIVISION-GIS: NASA FIRMS Area API Client
Handles authentic NASA FIRMS Area API queries with automatic date-range chunking (<= 5 days),
bounding box configuration, multiple satellite source querying, and strict MAP_KEY sanitization.
"""

import os
import io
import csv
import logging
import datetime
import requests
from typing import Dict, Any, List, Optional, Tuple, Union

logger = logging.getLogger("agnivision.firms.client")

# Official NASA FIRMS Area API base URL
FIRMS_AREA_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Canonical All-India geographic bounding box (West 67, South 7, East 98, North 38)
DEFAULT_INDIA_BBOX = {
    "west": 67.0,
    "south": 7.0,
    "east": 98.0,
    "north": 38.0
}

# Supported primary VIIRS sources
DEFAULT_NRT_SOURCES = [
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT"
]

EXTENSIBLE_NRT_SOURCES = [
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT"
]

HISTORICAL_SP_SOURCES = [
    "VIIRS_NOAA20_SP",
    "VIIRS_SNPP_SP"
]


def sanitize_message(text: str, secret: Optional[str] = None) -> str:
    """Sanitizes strings to ensure the FIRMS MAP_KEY is never exposed in logs or errors."""
    if not text:
        return ""
    clean = str(text)
    if secret and secret.strip():
        clean = clean.replace(secret.strip(), "[REDACTED_MAP_KEY]")
    env_key1 = os.environ.get("NASA_FIRMS_MAP_KEY", "").strip()
    env_key2 = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if env_key1:
        clean = clean.replace(env_key1, "[REDACTED_MAP_KEY]")
    if env_key2:
        clean = clean.replace(env_key2, "[REDACTED_MAP_KEY]")
    return clean


def format_bbox_str(bbox: Union[Dict[str, float], str]) -> str:
    """Formats bounding box dictionary or string into FIRMS 'W,S,E,N' format."""
    if isinstance(bbox, str):
        return bbox.strip()
    return f"{int(bbox['west'])},{int(bbox['south'])},{int(bbox['east'])},{int(bbox['north'])}"


def generate_date_chunks(
    start_date: Union[datetime.date, str],
    end_date: Union[datetime.date, str],
    max_chunk_days: int = 5
) -> List[Dict[str, Any]]:
    """
    Divides an arbitrary date range [start_date, end_date] into valid NASA FIRMS API chunks
    of at most max_chunk_days (NASA FIRMS Area API allows 1 through 5 days per call).
    """
    if isinstance(start_date, str):
        start_date = datetime.datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date.strip(), "%Y-%m-%d").date()

    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) must be prior to or equal to end_date ({end_date})")

    chunks = []
    curr = start_date
    while curr <= end_date:
        remaining_days = (end_date - curr).days + 1
        chunk_days = min(remaining_days, max_chunk_days)
        chunk_end = curr + datetime.timedelta(days=chunk_days - 1)
        chunks.append({
            "start_date": curr.strftime("%Y-%m-%d"),
            "end_date": chunk_end.strftime("%Y-%m-%d"),
            "day_range": chunk_days
        })
        curr = chunk_end + datetime.timedelta(days=1)

    return chunks


class FIRMSClient:
    """
    Client for NASA FIRMS Area API with date-range chunking,
    source management, bounding box validation, and rate-limit handling.
    """

    def __init__(self, map_key: Optional[str] = None):
        self.map_key = (
            map_key or
            os.environ.get("NASA_FIRMS_MAP_KEY") or
            os.environ.get("FIRMS_MAP_KEY") or
            ""
        ).strip()

    def get_validated_map_key(self) -> str:
        """Validates that a MAP_KEY is configured before attempting network operations."""
        if not self.map_key:
            raise ValueError(
                "FIRMS_MAP_KEY is missing or not configured on the server. "
                "Please configure NASA_FIRMS_MAP_KEY or FIRMS_MAP_KEY in backend/.env."
            )
        return self.map_key

    def fetch_chunk_csv(
        self,
        source: str,
        bbox: Union[Dict[str, float], str],
        day_range: int,
        start_date: str,
        timeout: int = 35
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        """
        Executes a single FIRMS Area API request for a chunk of <= 5 days.
        Returns:
            Tuple[List[Dict[str, str]], Optional[str]]: (parsed_rows, error_message)
        """
        key = self.get_validated_map_key()
        bbox_str = format_bbox_str(bbox)

        if not (1 <= day_range <= 5):
            raise ValueError(f"NASA FIRMS API day_range must be between 1 and 5 (got {day_range})")

        url = f"{FIRMS_AREA_API_BASE}/{key}/{source}/{bbox_str}/{day_range}/{start_date}"
        redacted_url = sanitize_message(url, key)
        logger.info(f"[FIRMS_CLIENT] Requesting chunk: {redacted_url}")

        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                text = response.text.strip()
                if not text or text.startswith("<!DOCTYPE") or text.startswith("<html"):
                    safe_body = sanitize_message(text[:150], key)
                    return [], f"Non-CSV response from NASA FIRMS: {safe_body}"

                csv_reader = csv.DictReader(io.StringIO(text))
                raw_rows = []
                for row in csv_reader:
                    if row:
                        cleaned = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                        raw_rows.append(cleaned)
                return raw_rows, None

            elif response.status_code == 400 and "invalid map_key" in response.text.lower():
                return [], "NASA FIRMS rejected the MAP_KEY as invalid. Please verify FIRMS_MAP_KEY."
            else:
                safe_body = sanitize_message(response.text[:200], key)
                return [], f"HTTP {response.status_code} from NASA FIRMS ({safe_body})"

        except requests.RequestException as e:
            safe_err = sanitize_message(str(e), key)
            logger.error(f"[FIRMS_CLIENT] Network error during request to {redacted_url}: {safe_err}")
            return [], f"Network error communicating with NASA FIRMS: {safe_err}"
