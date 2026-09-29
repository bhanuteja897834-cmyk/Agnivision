"""
AGNIVISION-GIS: NASA FIRMS Temporal Hotspot Ingestion & Query Package
"""

from .client import (
    FIRMSClient,
    generate_date_chunks,
    DEFAULT_INDIA_BBOX,
    DEFAULT_NRT_SOURCES,
    EXTENSIBLE_NRT_SOURCES,
    HISTORICAL_SP_SOURCES
)
from .normalizer import normalize_firms_record, calculate_raw_hash
from .models import FIRMSDatabase, DEFAULT_DB_PATH
from .ingestion import FIRMSIngestionService
from .scheduler import FIRMSAutoSyncScheduler
from .clustering import FIRMSSpatioTemporalClusteringService, classify_frp_intensity, classify_operational_state

__all__ = [
    "FIRMSClient",
    "generate_date_chunks",
    "DEFAULT_INDIA_BBOX",
    "DEFAULT_NRT_SOURCES",
    "EXTENSIBLE_NRT_SOURCES",
    "HISTORICAL_SP_SOURCES",
    "normalize_firms_record",
    "calculate_raw_hash",
    "FIRMSDatabase",
    "DEFAULT_DB_PATH",
    "FIRMSIngestionService",
    "FIRMSAutoSyncScheduler",
    "FIRMSSpatioTemporalClusteringService",
    "classify_frp_intensity",
    "classify_operational_state"
]
