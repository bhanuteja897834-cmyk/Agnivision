const API_BASE = (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE) || "";

/**
 * Fetch NASA FIRMS hotspot observations for an inclusive date range.
 *
 * @param {Object} params
 * @param {string} params.startDate - Format: YYYY-MM-DD (required)
 * @param {string} params.endDate - Format: YYYY-MM-DD (required)
 * @param {string} [params.bbox] - Format: "min_lon,min_lat,max_lon,max_lat"
 * @param {string} [params.satellite] - Filter by satellite: e.g. "NOAA-20", "NOAA-21"
 * @param {string} [params.source] - Filter by source: e.g. "VIIRS_NOAA20_NRT"
 * @param {number} [params.limit=5000] - Result limit (max 10000)
 * @param {number} [params.offset=0] - Result offset
 * @param {string} [params.sort="ASC"] - Sort order: "ASC" or "DESC"
 * @param {AbortSignal} [params.signal] - Optional abort signal
 * @returns {Promise<{status: string, startDate: string, endDate: string, total: number, count: number, limit: number, offset: number, hotspots: Array}>}
 */
export async function fetchFIRMSHotspots({
  startDate,
  endDate,
  bbox,
  satellite,
  source,
  limit = 5000,
  offset = 0,
  sort = "ASC",
  signal
}) {
  if (!startDate || !endDate) {
    throw new Error("Both startDate and endDate are required (YYYY-MM-DD)");
  }

  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    limit: String(limit),
    offset: String(offset),
    sort
  });

  if (bbox) params.append("bbox", bbox);
  if (satellite) params.append("satellite", satellite);
  if (source) params.append("source", source);

  const url = `${API_BASE}/api/v1/hotspots?${params.toString()}`;

  const response = await fetch(url, { signal });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: Failed to fetch FIRMS hotspots`;
    try {
      const errJson = await response.json();
      if (errJson?.detail) {
        errorDetail =
          typeof errJson.detail === "string"
            ? errJson.detail
            : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore parsing error
    }
    throw new Error(errorDetail);
  }

  const data = await response.json();

  // Support both 'hotspots' and 'observations' keys, and 'total' / 'total_matching'
  const hotspotsList = Array.isArray(data.hotspots)
    ? data.hotspots
    : Array.isArray(data.observations)
    ? data.observations
    : [];

  const total =
    typeof data.total === "number"
      ? data.total
      : typeof data.total_matching === "number"
      ? data.total_matching
      : hotspotsList.length;

  return {
    status: data.status || "success",
    startDate: data.start_date || startDate,
    endDate: data.end_date || endDate,
    total,
    count: data.count || hotspotsList.length,
    limit: data.limit || limit,
    offset: data.offset || offset,
    hotspots: hotspotsList
  };
}

/**
 * Fetch NASA FIRMS SQLite overview statistics.
 */
export async function fetchFIRMSStats({ signal } = {}) {
  const url = `${API_BASE}/api/v1/hotspots/stats`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch FIRMS stats (${response.status})`);
  }
  return response.json();
}

/**
 * Fetch NASA FIRMS automatic synchronization status (Stage 2C).
 */
export async function fetchFIRMSSyncStatus({ signal } = {}) {
  const url = `${API_BASE}/api/v1/hotspots/sync/status`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch FIRMS sync status (${response.status})`);
  }
  return response.json();
}

/**
 * Trigger an on-demand manual FIRMS synchronization (Stage 2C).
 */
export async function triggerFIRMSSync(payload = {}, { signal } = {}) {
  const url = `${API_BASE}/api/v1/hotspots/sync`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal
  });
  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: Failed to trigger FIRMS sync`;
    try {
      const errJson = await response.json();
      if (errJson?.detail) {
        errorDetail = errJson.detail;
      }
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }
  return response.json();
}

/**
 * Fetch Spatio-Temporal clusters of FIRMS hotspots (Stage 3).
 *
 * @param {Object} params
 * @param {string} params.startDate - Format: YYYY-MM-DD (required)
 * @param {string} params.endDate - Format: YYYY-MM-DD (required)
 * @param {number} [params.spatialRadiusKm=3.0] - Proximity radius in km
 * @param {number} [params.minObservations=1] - Minimum observations
 * @param {string} [params.bbox] - Format: "west,south,east,north"
 * @param {string} [params.satellite] - Filter by satellite
 * @param {string} [params.source] - Filter by source
 * @param {AbortSignal} [params.signal] - Optional abort signal
 * @returns {Promise<{status: string, start_date: string, end_date: string, total_clusters: number, clusters: Array}>}
 */
export async function fetchFIRMSClusters({
  startDate,
  endDate,
  spatialRadiusKm = 3.0,
  minObservations = 1,
  bbox,
  satellite,
  source,
  signal
}) {
  if (!startDate || !endDate) {
    throw new Error("Both startDate and endDate are required (YYYY-MM-DD)");
  }

  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    spatial_radius_km: String(spatialRadiusKm),
    min_observations: String(minObservations)
  });

  if (bbox) params.append("bbox", bbox);
  if (satellite) params.append("satellite", satellite);
  if (source) params.append("source", source);

  const url = `${API_BASE}/api/v1/hotspots/clusters?${params.toString()}`;

  const response = await fetch(url, { signal });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: Failed to fetch FIRMS clusters`;
    try {
      const errJson = await response.json();
      if (errJson?.detail) {
        errorDetail =
          typeof errJson.detail === "string"
            ? errJson.detail
            : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore parsing error
    }
    throw new Error(errorDetail);
  }

  return response.json();
}
