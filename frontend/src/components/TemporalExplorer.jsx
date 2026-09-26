import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  useMap
} from "react-leaflet";
import "./TemporalExplorer.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";

/* =========================================================
   UTILITIES
========================================================= */

function haversineKm(lat1, lon1, lat2, lon2) {
  if (lat1 == null || lon1 == null || lat2 == null || lon2 == null) return 0;
  const R = 6371.0;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function parseObsDateTime(obs) {
  if (!obs?.acq_date) return null;
  const rawTime = obs.acq_time != null ? String(obs.acq_time).trim().padStart(4, "0") : "0000";
  const hh = rawTime.slice(0, 2);
  const mm = rawTime.slice(2, 4);
  return new Date(`${obs.acq_date}T${hh}:${mm}:00Z`);
}

function formatAcqTime(timeStr) {
  if (timeStr == null || timeStr === "") return "00:00 UTC";
  const s = String(timeStr).trim().padStart(4, "0");
  return `${s.slice(0, 2)}:${s.slice(2, 4)} UTC`;
}

function formatShortDate(dateStr) {
  if (!dateStr) return "";
  const parts = String(dateStr).split("-");
  if (parts.length === 3) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = parseInt(parts[1], 10) - 1;
    const d = parseInt(parts[2], 10);
    if (m >= 0 && m < 12) return `${months[m]} ${d}`;
  }
  return dateStr;
}

function formatDateTimeLabel(obs) {
  if (!obs) return "Unavailable";
  return `${formatShortDate(obs.acq_date)} · ${formatAcqTime(obs.acq_time)}`;
}

function formatTimeGap(dt1, dt2) {
  if (!dt1 || !dt2) return "—";
  const t1 = dt1 instanceof Date ? dt1.getTime() : new Date(dt1).getTime();
  const t2 = dt2 instanceof Date ? dt2.getTime() : new Date(dt2).getTime();
  const diffMs = Math.abs(t2 - t1);
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
  return `${diffHours}h ${diffMins.toString().padStart(2, "0")}m`;
}

function riskColor(level) {
  switch (String(level || "").toLowerCase()) {
    case "critical":
      return "#dc2626";
    case "high":
      return "#ea580c";
    case "moderate":
      return "#d97706";
    default:
      return "#16a34a";
  }
}

/* =========================================================
   MAP VIEWPORT HELPER
========================================================= */

function MapAutoBounds({ observations, centroid, selectedObs }) {
  const map = useMap();

  useEffect(() => {
    if (selectedObs) {
      const lat = Number(selectedObs.latitude);
      const lon = Number(selectedObs.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        map.flyTo([lat, lon], Math.max(map.getZoom(), 13), { duration: 0.5 });
        return;
      }
    }

    if (!observations || observations.length === 0) {
      if (centroid && Number.isFinite(centroid.latitude) && Number.isFinite(centroid.longitude)) {
        map.setView([centroid.latitude, centroid.longitude], 12);
      }
      return;
    }

    if (observations.length === 1) {
      const o = observations[0];
      const lat = Number(o.latitude);
      const lon = Number(o.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        map.setView([lat, lon], 12);
      }
      return;
    }

    const validCoords = observations
      .map((o) => [Number(o.latitude), Number(o.longitude)])
      .filter(([lat, lon]) => Number.isFinite(lat) && Number.isFinite(lon));

    if (validCoords.length > 0) {
      map.fitBounds(validCoords, { padding: [35, 35], maxZoom: 14 });
    }
  }, [observations, centroid, selectedObs, map]);

  return null;
}

/* =========================================================
   MAIN TEMPORAL EXPLORER COMPONENT
========================================================= */

export default function TemporalExplorer({
  initialEventId = "EVT-000029",
  dataMode = "india",
  onSelectObservation,
  onOpenEvaluation
}) {
  const [eventsList, setEventsList] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      const urlId = sp.get("event_id") || sp.get("eventId");
      if (urlId) return urlId.trim().toUpperCase();
    } catch {
      // ignore
    }
    return (initialEventId || "EVT-000029").trim().toUpperCase();
  });
  const prevInitialIdRef = useRef(initialEventId);

  useEffect(() => {
    if (initialEventId && initialEventId !== prevInitialIdRef.current) {
      prevInitialIdRef.current = initialEventId;
      setSelectedEventId(initialEventId.trim().toUpperCase());
    }
  }, [initialEventId]);

  useEffect(() => {
    const handlePopState = () => {
      try {
        const sp = new URLSearchParams(window.location.search);
        const urlId = sp.get("event_id") || sp.get("eventId");
        if (urlId) setSelectedEventId(urlId.trim().toUpperCase());
      } catch {
        // ignore
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const [historyData, setHistoryData] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState(null);

  const [selectedObsIndex, setSelectedObsIndex] = useState(0);
  const [timeFilter, setTimeFilter] = useState("all"); // "all" | "24h" | "3d" | "7d" | "custom"
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const [mapBaseLayer, setMapBaseLayer] = useState("satellite"); // "standard" | "satellite"

  // 1. Fetch available events for the selector
  useEffect(() => {
    let active = true;
    async function fetchEvents() {
      try {
        setLoadingEvents(true);
        const res = await fetch(`${API_BASE}/events?mode=${dataMode}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (active && Array.isArray(data.events)) {
          setEventsList(data.events);
          setSelectedEventId((prev) => (prev ? prev : (data.events[0]?.event_id || "EVT-000029")));
        }
      } catch (err) {
        console.error("Failed to load events list:", err);
      } finally {
        if (active) setLoadingEvents(false);
      }
    }
    fetchEvents();
    return () => {
      active = false;
    };
  }, [dataMode]);

  // 2. Fetch event history for selectedEventId with AbortController and out-of-order protection
  useEffect(() => {
    if (!selectedEventId) return;
    let active = true;
    const controller = new AbortController();
    const cleanId = selectedEventId.trim().toUpperCase();

    async function fetchEventHistory() {
      try {
        setLoadingHistory(true);
        setHistoryError(null);
        const res = await fetch(`${API_BASE}/events/${cleanId}/history?mode=${dataMode}`, {
          signal: controller.signal
        });
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Persistent thermal event '${cleanId}' not found.`);
          throw new Error(`Failed to load event history (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active && data) {
          // Guard against out-of-order responses for mismatched events
          if (data.event_id && cleanId && data.event_id.toUpperCase() !== cleanId) {
            return;
          }
          setHistoryData(data);
          setSelectedObsIndex(0);
        }
      } catch (err) {
        if (err.name === "AbortError") return;
        if (active) setHistoryError(err.message || "Failed to load observation history");
      } finally {
        if (active) setLoadingHistory(false);
      }
    }

    fetchEventHistory();

    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedEventId, dataMode]);

  // Raw observations from API
  const rawObservations = useMemo(() => {
    if (!historyData) return [];
    if (Array.isArray(historyData.observations)) return historyData.observations;
    if (Array.isArray(historyData)) return historyData;
    return [];
  }, [historyData]);

  // 3. Apply Date Filtering (Requirement 11)
  const filteredObservations = useMemo(() => {
    if (rawObservations.length === 0) return [];
    if (timeFilter === "all") return rawObservations;

    const lastObs = rawObservations[rawObservations.length - 1];
    const lastDt = parseObsDateTime(lastObs) || new Date();

    if (timeFilter === "24h") {
      const cutoff = new Date(lastDt.getTime() - 24 * 60 * 60 * 1000);
      return rawObservations.filter((o) => {
        const dt = parseObsDateTime(o);
        return dt && dt >= cutoff;
      });
    }

    if (timeFilter === "3d") {
      const cutoff = new Date(lastDt.getTime() - 3 * 24 * 60 * 60 * 1000);
      return rawObservations.filter((o) => {
        const dt = parseObsDateTime(o);
        return dt && dt >= cutoff;
      });
    }

    if (timeFilter === "7d") {
      const cutoff = new Date(lastDt.getTime() - 7 * 24 * 60 * 60 * 1000);
      return rawObservations.filter((o) => {
        const dt = parseObsDateTime(o);
        return dt && dt >= cutoff;
      });
    }

    if (timeFilter === "custom") {
      return rawObservations.filter((o) => {
        const d = o?.acq_date;
        if (!d) return false;
        if (customFrom && d < customFrom) return false;
        if (customTo && d > customTo) return false;
        return true;
      });
    }

    return rawObservations;
  }, [rawObservations, timeFilter, customFrom, customTo]);

  // Clamp selectedObsIndex to bounds of filteredObservations
  useEffect(() => {
    if (selectedObsIndex >= filteredObservations.length) {
      setSelectedObsIndex(Math.max(0, filteredObservations.length - 1));
    }
  }, [filteredObservations.length, selectedObsIndex]);

  const activeObs = filteredObservations[selectedObsIndex] || null;

  // Consecutive Dynamics: Time Gap & Spatial Offset (Requirements 8 & 9)
  const consecutiveDynamics = useMemo(() => {
    if (!activeObs || filteredObservations.length === 0) return null;
    const idx = selectedObsIndex;
    const prevObs = idx > 0 ? filteredObservations[idx - 1] : null;

    if (!prevObs) {
      return {
        isFirst: true,
        prevObs: null,
        timeGapStr: "Initial Detection",
        distanceKm: null
      };
    }

    const dtPrev = parseObsDateTime(prevObs);
    const dtCurr = parseObsDateTime(activeObs);
    const gap = formatTimeGap(dtPrev, dtCurr);

    const dist = haversineKm(
      Number(prevObs.latitude),
      Number(prevObs.longitude),
      Number(activeObs.latitude),
      Number(activeObs.longitude)
    );

    return {
      isFirst: false,
      prevObs,
      timeGapStr: gap,
      distanceKm: dist != null ? dist.toFixed(2) : "0.00"
    };
  }, [activeObs, selectedObsIndex, filteredObservations]);

  // Overall dynamics averages
  const dynamicsSummary = useMemo(() => {
    if (filteredObservations.length < 2) return null;
    const gaps = [];
    const distances = [];

    for (let i = 1; i < filteredObservations.length; i++) {
      const prev = filteredObservations[i - 1];
      const curr = filteredObservations[i];
      const dtPrev = parseObsDateTime(prev);
      const dtCurr = parseObsDateTime(curr);
      if (dtPrev && dtCurr) {
        gaps.push(Math.abs(dtCurr.getTime() - dtPrev.getTime()) / (1000 * 60 * 60));
      }
      const dist = haversineKm(
        Number(prev.latitude),
        Number(prev.longitude),
        Number(curr.latitude),
        Number(curr.longitude)
      );
      if (Number.isFinite(dist)) distances.push(dist);
    }

    const avgGapHours = gaps.length ? (gaps.reduce((a, b) => a + b, 0) / gaps.length).toFixed(1) : null;
    const maxGapHours = gaps.length ? Math.max(...gaps).toFixed(1) : null;
    const avgDistKm = distances.length ? (distances.reduce((a, b) => a + b, 0) / distances.length).toFixed(2) : null;

    return { avgGapHours, maxGapHours, avgDistKm };
  }, [filteredObservations]);

  // Summary object from historyData
  const eventMeta = historyData || {};
  const centroid =
    eventMeta.spatial_summary?.centroid ||
    eventMeta.centroid ||
    { latitude: 23.5, longitude: 85.5 };
  const geoDomain = eventMeta.geographic_validation?.domain || eventMeta.geographic_domain || "LAND";
  const geoState = eventMeta.geographic_validation?.state || eventMeta.state || "India";

  return (
    <div className="temporal-explorer-container">
      {/* 1. TOP HEADER & EVENT SELECTOR */}
      <header className="temporal-header">
        <div className="temporal-header-left">
          <div className="temporal-badge">
            <span className="live-dot" /> SATELLITE TEMPORAL INTELLIGENCE
          </div>
          <h2>Temporal Explorer</h2>
          <p className="temporal-subtitle">
            Reconstruct and inspect chronological observation history for persistent thermal events
          </p>
        </div>

        <div className="temporal-header-controls">
          <label className="event-selector-label">
            <span>SELECT THERMAL EVENT:</span>
            <select
              value={selectedEventId}
              onChange={(e) => setSelectedEventId(e.target.value)}
              className="event-dropdown"
              disabled={loadingEvents}
            >
              {!eventsList.some((ev) => ev.event_id === selectedEventId) && (
                <option key={selectedEventId} value={selectedEventId}>
                  {selectedEventId} (Selected Event)
                </option>
              )}
              {eventsList.map((ev) => (
                <option key={ev.event_id} value={ev.event_id}>
                  {ev.event_id} ({ev.observation_count} obs · {ev.state || "Unassigned"} · {ev.risk_level})
                </option>
              ))}
            </select>
          </label>

          {onOpenEvaluation && (
            <button
              type="button"
              className="jump-eval-btn"
              onClick={() => onOpenEvaluation(selectedEventId)}
              title="Inspect multi-source evidence fusion profile and historical anomaly analysis for this event in Event Evaluation"
            >
              Evaluate Event & Evidence Profile ↗
            </button>
          )}
        </div>
      </header>

      {/* ERROR / LOADING ALERTS */}
      {loadingHistory && !historyData && (
        <div className="temporal-loading-bar">
          <div className="loading-spinner" />
          <span>Retrieving chronological FIRMS observation history for {selectedEventId}...</span>
        </div>
      )}

      {historyError && !historyData && (
        <div className="temporal-error-card">
          <span className="error-icon">⚠</span>
          <div>
            <strong>Observation History Query Error</strong>
            <p>{historyError}</p>
          </div>
        </div>
      )}

      {!historyData && !loadingHistory && !historyError && (
        <div className="temporal-empty-state" style={{ marginTop: "40px" }}>
          <span className="empty-icon">🛰</span>
          <strong>No Persistent Thermal Event Selected</strong>
          <p>Please select an event ID from the dropdown above to inspect its chronological observations.</p>
        </div>
      )}

      {historyData && (
        <>
          {loadingHistory && (
            <div className="temporal-loading-bar" style={{ marginBottom: "16px" }}>
              <div className="loading-spinner" />
              <span>Updating observation history for {selectedEventId}...</span>
            </div>
          )}
          {/* 2. EVENT SUMMARY CARDS (Requirement 7) */}
          <section className="event-summary-grid">
            <div className="summary-card">
              <span className="card-kicker">PERSISTENT EVENT ID</span>
              <strong className="card-value highlight-id">{eventMeta.event_id}</strong>
              <div className="card-footer">
                <span className="domain-pill">{geoDomain}</span>
                <span className="state-name">{geoState}</span>
              </div>
            </div>

            <div className="summary-card">
              <span className="card-kicker">OBSERVATION COUNT</span>
              <strong className="card-value">{eventMeta.observation_count}</strong>
              <div className="card-footer">
                <span>Discrete VIIRS Detections</span>
              </div>
            </div>

            <div className="summary-card">
              <span className="card-kicker">PERSISTENCE SPAN</span>
              <strong className="card-value">{eventMeta.persistence_days} days</strong>
              <div className="card-footer">
                <span>{formatShortDate(eventMeta.first_detected)} → {formatShortDate(eventMeta.last_detected)}</span>
              </div>
            </div>

            <div className="summary-card">
              <span className="card-kicker">SPATIAL CENTROID</span>
              <strong className="card-value coords-val">
                {Number(centroid.latitude).toFixed(4)}°, {Number(centroid.longitude).toFixed(4)}°
              </strong>
              <div className="card-footer">
                <span>Center of Gravity</span>
              </div>
            </div>

            <div className="summary-card">
              <span className="card-kicker">PROTOTYPE RISK HEURISTIC</span>
              <strong className="card-value" style={{ color: riskColor(eventMeta.risk_level) }}>
                {eventMeta.risk_level} ({eventMeta.risk_score})
              </strong>
              <div className="card-footer muted-disclaimer">
                <span>Rule-based score · Not ML</span>
              </div>
            </div>
          </section>

          {/* 3. DATE FILTERING CONTROLS (Requirement 11) */}
          <section className="temporal-filter-bar">
            <div className="filter-presets">
              <span className="filter-label">Filter Timeline:</span>
              <button
                type="button"
                className={`filter-btn ${timeFilter === "all" ? "active" : ""}`}
                onClick={() => setTimeFilter("all")}
              >
                All ({rawObservations.length})
              </button>
              <button
                type="button"
                className={`filter-btn ${timeFilter === "24h" ? "active" : ""}`}
                onClick={() => setTimeFilter("24h")}
              >
                Last 24 Hours
              </button>
              <button
                type="button"
                className={`filter-btn ${timeFilter === "3d" ? "active" : ""}`}
                onClick={() => setTimeFilter("3d")}
              >
                Last 3 Days
              </button>
              <button
                type="button"
                className={`filter-btn ${timeFilter === "7d" ? "active" : ""}`}
                onClick={() => setTimeFilter("7d")}
              >
                Last 7 Days
              </button>
              <button
                type="button"
                className={`filter-btn ${timeFilter === "custom" ? "active" : ""}`}
                onClick={() => setTimeFilter("custom")}
              >
                Custom Range
              </button>
            </div>

            {timeFilter === "custom" && (
              <div className="custom-filter-inputs">
                <label>
                  <span>From:</span>
                  <input
                    type="date"
                    value={customFrom}
                    onChange={(e) => setCustomFrom(e.target.value)}
                  />
                </label>
                <label>
                  <span>To:</span>
                  <input
                    type="date"
                    value={customTo}
                    onChange={(e) => setCustomTo(e.target.value)}
                  />
                </label>
                {(customFrom || customTo) && (
                  <button
                    type="button"
                    className="reset-filter-btn"
                    onClick={() => {
                      setCustomFrom("");
                      setCustomTo("");
                    }}
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
          </section>

          {/* EMPTY FILTER NOTICE */}
          {filteredObservations.length === 0 ? (
            <div className="temporal-empty-state">
              <span className="empty-icon">📅</span>
              <strong>No FIRMS observations in selected period.</strong>
              <p>No synthetic placeholder data is generated. Please adjust the timeline filter above.</p>
            </div>
          ) : (
            <>
              {/* 4. CHRONOLOGICAL TIMELINE STRIP (Requirement 1) */}
              <section className="timeline-section">
                <div className="section-title-row">
                  <div>
                    <h4>Observation Sequence Timeline</h4>
                    <span className="section-subtitle">
                      Chronological ordering of discrete NASA FIRMS VIIRS detections for {eventMeta.event_id}
                    </span>
                  </div>
                  <span className="obs-counter-pill">
                    Viewing {selectedObsIndex + 1} of {filteredObservations.length} observations
                  </span>
                </div>

                <div className="timeline-horizontal-scroll">
                  <div className="timeline-track">
                    {filteredObservations.map((obs, idx) => {
                      const isSelected = idx === selectedObsIndex;
                      const level = obs?.risk_level || "Low";
                      const color = riskColor(level);
                      const frp = obs?.frp != null && obs?.frp !== "" ? `${Number(obs.frp).toFixed(1)} MW` : "N/A";
                      const bright = obs?.bright_ti4 ? `${Math.round(obs.bright_ti4)} K` : "N/A";

                      return (
                        <div
                          key={`timeline-node-${obs.acq_date}-${obs.acq_time}-${idx}`}
                          className={`timeline-node ${isSelected ? "selected" : ""}`}
                          onClick={() => setSelectedObsIndex(idx)}
                        >
                          <div className="node-seq">#{idx + 1}</div>
                          <div
                            className="node-dot"
                            style={{
                              backgroundColor: color,
                              boxShadow: isSelected ? `0 0 0 4px rgba(255, 255, 255, 0.4), 0 0 12px ${color}` : "none"
                            }}
                          />
                          <div className="node-date">{formatShortDate(obs.acq_date)}</div>
                          <div className="node-time">{formatAcqTime(obs.acq_time)}</div>
                          <div className="node-metrics">
                            <span className="metric-pill bright-pill">{bright}</span>
                            <span className="metric-pill frp-pill">{frp}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>

              {/* 5. CONSECUTIVE OBSERVATION DYNAMICS (Requirements 8 & 9) */}
              <section className="dynamics-strip">
                <div className="dynamics-current-pair">
                  <div className="dynamics-kicker">CONSECUTIVE OBSERVATION INTERVAL ANALYSIS</div>
                  {consecutiveDynamics?.isFirst ? (
                    <div className="dynamics-body">
                      <span className="dynamics-icon">🚩</span>
                      <span>
                        <strong>Observation #1:</strong> Initial detection in the sequence at {formatDateTimeLabel(activeObs)}.
                      </span>
                    </div>
                  ) : (
                    <div className="dynamics-body">
                      <span className="dynamics-icon">⏱</span>
                      <div className="dynamics-text">
                        <span>
                          <strong>{formatDateTimeLabel(consecutiveDynamics?.prevObs)}</strong> → <strong>{formatDateTimeLabel(activeObs)}</strong>
                        </span>
                        <div className="dynamics-metrics">
                          <span className="dyn-badge gap-badge">Time Gap: {consecutiveDynamics?.timeGapStr}</span>
                          <span className="dyn-badge dist-badge">Footprint Offset: {consecutiveDynamics?.distanceKm} km</span>
                        </div>
                      </div>
                    </div>
                  )}
                  <p className="dynamics-disclaimer">
                    ℹ Descriptive satellite pass interval and sensor footprint offset only. Does not prove continuous fire activity or physical spread without auxiliary ground data.
                  </p>
                </div>

                {dynamicsSummary && (
                  <div className="dynamics-averages">
                    <div className="avg-box">
                      <span className="avg-label">AVG REVISIT GAP</span>
                      <strong className="avg-val">{dynamicsSummary.avgGapHours}h</strong>
                    </div>
                    <div className="avg-box">
                      <span className="avg-label">MAX REVISIT GAP</span>
                      <strong className="avg-val">{dynamicsSummary.maxGapHours}h</strong>
                    </div>
                    <div className="avg-box">
                      <span className="avg-label">AVG OFFSET</span>
                      <strong className="avg-val">{dynamicsSummary.avgDistKm} km</strong>
                    </div>
                  </div>
                )}
              </section>

              {/* 6. CHARTS & MAP DUAL VIEW */}
              <div className="workspace-main-split">
                {/* LEFT: TIME-SERIES CHARTS (Requirements 3, 4, 5) */}
                <div className="workspace-charts-col">
                  {/* BRIGHTNESS TREND */}
                  <div className="chart-panel">
                    <div className="chart-header">
                      <div>
                        <h5>Brightness Temperature Trend ($T_4$)</h5>
                        <span className="chart-meta">Discrete VIIRS 375m sensor brightness readings (Kelvin)</span>
                      </div>
                      <div className="chart-stat-tag">
                        Avg: {eventMeta.brightness_summary?.avg ?? "—"} K · Peak: {eventMeta.brightness_summary?.max ?? "—"} K
                      </div>
                    </div>
                    <BrightnessChart
                      observations={filteredObservations}
                      selectedIndex={selectedObsIndex}
                      onSelectIndex={setSelectedObsIndex}
                    />
                  </div>

                  {/* FRP TREND */}
                  <div className="chart-panel">
                    <div className="chart-header">
                      <div>
                        <h5>Fire Radiative Power (FRP) Trend</h5>
                        <span className="chart-meta">Instantaneous radiative energy output (Megawatts)</span>
                      </div>
                      <div className="chart-stat-tag">
                        Avg: {eventMeta.frp_summary?.avg ?? "—"} MW · Peak: {eventMeta.frp_summary?.max ?? "—"} MW
                      </div>
                    </div>
                    <FrpChart
                      observations={filteredObservations}
                      selectedIndex={selectedObsIndex}
                      onSelectIndex={setSelectedObsIndex}
                    />
                  </div>

                  {/* RISK SCORE TREND */}
                  <div className="chart-panel risk-chart-panel">
                    <div className="chart-header">
                      <div>
                        <h5>Rule-Based Risk Score Trend</h5>
                        <span className="chart-meta">Current prototype heuristic score (0–100 scale)</span>
                      </div>
                      <span className="risk-disclaimer-badge">Prototype Heuristic · Not ML</span>
                    </div>
                    <RiskChart
                      observations={filteredObservations}
                      selectedIndex={selectedObsIndex}
                      onSelectIndex={setSelectedObsIndex}
                    />
                  </div>
                </div>

                {/* RIGHT: MAP & OBSERVATION DETAILS (Requirements 10 & 2) */}
                <div className="workspace-map-col">
                  {/* MAP CONTAINER */}
                  <div className="explorer-map-card">
                    <div className="map-card-header">
                      <span>EVENT SPATIAL FOOTPRINT</span>
                      <div className="map-layer-toggles">
                        <button
                          type="button"
                          className={`layer-btn ${mapBaseLayer === "satellite" ? "active" : ""}`}
                          onClick={() => setMapBaseLayer("satellite")}
                        >
                          Satellite
                        </button>
                        <button
                          type="button"
                          className={`layer-btn ${mapBaseLayer === "standard" ? "active" : ""}`}
                          onClick={() => setMapBaseLayer("standard")}
                        >
                          Map
                        </button>
                      </div>
                    </div>

                    <div className="explorer-map-frame">
                      <MapContainer
                        center={[centroid.latitude || 23.5, centroid.longitude || 85.5]}
                        zoom={11}
                        className="explorer-leaflet-map"
                        attributionControl={false}
                      >
                        <MapAutoBounds
                          observations={filteredObservations}
                          centroid={centroid}
                          selectedObs={activeObs}
                        />

                        {mapBaseLayer === "satellite" ? (
                          <TileLayer
                            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                            maxZoom={18}
                          />
                        ) : (
                          <TileLayer
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                            maxZoom={18}
                          />
                        )}

                        {/* CENTROID MARKER */}
                        {centroid && Number.isFinite(centroid.latitude) && Number.isFinite(centroid.longitude) && (
                          <CircleMarker
                            center={[Number(centroid.latitude), Number(centroid.longitude)]}
                            radius={8}
                            pathOptions={{
                              color: "#38bdf8",
                              fillColor: "#0284c7",
                              fillOpacity: 0.9,
                              weight: 2
                            }}
                          >
                            <Popup>
                              <div className="map-pop">
                                <strong>📍 Event Centroid</strong>
                                <div>Lat: {Number(centroid.latitude).toFixed(5)}</div>
                                <div>Lon: {Number(centroid.longitude).toFixed(5)}</div>
                              </div>
                            </Popup>
                          </CircleMarker>
                        )}

                        {/* ALL EVENT OBSERVATIONS */}
                        {filteredObservations.map((obs, idx) => {
                          const lat = Number(obs.latitude);
                          const lon = Number(obs.longitude);
                          if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

                          const isSelected = idx === selectedObsIndex;
                          const color = riskColor(obs.risk_level);

                          return (
                            <CircleMarker
                              key={`map-obs-${obs.acq_date}-${obs.acq_time}-${idx}`}
                              center={[lat, lon]}
                              radius={isSelected ? 11 : 6}
                              pathOptions={{
                                color: isSelected ? "#ffffff" : color,
                                fillColor: color,
                                fillOpacity: isSelected ? 1.0 : 0.85,
                                weight: isSelected ? 3 : 1.5
                              }}
                              eventHandlers={{
                                click: () => setSelectedObsIndex(idx)
                              }}
                            >
                              <Popup>
                                <div className="map-pop">
                                  <strong>Observation #{idx + 1}</strong>
                                  <div>Acquired: {formatDateTimeLabel(obs)}</div>
                                  <div>Brightness: {obs.bright_ti4 ?? obs.brightness ?? "Unavailable"} K</div>
                                  <div>FRP: {obs.frp != null && obs.frp !== "" ? `${obs.frp} MW` : "Unavailable"}</div>
                                  <div>Coordinates: {lat.toFixed(5)}, {lon.toFixed(5)}</div>
                                </div>
                              </Popup>
                            </CircleMarker>
                          );
                        })}
                      </MapContainer>
                    </div>
                  </div>

                  {/* OBSERVATION DETAILS INSPECTOR (Requirement 2) */}
                  {activeObs && (
                    <div className="obs-details-card">
                      <div className="obs-details-header">
                        <h5>Observation Inspector · #{selectedObsIndex + 1}</h5>
                        <span className="obs-status-chip" style={{ color: riskColor(activeObs.risk_level) }}>
                          {activeObs.risk_level || "Low"} Risk
                        </span>
                      </div>

                      <div className="obs-details-table">
                        <div className="detail-row">
                          <span className="d-label">Observation Date</span>
                          <strong className="d-val">{activeObs.acq_date || "Unavailable"}</strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Acquisition Time</span>
                          <strong className="d-val">{formatAcqTime(activeObs.acq_time)}</strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Coordinates</span>
                          <strong className="d-val mono-val">
                            {Number(activeObs.latitude).toFixed(5)}°, {Number(activeObs.longitude).toFixed(5)}°
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Brightness ($T_4$ / 4µm)</span>
                          <strong className="d-val">
                            {activeObs.bright_ti4 != null ? `${activeObs.bright_ti4} K` : "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Brightness ($T_5$ / 11µm)</span>
                          <strong className="d-val">
                            {activeObs.bright_ti5 != null ? `${activeObs.bright_ti5} K` : "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Fire Radiative Power</span>
                          <strong className="d-val">
                            {activeObs.frp != null && activeObs.frp !== "" ? `${activeObs.frp} MW` : "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">FIRMS Confidence</span>
                          <strong className="d-val">
                            {activeObs.confidence_label || activeObs.confidence || "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Day / Night</span>
                          <strong className="d-val">
                            {activeObs.daynight === "D" ? "Daytime" : activeObs.daynight === "N" ? "Nighttime" : "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Prototype Risk Score</span>
                          <strong className="d-val" style={{ color: riskColor(activeObs.risk_level) }}>
                            {activeObs.risk_score != null ? activeObs.risk_score : "Unavailable"} ({activeObs.risk_level || "Low"})
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Geographic Domain</span>
                          <strong className="d-val">
                            {activeObs.geographic_validation?.domain || activeObs.geographic_domain || "LAND"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">State Attribution</span>
                          <strong className="d-val">
                            {activeObs.geographic_validation?.state || activeObs.state || "Unavailable"}
                          </strong>
                        </div>
                        <div className="detail-row">
                          <span className="d-label">Persistent Event ID</span>
                          <strong className="d-val highlight-id">{activeObs.event_id || eventMeta.event_id}</strong>
                        </div>
                      </div>

                      {onSelectObservation && (
                        <button
                          type="button"
                          className="inspect-incident-btn"
                          onClick={() => onSelectObservation(activeObs)}
                        >
                          View Facility Proximity in Geo Map →
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* 7. CHRONOLOGICAL OBSERVATION TABLE (Requirement 6) */}
              <section className="obs-table-section">
                <div className="section-title-row">
                  <div>
                    <h4>Chronological Observations Ledger</h4>
                    <span className="section-subtitle">
                      Complete tabular record of all {filteredObservations.length} discrete sensor detections
                    </span>
                  </div>
                </div>

                <div className="table-responsive-wrapper">
                  <table className="temporal-obs-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Acquisition Time (UTC)</th>
                        <th>Latitude</th>
                        <th>Longitude</th>
                        <th>Brightness ($T_4$)</th>
                        <th>FRP</th>
                        <th>Confidence</th>
                        <th>Risk Level</th>
                        <th>Domain</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredObservations.map((obs, idx) => {
                        const isSelected = idx === selectedObsIndex;
                        const frp = obs.frp != null && obs.frp !== "" ? `${Number(obs.frp).toFixed(2)} MW` : "—";
                        const bright = obs.bright_ti4 ? `${Number(obs.bright_ti4).toFixed(1)} K` : "—";
                        const level = obs.risk_level || "Low";

                        return (
                          <tr
                            key={`table-row-${idx}`}
                            className={isSelected ? "selected-row" : ""}
                            onClick={() => setSelectedObsIndex(idx)}
                          >
                            <td className="seq-cell">#{idx + 1}</td>
                            <td className="time-cell">{formatDateTimeLabel(obs)}</td>
                            <td className="mono-cell">{Number(obs.latitude).toFixed(4)}</td>
                            <td className="mono-cell">{Number(obs.longitude).toFixed(4)}</td>
                            <td className="num-cell">{bright}</td>
                            <td className="num-cell">{frp}</td>
                            <td>{obs.confidence_label || obs.confidence || "—"}</td>
                            <td>
                              <span className="risk-chip-small" style={{ backgroundColor: riskColor(level) }}>
                                {level}
                              </span>
                            </td>
                            <td>{obs.geographic_validation?.domain || "LAND"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {/* 8. DATA PROVENANCE NOTICE (Requirements 12 & 13) */}
          <footer className="temporal-provenance-footer">
            <div className="provenance-item">
              <span className="prov-kicker">SENSOR & DATA PROVENANCE</span>
              <p>NASA FIRMS · VIIRS NOAA-20 NRT (375m active thermal anomaly resolution) · EOSDIS MODAPS</p>
            </div>
            <div className="provenance-item">
              <span className="prov-kicker">SCIENTIFIC & OPERATIONAL INTEGRITY</span>
              <p>
                An Event is a rule-based spatiotemporal grouping (3.0 km × 36 hours) of satellite detections, not an automatic confirmation of active open flame. Missing values strictly display as Unavailable without synthetic imputation.
              </p>
            </div>
          </footer>
        </>
      )}
    </div>
  );
}

/* =========================================================
   PURE SVG TIME-SERIES CHARTS (Requirements 3, 4, 5)
========================================================= */

function BrightnessChart({ observations, selectedIndex, onSelectIndex }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(520);

  useEffect(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.width > 50) setWidth(Math.round(rect.width));

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect && entry.contentRect.width > 50) {
          setWidth(Math.round(entry.contentRect.width));
        }
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const height = 180;
  const padLeft = 52;
  const padRight = 20;
  const padTop = 18;
  const padBottom = 34;

  const plotW = Math.max(80, width - padLeft - padRight);
  const plotH = height - padTop - padBottom;

  const dataPoints = useMemo(() => {
    return observations
      .map((o, idx) => {
        const b = o.bright_ti4 != null ? Number(o.bright_ti4) : o.brightness != null ? Number(o.brightness) : null;
        return { idx, val: b, obs: o };
      })
      .filter((d) => d.val != null && Number.isFinite(d.val));
  }, [observations]);

  if (dataPoints.length === 0) {
    return (
      <div className="chart-empty" style={{ minHeight: "180px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        No valid brightness values recorded.
      </div>
    );
  }

  const values = dataPoints.map((d) => d.val);
  const minV = Math.floor(Math.min(...values) - 5);
  const maxV = Math.ceil(Math.max(...values) + 5);
  const range = maxV - minV || 1;

  const avgVal = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1);
  const avgY = padTop + plotH - ((Number(avgVal) - minV) / range) * plotH;

  const points = dataPoints.map((d, i) => {
    const x = dataPoints.length === 1 ? padLeft + plotW / 2 : padLeft + (i / (dataPoints.length - 1)) * plotW;
    const y = padTop + plotH - ((d.val - minV) / range) * plotH;
    return { ...d, x, y };
  });

  const pathD = points.length > 1
    ? points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ")
    : "";

  return (
    <div className="svg-chart-wrapper" ref={containerRef} style={{ minHeight: "180px" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        className="time-series-svg"
        style={{ overflow: "hidden" }}
      >
        <defs>
          <linearGradient id="brightGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Y-AXIS TICKS */}
        {[minV, Math.round(minV + range * 0.5), maxV].map((tick) => {
          const y = padTop + plotH - ((tick - minV) / range) * plotH;
          return (
            <g key={`bright-tick-${tick}`}>
              <line x1={padLeft} y1={y} x2={padLeft + plotW} y2={y} stroke="#334155" strokeDasharray="3 3" />
              <text x={padLeft - 8} y={y + 3.5} textAnchor="end" fill="#94a3b8" fontSize="10" fontFamily="monospace">
                {tick}K
              </text>
            </g>
          );
        })}

        {/* AVERAGE REFERENCE LINE */}
        {avgY >= padTop && avgY <= padTop + plotH && (
          <line
            x1={padLeft}
            y1={avgY}
            x2={padLeft + plotW}
            y2={avgY}
            stroke="#eab308"
            strokeDasharray="4 4"
            strokeWidth="1.2"
          />
        )}

        {/* X-AXIS BASELINE */}
        <line x1={padLeft} y1={padTop + plotH} x2={padLeft + plotW} y2={padTop + plotH} stroke="#334155" strokeWidth="1" />

        {/* CONNECTING LINE */}
        {pathD && <path d={pathD} fill="none" stroke="#f59e0b" strokeWidth="2" />}

        {/* OBSERVATION POINTS */}
        {points.map((p) => {
          const isSelected = p.idx === selectedIndex;
          return (
            <g
              key={`bright-pt-${p.idx}`}
              className="chart-interactive-point"
              onClick={() => onSelectIndex(p.idx)}
              style={{ cursor: "pointer" }}
            >
              {isSelected && (
                <circle cx={p.x} cy={p.y} r="9" fill="rgba(245, 158, 11, 0.3)" stroke="#f59e0b" strokeWidth="1.5" />
              )}
              <circle
                cx={p.x}
                cy={p.y}
                r={isSelected ? 5 : 3.5}
                fill={isSelected ? "#ffffff" : "#f59e0b"}
                stroke="#d97706"
                strokeWidth="1.5"
              />
              <title>{`#${p.idx + 1} · ${formatDateTimeLabel(p.obs)}: ${p.val} K`}</title>
            </g>
          );
        })}

        {/* X-AXIS LABELS */}
        {points.length === 1 ? (
          <text x={padLeft + plotW / 2} y={padTop + plotH + 20} textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="monospace">
            {formatDateTimeLabel(points[0].obs)}
          </text>
        ) : (
          <>
            <text x={padLeft} y={padTop + plotH + 20} textAnchor="start" fill="#94a3b8" fontSize="9.5" fontFamily="monospace">
              {formatDateTimeLabel(points[0].obs)}
            </text>
            {points.length >= 6 && (
              <text x={padLeft + plotW / 2} y={padTop + plotH + 20} textAnchor="middle" fill="#64748b" fontSize="9.5" fontFamily="monospace">
                {formatDateTimeLabel(points[Math.floor(points.length / 2)].obs)}
              </text>
            )}
            <text x={padLeft + plotW} y={padTop + plotH + 20} textAnchor="end" fill="#94a3b8" fontSize="9.5" fontFamily="monospace">
              {formatDateTimeLabel(points[points.length - 1].obs)}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

function FrpChart({ observations, selectedIndex, onSelectIndex }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(520);

  useEffect(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.width > 50) setWidth(Math.round(rect.width));

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect && entry.contentRect.width > 50) {
          setWidth(Math.round(entry.contentRect.width));
        }
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const height = 180;
  const padLeft = 52;
  const padRight = 20;
  const padTop = 18;
  const padBottom = 34;

  const plotW = Math.max(80, width - padLeft - padRight);
  const plotH = height - padTop - padBottom;

  const validObservations = useMemo(() => {
    return observations.filter((o) => o.frp != null && o.frp !== "" && Number.isFinite(Number(o.frp)));
  }, [observations]);

  if (validObservations.length === 0) {
    return (
      <div className="chart-empty" style={{ minHeight: "180px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "6px" }}>
        <span style={{ fontSize: "20px" }}>⚡</span>
        <strong style={{ color: "#94a3b8", fontSize: "12px" }}>No FRP Measurements Reported</strong>
        <span style={{ color: "#64748b", fontSize: "11px" }}>VIIRS sensor did not report instantaneous radiative power for these observations.</span>
      </div>
    );
  }

  const values = validObservations.map((o) => Number(o.frp));
  const minV = 0;
  const maxV = Math.max(1, Math.ceil(Math.max(...values) * 1.15));
  const range = maxV - minV || 1;

  const avgVal = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(2);
  const avgY = padTop + plotH - ((Number(avgVal) - minV) / range) * plotH;

  // Build points preserving observation sequence indices
  const count = observations.length;
  const points = observations.map((o, idx) => {
    const hasFrp = o.frp != null && o.frp !== "" && Number.isFinite(Number(o.frp));
    const frpVal = hasFrp ? Number(o.frp) : null;
    const x = count === 1 ? padLeft + plotW / 2 : padLeft + (idx / Math.max(1, count - 1)) * plotW;
    const y = hasFrp ? padTop + plotH - ((frpVal - minV) / range) * plotH : padTop + plotH - 4;
    return { idx, val: frpVal, hasFrp, obs: o, x, y };
  });

  // Build segments for consecutive valid points (never interpolate missing FRP)
  const segments = [];
  let cur = [];
  points.forEach((p) => {
    if (p.hasFrp) {
      cur.push(p);
    } else {
      if (cur.length > 1) segments.push(cur);
      cur = [];
    }
  });
  if (cur.length > 1) segments.push(cur);

  return (
    <div className="svg-chart-wrapper" ref={containerRef} style={{ minHeight: "180px" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        className="time-series-svg"
        style={{ overflow: "hidden" }}
      >
        {/* Y-AXIS TICKS */}
        {[0, Math.round(maxV * 0.5), maxV].map((tick) => {
          const y = padTop + plotH - ((tick - minV) / range) * plotH;
          return (
            <g key={`frp-tick-${tick}`}>
              <line x1={padLeft} y1={y} x2={padLeft + plotW} y2={y} stroke="#334155" strokeDasharray="3 3" />
              <text x={padLeft - 8} y={y + 3.5} textAnchor="end" fill="#94a3b8" fontSize="10" fontFamily="monospace">
                {tick} MW
              </text>
            </g>
          );
        })}

        {/* AVERAGE REFERENCE LINE */}
        {avgY >= padTop && avgY <= padTop + plotH && (
          <line
            x1={padLeft}
            y1={avgY}
            x2={padLeft + plotW}
            y2={avgY}
            stroke="#ef4444"
            strokeDasharray="4 4"
            strokeWidth="1.2"
          />
        )}

        {/* X-AXIS BASELINE */}
        <line x1={padLeft} y1={padTop + plotH} x2={padLeft + plotW} y2={padTop + plotH} stroke="#334155" strokeWidth="1" />

        {/* CONNECTING SEGMENTS (ONLY CONTIGUOUS REPORTED FRP) */}
        {segments.map((seg, sIdx) => {
          const d = seg.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
          return <path key={`frp-seg-${sIdx}`} d={d} fill="none" stroke="#ef4444" strokeWidth="2" />;
        })}

        {/* OBSERVATION POINTS */}
        {points.map((p) => {
          const isSelected = p.idx === selectedIndex;
          if (!p.hasFrp) {
            return (
              <g
                key={`frp-pt-${p.idx}`}
                className="chart-interactive-point"
                onClick={() => onSelectIndex(p.idx)}
                style={{ cursor: "pointer" }}
              >
                <circle cx={p.x} cy={p.y} r="3" fill="none" stroke="#64748b" strokeDasharray="2 2" strokeWidth="1.2" />
                <title>{`#${p.idx + 1} · ${formatDateTimeLabel(p.obs)}: FRP unrecorded`}</title>
              </g>
            );
          }

          return (
            <g
              key={`frp-pt-${p.idx}`}
              className="chart-interactive-point"
              onClick={() => onSelectIndex(p.idx)}
              style={{ cursor: "pointer" }}
            >
              {isSelected && (
                <circle cx={p.x} cy={p.y} r="9" fill="rgba(239, 68, 68, 0.3)" stroke="#ef4444" strokeWidth="1.5" />
              )}
              <circle
                cx={p.x}
                cy={p.y}
                r={isSelected ? 5 : 3.5}
                fill={isSelected ? "#ffffff" : "#ef4444"}
                stroke="#b91c1c"
                strokeWidth="1.5"
              />
              <title>{`#${p.idx + 1} · ${formatDateTimeLabel(p.obs)}: ${p.val} MW`}</title>
            </g>
          );
        })}

        {/* X-AXIS LABELS */}
        {points.length === 1 ? (
          <text x={padLeft + plotW / 2} y={padTop + plotH + 20} textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="monospace">
            {formatDateTimeLabel(points[0].obs)}
          </text>
        ) : (
          <>
            <text x={padLeft} y={padTop + plotH + 20} textAnchor="start" fill="#94a3b8" fontSize="9.5" fontFamily="monospace">
              {formatDateTimeLabel(points[0].obs)}
            </text>
            {points.length >= 6 && (
              <text x={padLeft + plotW / 2} y={padTop + plotH + 20} textAnchor="middle" fill="#64748b" fontSize="9.5" fontFamily="monospace">
                {formatDateTimeLabel(points[Math.floor(points.length / 2)].obs)}
              </text>
            )}
            <text x={padLeft + plotW} y={padTop + plotH + 20} textAnchor="end" fill="#94a3b8" fontSize="9.5" fontFamily="monospace">
              {formatDateTimeLabel(points[points.length - 1].obs)}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

function RiskChart({ observations, selectedIndex, onSelectIndex }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(520);

  useEffect(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    if (rect.width > 50) setWidth(Math.round(rect.width));

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect && entry.contentRect.width > 50) {
          setWidth(Math.round(entry.contentRect.width));
        }
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const height = 120;
  const padLeft = 52;
  const padRight = 20;
  const padTop = 14;
  const padBottom = 26;

  const plotW = Math.max(80, width - padLeft - padRight);
  const plotH = height - padTop - padBottom;

  const dataPoints = observations.map((o, idx) => {
    const score = o.risk_score != null ? Number(o.risk_score) : 20;
    return { idx, score, obs: o, level: o.risk_level || "Low" };
  });

  if (dataPoints.length === 0) {
    return (
      <div className="chart-empty" style={{ minHeight: "120px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        No risk score data recorded.
      </div>
    );
  }

  const count = dataPoints.length;
  const slotW = plotW / Math.max(1, count);
  const barW = Math.max(2, Math.min(22, slotW * 0.75));

  return (
    <div className="svg-chart-wrapper" ref={containerRef} style={{ minHeight: "120px" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        className="risk-series-svg"
        style={{ overflow: "hidden" }}
      >
        {/* Y-AXIS LABELS & THRESHOLD LINES */}
        {[
          { t: 80, label: "80 Crit", color: "#dc2626" },
          { t: 60, label: "60 High", color: "#ea580c" },
          { t: 30, label: "30 Mod", color: "#d97706" }
        ].map(({ t, label, color }) => {
          const y = padTop + plotH - (t / 100) * plotH;
          return (
            <g key={`risk-thresh-${t}`}>
              <line x1={padLeft} y1={y} x2={padLeft + plotW} y2={y} stroke="#334155" strokeDasharray="2 2" />
              <text x={padLeft - 6} y={y + 3.5} textAnchor="end" fill={color} fontSize="9" fontFamily="monospace">
                {label}
              </text>
            </g>
          );
        })}

        {/* 0 BASELINE */}
        <line x1={padLeft} y1={padTop + plotH} x2={padLeft + plotW} y2={padTop + plotH} stroke="#334155" strokeWidth="1" />
        <text x={padLeft - 6} y={padTop + plotH + 3} textAnchor="end" fill="#64748b" fontSize="9" fontFamily="monospace">
          0
        </text>

        {/* RISK BARS */}
        {dataPoints.map((d, i) => {
          const cx = padLeft + (i + 0.5) * slotW;
          const x = Math.min(padLeft + plotW - barW, Math.max(padLeft, cx - barW / 2));
          const h = Math.max(3, (d.score / 100) * plotH);
          const y = padTop + plotH - h;
          const isSelected = d.idx === selectedIndex;
          const color = riskColor(d.level);

          return (
            <g
              key={`risk-bar-${i}`}
              onClick={() => onSelectIndex(d.idx)}
              style={{ cursor: "pointer" }}
            >
              <rect
                x={x}
                y={y}
                width={barW}
                height={h}
                fill={color}
                stroke={isSelected ? "#ffffff" : "none"}
                strokeWidth={isSelected ? 1.5 : 0}
                rx={Math.min(1.5, barW / 2)}
              />
              <title>{`#${i + 1} · ${formatDateTimeLabel(d.obs)}: Risk ${d.score} (${d.level})`}</title>
            </g>
          );
        })}

        {/* X-AXIS TIMELINE LABELS */}
        {count === 1 ? (
          <text x={padLeft + plotW / 2} y={padTop + plotH + 16} textAnchor="middle" fill="#94a3b8" fontSize="9.5" fontFamily="monospace">
            {formatDateTimeLabel(dataPoints[0].obs)}
          </text>
        ) : (
          <>
            <text x={padLeft} y={padTop + plotH + 16} textAnchor="start" fill="#94a3b8" fontSize="9" fontFamily="monospace">
              {formatDateTimeLabel(dataPoints[0].obs)}
            </text>
            {count >= 8 && (
              <text x={padLeft + plotW / 2} y={padTop + plotH + 16} textAnchor="middle" fill="#64748b" fontSize="9" fontFamily="monospace">
                {formatDateTimeLabel(dataPoints[Math.floor(count / 2)].obs)}
              </text>
            )}
            <text x={padLeft + plotW} y={padTop + plotH + 16} textAnchor="end" fill="#94a3b8" fontSize="9" fontFamily="monospace">
              {formatDateTimeLabel(dataPoints[count - 1].obs)}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

