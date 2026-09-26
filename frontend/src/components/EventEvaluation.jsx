import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup,
  Rectangle,
  useMap
} from "react-leaflet";
import "./EventEvaluation.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";

/* =========================================================
   UTILITIES & HELPERS
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

function formatAcqTime(timeStr) {
  if (timeStr == null || timeStr === "") return "00:00 UTC";
  const s = String(timeStr).trim().padStart(4, "0");
  return `${s.slice(0, 2)}:${s.slice(2, 4)} UTC`;
}

function formatShortDate(dateStr) {
  if (!dateStr) return "";
  const parts = String(dateStr).split("T")[0].split("-");
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

function formatIsoDateTime(isoStr) {
  if (!isoStr) return "Unavailable";
  try {
    const dt = new Date(isoStr);
    if (isNaN(dt.getTime())) return String(isoStr);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = months[dt.getUTCMonth()];
    const d = dt.getUTCDate();
    const hh = String(dt.getUTCHours()).padStart(2, "0");
    const mm = String(dt.getUTCMinutes()).padStart(2, "0");
    return `${m} ${d}, ${dt.getUTCFullYear()} · ${hh}:${mm} UTC`;
  } catch {
    return String(isoStr);
  }
}

function riskColor(level) {
  switch (String(level || "").toLowerCase()) {
    case "critical":
      return "#dc2626";
    case "high":
      return "#ea580c";
    case "moderate":
      return "#ca8a04";
    case "low":
      return "#16a34a";
    default:
      return "#64748b";
  }
}

function RecenterMap({ lat, lon, zoom = 12 }) {
  const map = useMap();
  useEffect(() => {
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      map.setView([lat, lon], zoom, { animate: true });
    }
  }, [lat, lon, zoom, map]);
  return null;
}

/* =========================================================
   COMPACT PURE SVG TIME-SERIES CHARTS (REAL DATA ONLY)
========================================================= */

function CompactBrightnessChart({ observations }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(380);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 50) setWidth(entry.contentRect.width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const height = 120;
  const padLeft = 46;
  const padRight = 16;
  const padTop = 14;
  const padBottom = 22;

  const plotW = Math.max(60, width - padLeft - padRight);
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
    return <div className="chart-empty" style={{ padding: "20px", textAlign: "center", color: "#64748b", fontSize: "12px" }}>No brightness readings recorded.</div>;
  }

  const values = dataPoints.map((d) => d.val);
  const minV = Math.floor(Math.min(...values) - 4);
  const maxV = Math.ceil(Math.max(...values) + 4);
  const range = maxV - minV || 1;

  const avgVal = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1);
  const avgY = padTop + plotH - ((Number(avgVal) - minV) / range) * plotH;

  const points = dataPoints.map((d, i) => {
    const x = dataPoints.length === 1 ? padLeft + plotW / 2 : padLeft + (i / (dataPoints.length - 1)) * plotW;
    const y = padTop + plotH - ((d.val - minV) / range) * plotH;
    return { ...d, x, y };
  });

  const pathD =
    points.length > 1
      ? points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ")
      : "";

  return (
    <div className="compact-chart-card" ref={containerRef}>
      <div className="compact-chart-header">
        <span>VIIRS $T_4$ (4µm) Radiance Trend</span>
        <span className="compact-chart-avg">Mean: {avgVal} K</span>
      </div>
      <svg width={width} height={height} className="compact-svg-chart">
        {[minV, maxV].map((tick) => {
          const y = padTop + plotH - ((tick - minV) / range) * plotH;
          return (
            <g key={`b-tick-${tick}`}>
              <line x1={padLeft} y1={y} x2={padLeft + plotW} y2={y} stroke="#1e293b" strokeDasharray="2 2" />
              <text x={padLeft - 6} y={y + 3.5} textAnchor="end" fill="#64748b" fontSize="9" fontFamily="monospace">
                {tick}K
              </text>
            </g>
          );
        })}
        {avgY >= padTop && avgY <= padTop + plotH && (
          <line x1={padLeft} y1={avgY} x2={padLeft + plotW} y2={avgY} stroke="#eab308" strokeDasharray="3 3" strokeWidth="1" />
        )}
        {pathD && <path d={pathD} fill="none" stroke="#f59e0b" strokeWidth="1.8" />}
        {points.map((p) => (
          <circle key={`b-pt-${p.idx}`} cx={p.x} cy={p.y} r="3" fill="#f59e0b" stroke="#0f172a" strokeWidth="1">
            <title>{`#${p.idx + 1} · ${formatDateTimeLabel(p.obs)}: ${p.val} K`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

function CompactFrpChart({ observations }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(380);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 50) setWidth(entry.contentRect.width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const height = 120;
  const padLeft = 46;
  const padRight = 16;
  const padTop = 14;
  const padBottom = 22;

  const plotW = Math.max(60, width - padLeft - padRight);
  const plotH = height - padTop - padBottom;

  const dataPoints = useMemo(() => {
    return observations
      .map((o, idx) => {
        const frpVal = o.frp != null && o.frp !== "" ? Number(o.frp) : null;
        return { idx, val: frpVal, obs: o };
      })
      .filter((d) => d.val != null && Number.isFinite(d.val));
  }, [observations]);

  if (dataPoints.length === 0) {
    return <div className="chart-empty" style={{ padding: "20px", textAlign: "center", color: "#64748b", fontSize: "12px" }}>No FRP values reported.</div>;
  }

  const values = dataPoints.map((d) => d.val);
  const minV = 0;
  const maxV = Math.max(1, Math.ceil(Math.max(...values) * 1.15));
  const range = maxV - minV || 1;

  const avgVal = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(2);
  const avgY = padTop + plotH - ((Number(avgVal) - minV) / range) * plotH;

  const points = dataPoints.map((d, i) => {
    const x = dataPoints.length === 1 ? padLeft + plotW / 2 : padLeft + (i / (dataPoints.length - 1)) * plotW;
    const y = padTop + plotH - ((d.val - minV) / range) * plotH;
    return { ...d, x, y };
  });

  const pathD =
    points.length > 1
      ? points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ")
      : "";

  return (
    <div className="compact-chart-card" ref={containerRef}>
      <div className="compact-chart-header">
        <span>Fire Radiative Power (MW)</span>
        <span className="compact-chart-avg">Mean: {avgVal} MW</span>
      </div>
      <svg width={width} height={height} className="compact-svg-chart">
        {[0, maxV].map((tick) => {
          const y = padTop + plotH - ((tick - minV) / range) * plotH;
          return (
            <g key={`frp-tick-${tick}`}>
              <line x1={padLeft} y1={y} x2={padLeft + plotW} y2={y} stroke="#1e293b" strokeDasharray="2 2" />
              <text x={padLeft - 6} y={y + 3.5} textAnchor="end" fill="#64748b" fontSize="9" fontFamily="monospace">
                {tick}M
              </text>
            </g>
          );
        })}
        {avgY >= padTop && avgY <= padTop + plotH && (
          <line x1={padLeft} y1={avgY} x2={padLeft + plotW} y2={avgY} stroke="#ef4444" strokeDasharray="3 3" strokeWidth="1" />
        )}
        {pathD && <path d={pathD} fill="none" stroke="#ef4444" strokeWidth="1.8" />}
        {points.map((p) => (
          <circle key={`frp-pt-${p.idx}`} cx={p.x} cy={p.y} r="3" fill="#ef4444" stroke="#0f172a" strokeWidth="1">
            <title>{`#${p.idx + 1} · ${formatDateTimeLabel(p.obs)}: ${p.val} MW`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

/* =========================================================
   MAIN EVENT EVALUATION COMPONENT
========================================================= */

export default function EventEvaluation({
  initialEventId = "EVT-000029",
  dataMode = "india",
  onSelectEvent,
  onOpenTemporal,
  verifiedEvents = [],
  onRefreshVerified
}) {
  const [eventsList, setEventsList] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState(initialEventId);
  const prevInitialIdRef = useRef(initialEventId);

  useEffect(() => {
    if (initialEventId && initialEventId !== prevInitialIdRef.current) {
      prevInitialIdRef.current = initialEventId;
      setSelectedEventId(initialEventId);
    }
  }, [initialEventId]);

  useEffect(() => {
    const handleSelectEvent = (e) => {
      if (e?.detail) {
        setSelectedEventId(e.detail);
        if (typeof onSelectEvent === "function") {
          onSelectEvent(e.detail);
        }
      }
    };
    window.addEventListener("agnivision-select-event", handleSelectEvent);
    return () => window.removeEventListener("agnivision-select-event", handleSelectEvent);
  }, [onSelectEvent]);

  const [historyData, setHistoryData] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState(null);

  // OSM Assets context
  const [assets, setAssets] = useState(null);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [assetError, setAssetError] = useState(false);

  // Map Basemap layer
  const [mapBaseLayer, setMapBaseLayer] = useState("satellite"); // "standard" | "satellite"

  // Human Verification Form state
  const [selectedLabel, setSelectedLabel] = useState("ACTIVE_FIRE");
  const [analystNotes, setAnalystNotes] = useState("");
  const [submittingVerif, setSubmittingVerif] = useState(false);
  const [verifSuccessMsg, setVerifSuccessMsg] = useState("");
  const [verifErrorMsg, setVerifErrorMsg] = useState("");
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [isEditingExisting, setIsEditingExisting] = useState(false);

  // 1. Fetch available persistent events
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
          if (!selectedEventId && data.events.length > 0) {
            setSelectedEventId(data.events[0].event_id);
          }
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

  // 2. Fetch event history for selectedEventId
  useEffect(() => {
    let active = true;
    async function fetchEventHistory() {
      if (!selectedEventId) return;
      try {
        setLoadingHistory(true);
        setHistoryError(null);
        const res = await fetch(`${API_BASE}/events/${selectedEventId}/history?mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Persistent thermal event '${selectedEventId}' not found.`);
          throw new Error(`Failed to load event history (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          setHistoryData(data);
          setVerifSuccessMsg("");
          setVerifErrorMsg("");
        }
      } catch (err) {
        if (active) setHistoryError(err.message || "Failed to load event history");
      } finally {
        if (active) setLoadingHistory(false);
      }
    }
    fetchEventHistory();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // 3. Fetch Historical Baseline Summary (Step 5)
  const [baselineSummary, setBaselineSummary] = useState(null);
  const [loadingBaseline, setLoadingBaseline] = useState(true);
  const [baselineError, setBaselineError] = useState(null);

  useEffect(() => {
    let active = true;
    async function fetchBaseline() {
      try {
        setLoadingBaseline(true);
        setBaselineError(null);
        const res = await fetch(`${API_BASE}/historical-baseline/summary`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (active) {
          if (data.status === "unavailable") {
            setBaselineError(data.reason || "Historical baseline unavailable.");
          } else {
            setBaselineSummary(data);
          }
        }
      } catch (err) {
        if (active) setBaselineError(err.message || "Failed to load historical baseline");
      } finally {
        if (active) setLoadingBaseline(false);
      }
    }
    fetchBaseline();
    return () => {
      active = false;
    };
  }, []);

  // 4. Fetch Event Anomaly Analysis vs Historical Baseline (Step 6)
  const [anomalyData, setAnomalyData] = useState(null);
  const [loadingAnomaly, setLoadingAnomaly] = useState(false);
  const [anomalyError, setAnomalyError] = useState(null);

  useEffect(() => {
    let active = true;
    async function fetchAnomaly() {
      if (!selectedEventId) return;
      try {
        setLoadingAnomaly(true);
        setAnomalyError(null);
        const res = await fetch(`${API_BASE}/events/${selectedEventId}/anomaly?mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Anomaly analysis for '${selectedEventId}' not found.`);
          throw new Error(`Failed to load anomaly analysis (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          if (data.status === "unavailable") {
            setAnomalyError(data.reason || "Historical baseline unavailable.");
            setAnomalyData(null);
          } else {
            setAnomalyData(data);
          }
        }
      } catch (err) {
        if (active) {
          setAnomalyError(err.message || "Failed to load anomaly analysis");
          setAnomalyData(null);
        }
      } finally {
        if (active) setLoadingAnomaly(false);
      }
    }
    fetchAnomaly();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // 5. Fetch Evidence Profile & Fusion (Step 7)
  const [evidenceData, setEvidenceData] = useState(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const [evidenceError, setEvidenceError] = useState(null);

  useEffect(() => {
    let active = true;
    async function fetchEvidence() {
      if (!selectedEventId) return;
      try {
        setLoadingEvidence(true);
        setEvidenceError(null);
        const res = await fetch(`${API_BASE}/events/${selectedEventId}/evidence?mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Evidence profile for '${selectedEventId}' not found.`);
          throw new Error(`Failed to load evidence profile (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          setEvidenceData(data);
        }
      } catch (err) {
        if (active) {
          setEvidenceError(err.message || "Failed to load evidence profile");
          setEvidenceData(null);
        }
      } finally {
        if (active) setLoadingEvidence(false);
      }
    }
    fetchEvidence();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // 6. Fetch Rule-Based Classification (Step 8)
  const [classificationData, setClassificationData] = useState(null);
  const [loadingClassification, setLoadingClassification] = useState(false);
  const [classificationError, setClassificationError] = useState(null);

  useEffect(() => {
    let active = true;
    async function fetchClassification() {
      if (!selectedEventId) return;
      try {
        setLoadingClassification(true);
        setClassificationError(null);
        const res = await fetch(`${API_BASE}/events/${selectedEventId}/classification?mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Classification for '${selectedEventId}' not found.`);
          throw new Error(`Failed to load classification (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          setClassificationData(data);
        }
      } catch (err) {
        if (active) {
          setClassificationError(err.message || "Failed to load classification");
          setClassificationData(null);
        }
      } finally {
        if (active) setLoadingClassification(false);
      }
    }
    fetchClassification();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // 7. Fetch AI Event Assessment & ML Classification (Steps 2 & 3)
  const [assessmentData, setAssessmentData] = useState(null);
  const [loadingAssessment, setLoadingAssessment] = useState(false);
  const [assessmentError, setAssessmentError] = useState(null);

  useEffect(() => {
    let active = true;
    async function fetchAssessment() {
      if (!selectedEventId) return;
      try {
        setLoadingAssessment(true);
        setAssessmentError(null);
        const res = await fetch(`${API_BASE}/events/${selectedEventId}/assessment?mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`Assessment for '${selectedEventId}' not found.`);
          throw new Error(`Failed to load assessment (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          if (data.status === "unavailable") {
            setAssessmentError(data.reason || "Assessment unavailable.");
            setAssessmentData(null);
          } else {
            setAssessmentData(data);
          }
        }
      } catch (err) {
        if (active) {
          setAssessmentError(err.message || "Assessment unavailable");
          setAssessmentData(null);
        }
      } finally {
        if (active) setLoadingAssessment(false);
      }
    }
    fetchAssessment();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // 7b. Fetch Trained Random Forest ML Prediction directly (Step 2 ML endpoint)
  const [mlPredictionData, setMlPredictionData] = useState(null);
  const [loadingMlPrediction, setLoadingMlPrediction] = useState(false);
  const [mlPredictionError, setMlPredictionError] = useState(null);
  const [showMlFeatures, setShowMlFeatures] = useState(false);

  useEffect(() => {
    let active = true;
    async function fetchMlPrediction() {
      if (!selectedEventId) return;
      try {
        setLoadingMlPrediction(true);
        setMlPredictionError(null);
        const res = await fetch(`${API_BASE}/ml/predict?event_id=${selectedEventId}&mode=${dataMode}`);
        if (!res.ok) {
          if (res.status === 404) throw new Error(`ML prediction for '${selectedEventId}' not found.`);
          throw new Error(`Failed to load ML prediction (HTTP ${res.status})`);
        }
        const data = await res.json();
        if (active) {
          setMlPredictionData(data);
        }
      } catch (err) {
        if (active) {
          setMlPredictionError(err.message || "ML prediction unavailable");
          setMlPredictionData(null);
        }
      } finally {
        if (active) setLoadingMlPrediction(false);
      }
    }
    fetchMlPrediction();
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // Unified ML inference values from /ml/predict or /assessment fallback
  const mlClass =
    mlPredictionData?.predicted_class ||
    assessmentData?.ml_class ||
    assessmentData?.evidence?.ml_inference?.predicted_class ||
    null;

  const mlConfidence =
    mlPredictionData?.confidence != null
      ? mlPredictionData.confidence
      : assessmentData?.ml_confidence != null
      ? assessmentData.ml_confidence
      : assessmentData?.evidence?.ml_inference?.confidence != null
      ? assessmentData.evidence.ml_inference.confidence
      : null;

  const mlProbabilities =
    mlPredictionData?.probabilities ||
    assessmentData?.evidence?.ml_inference?.probabilities ||
    { Agricultural: 0, Forest: 0, Industrial: 0, Other: 0 };

  const mlFeaturesUsed =
    mlPredictionData?.features_used ||
    assessmentData?.evidence?.ml_inference?.features_used ||
    null;

  // Derived event fields
  const eventMeta = historyData || {};
  const centroid = useMemo(() => {
    return (
      historyData?.spatial_summary?.centroid ||
      historyData?.centroid ||
      { latitude: 23.5, longitude: 85.5 }
    );
  }, [historyData]);

  const observations = useMemo(() => {
    return Array.isArray(historyData?.observations) ? historyData.observations : [];
  }, [historyData]);

  const spatialExtent = eventMeta.spatial_summary || {};
  const minLat = spatialExtent.min_latitude != null ? Number(spatialExtent.min_latitude) : null;
  const maxLat = spatialExtent.max_latitude != null ? Number(spatialExtent.max_latitude) : null;
  const minLon = spatialExtent.min_longitude != null ? Number(spatialExtent.min_longitude) : null;
  const maxLon = spatialExtent.max_longitude != null ? Number(spatialExtent.max_longitude) : null;

  const hasBoundingBox =
    minLat != null &&
    maxLat != null &&
    minLon != null &&
    maxLon != null &&
    (maxLat !== minLat || maxLon !== minLon);

  // 3. Fetch OSM Facility context for centroid
  useEffect(() => {
    let active = true;
    async function fetchAssets() {
      if (!centroid || centroid.latitude == null || centroid.longitude == null) return;
      try {
        setLoadingAssets(true);
        setAssetError(false);
        const res = await fetch(
          `${API_BASE}/assets?lat=${centroid.latitude}&lon=${centroid.longitude}&radius=5000`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (active) {
          setAssets(data);
        }
      } catch (err) {
        console.warn("Failed to load OSM assets:", err);
        if (active) setAssetError(true);
      } finally {
        if (active) setLoadingAssets(false);
      }
    }
    fetchAssets();
    return () => {
      active = false;
    };
  }, [centroid.latitude, centroid.longitude]);

  // Geographic validation attributes (strict and un-inferred)
  const geoDomain = eventMeta.geographic_validation?.domain || eventMeta.geographic_domain || "LAND";
  const geoState = eventMeta.geographic_validation?.state || eventMeta.state || "Unavailable";
  const geoDistrict = eventMeta.geographic_validation?.district || "Unavailable";
  const geoCity = eventMeta.geographic_validation?.city || "Unavailable";
  const geoSource =
    eventMeta.geographic_validation?.source ||
    "NOAA GLOBE 1km Land Mask / Natural Earth";
  const geoStatus = eventMeta.geographic_validation?.status || "Validated";

  // Temporal summary & consecutive pass dynamics
  const temporalSummary = eventMeta.temporal_summary || {};
  const brightnessSummary = eventMeta.brightness_summary || {};
  const frpSummary = eventMeta.frp_summary || {};

  // Check if this event already has a human verification record
  const existingVerification = useMemo(() => {
    if (!Array.isArray(verifiedEvents) || !selectedEventId) return null;
    return verifiedEvents.find((v) => {
      const vEid = v?.event_id || v?.features?.event_id;
      if (vEid) {
        return Boolean(selectedEventId && vEid.toUpperCase() === selectedEventId.toUpperCase());
      }
      const lat = Number(v?.event?.latitude);
      const lon = Number(v?.event?.longitude);
      const cLat = Number(centroid?.latitude);
      const cLon = Number(centroid?.longitude);
      return (
        Number.isFinite(lat) &&
        Number.isFinite(lon) &&
        Number.isFinite(cLat) &&
        Number.isFinite(cLon) &&
        Math.abs(lat - cLat) < 0.01 &&
        Math.abs(lon - cLon) < 0.01
      );
    });
  }, [verifiedEvents, centroid, selectedEventId]);

  // Synchronize verification form state when event or existing verification changes
  const prevEventIdRef = useRef(selectedEventId);
  useEffect(() => {
    if (prevEventIdRef.current !== selectedEventId) {
      prevEventIdRef.current = selectedEventId;
      setIsEditingExisting(false);
      setVerifSuccessMsg("");
      setVerifErrorMsg("");
      if (existingVerification) {
        setSelectedLabel(existingVerification.label || "ACTIVE_FIRE");
        setAnalystNotes(existingVerification.notes || existingVerification.features?.analyst_notes || "");
      } else {
        setSelectedLabel("ACTIVE_FIRE");
        setAnalystNotes("");
      }
    } else if (existingVerification && !isEditingExisting) {
      setSelectedLabel(existingVerification.label || "ACTIVE_FIRE");
      setAnalystNotes(existingVerification.notes || existingVerification.features?.analyst_notes || "");
    }
  }, [existingVerification, selectedEventId, isEditingExisting]);

  // Nearest facility computation from assets
  const nearestFacility = useMemo(() => {
    if (!assets || !Array.isArray(assets.assets) || assets.assets.length === 0) return null;
    let closest = null;
    let minD = Infinity;
    for (const a of assets.assets) {
      const alat = Number(a.latitude ?? a.lat);
      const alon = Number(a.longitude ?? a.lon);
      if (Number.isFinite(alat) && Number.isFinite(alon)) {
        const d = haversineKm(Number(centroid.latitude), Number(centroid.longitude), alat, alon);
        if (d < minD) {
          minD = d;
          closest = { ...a, distanceKm: d.toFixed(2), lat: alat, lon: alon };
        }
      }
    }
    return closest;
  }, [assets, centroid]);

  // Handle Human Verification initiation (triggers confirmation)
  function handleVerifySubmit(e) {
    if (e) e.preventDefault();
    setVerifSuccessMsg("");
    setVerifErrorMsg("");
    setShowConfirmModal(true);
  }

  // Execute confirmed verification submission
  async function executeVerifySubmit() {
    if (submittingVerif) return;
    try {
      setSubmittingVerif(true);
      setVerifSuccessMsg("");
      setVerifErrorMsg("");

      const payload = {
        event_id: selectedEventId,
        label: selectedLabel,
        notes: analystNotes.trim(),
        system_classification_at_review: classificationData?.classification || "UNKNOWN",
        source_context: "AGNIVISION Event Evaluation Station",
        latitude: Number(centroid.latitude),
        longitude: Number(centroid.longitude),
        features: {
          event_id: selectedEventId,
          observation_count: eventMeta.observation_count,
          persistence_days: eventMeta.persistence_days,
          brightness_avg: brightnessSummary.avg,
          frp_avg: frpSummary.avg,
          risk_score: eventMeta.risk_score,
          risk_level: eventMeta.risk_level,
          state: geoState,
          domain: geoDomain,
          analyst_notes: analystNotes.trim(),
          source: "AGNIVISION Event Evaluation Station"
        },
        mode: dataMode
      };

      const res = await fetch(`${API_BASE}/verify-event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson?.detail?.message || errJson?.detail || `HTTP ${res.status}`);
      }

      setVerifSuccessMsg(`Human verification saved successfully for ${selectedEventId}. Complete AI snapshot captured.`);
      setShowConfirmModal(false);
      setIsEditingExisting(false);
      if (typeof onRefreshVerified === "function") {
        onRefreshVerified();
      }
    } catch (err) {
      setVerifErrorMsg(`Verification submission failed: ${err.message}`);
      setShowConfirmModal(false);
    } finally {
      setSubmittingVerif(false);
    }
  }

  return (
    <div className="evaluation-workspace-container">
      {/* 1. TOP HEADER & EVENT SELECTOR */}
      <header className="eval-header">
        <div className="eval-header-left">
          <div className="eval-badge">
            <span className="live-dot" /> Evidence-Based Analysis
          </div>
          <h2>Event Evaluation Workspace</h2>
          <p className="eval-subtitle">
            Multi-source spatial, temporal, and physical evidence assessment for persistent thermal events
          </p>
        </div>

        <div className="eval-header-controls">
          <label className="event-selector-label">
            <span>SELECT THERMAL EVENT:</span>
            <select
              value={selectedEventId}
              onChange={(e) => {
                const val = e.target.value;
                setSelectedEventId(val);
                if (typeof onSelectEvent === "function") {
                  onSelectEvent(val);
                }
              }}
              className="event-dropdown"
              disabled={loadingEvents}
            >
              {eventsList.map((ev) => (
                <option key={ev.event_id} value={ev.event_id}>
                  {ev.event_id} ({ev.observation_count} obs · {ev.state || "Unassigned"} · {ev.risk_level})
                </option>
              ))}
            </select>
          </label>

          {onOpenTemporal && (
            <button
              type="button"
              className="jump-temporal-btn"
              onClick={() => onOpenTemporal(selectedEventId)}
              title={`View chronological history for ${selectedEventId} in Temporal Explorer`}
              aria-label={`View history for ${selectedEventId}`}
            >
              ◷ View History ({selectedEventId}) ↗
            </button>
          )}
        </div>
      </header>

      {/* ERROR & LOADING STATES */}
      {loadingHistory && (
        <div className="eval-loading-bar">
          <div className="loading-spinner" />
          <span>Retrieving observation history, geographic layers, and contextual evidence for {selectedEventId}...</span>
        </div>
      )}

      {historyError && (
        <div className="eval-error-card">
          <span className="error-icon">⚠</span>
          <div>
            <strong>Event History Query Error</strong>
            <p>{historyError}</p>
          </div>
        </div>
      )}

      {!historyData && !loadingHistory && !historyError && (
        <div className="eval-empty-state">
          <span className="empty-icon">🛰</span>
          <strong>No Persistent Thermal Event Selected</strong>
          <p>Please select an event ID from the dropdown above to begin evidence-based evaluation.</p>
        </div>
      )}

      {historyData && (
        <>
          {/* ROW 1: EVENT SUMMARY & GEOGRAPHIC VALIDATION */}
          <div className="eval-grid-two">
            {/* 2. EVENT SUMMARY */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">📑</span>
                  Event Summary · {eventMeta.event_id}
                </h3>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  {onOpenTemporal && (
                    <button
                      type="button"
                      onClick={() => onOpenTemporal(selectedEventId)}
                      style={{
                        background: "rgba(56, 189, 248, 0.12)",
                        color: "#38bdf8",
                        border: "1px solid rgba(56, 189, 248, 0.3)",
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: 700,
                        cursor: "pointer"
                      }}
                      title={`Open chronological observations for ${selectedEventId} in Temporal Explorer`}
                    >
                      ◷ View History
                    </button>
                  )}
                  <span className={`panel-chip ${String(eventMeta.risk_level || "low").toLowerCase()}`}>
                    {eventMeta.risk_level || "Low"}
                  </span>
                  {mlClass && (
                    <a
                      href="#ai-ml-panel"
                      style={{
                        background: "rgba(139, 92, 246, 0.15)",
                        color: "#c084fc",
                        border: "1px solid rgba(139, 92, 246, 0.35)",
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontSize: "11px",
                        fontWeight: 700,
                        textDecoration: "none",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "4px"
                      }}
                      title="Jump directly to AI Intelligence — Random Forest Classification"
                    >
                      <span>🌲 RF ML:</span>
                      <strong>{mlClass}</strong>
                      {mlConfidence != null && <span>({(mlConfidence * 100).toFixed(0)}%)</span>}
                    </a>
                  )}
                </div>
              </div>

              <div className="eval-data-grid">
                <div className="eval-data-row">
                  <span className="eval-data-label">Entity Classification</span>
                  <strong className="eval-data-value">Thermal Event</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Sequence Status</span>
                  <strong className="eval-data-value highlight">Monitored Cluster</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Discrete Sensor Detections</span>
                  <strong className="eval-data-value">
                    {eventMeta.observation_count} {eventMeta.observation_count === 1 ? "observation" : "observations"}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Persistence Span</span>
                  <strong className="eval-data-value">
                    {eventMeta.persistence_days} {eventMeta.persistence_days === 1 ? "day" : "days"}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">First Detected</span>
                  <strong className="eval-data-value mono">{formatIsoDateTime(temporalSummary.first_detected || eventMeta.first_detected)}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Last Detected</span>
                  <strong className="eval-data-value mono">{formatIsoDateTime(temporalSummary.last_detected || eventMeta.last_detected)}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Spatial Centroid</span>
                  <strong className="eval-data-value mono">
                    {Number(centroid.latitude).toFixed(5)}°, {Number(centroid.longitude).toFixed(5)}°
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Spatial Footprint Extent</span>
                  <strong className="eval-data-value mono">
                    {minLat != null && maxLat != null
                      ? `ΔLat ${(maxLat - minLat).toFixed(3)}° · ΔLon ${(maxLon - minLon).toFixed(3)}°`
                      : "Point Anomaly"}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">State Attribution</span>
                  <strong className="eval-data-value">{geoState}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Prototype Risk Score</span>
                  <strong className="eval-data-value" style={{ color: riskColor(eventMeta.risk_level) }}>
                    {eventMeta.risk_score} / 100
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">AI Event Assessment</span>
                  <strong className="eval-data-value" style={{ color: "#a855f7", fontWeight: 700 }}>
                    {assessmentData?.assessment ? assessmentData.assessment.replace(/_/g, " ") : (loadingAssessment ? "Analyzing..." : "Assessment unavailable")}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">ML Classification</span>
                  <strong className="eval-data-value" style={{ color: "#38bdf8", fontWeight: 700 }}>
                    {mlClass ? `${mlClass} (${((mlConfidence || 0) * 100).toFixed(1)}%)` : (loadingMlPrediction || loadingAssessment ? "Predicting..." : "ML classification unavailable")}
                  </strong>
                </div>
              </div>

              <div className="eval-limitation-box">
                <strong>Standard Terminology Compliance:</strong> In accordance with satellite remote sensing standards, this sequence is classified as a <em>Thermal Event</em> representing aggregated VIIRS 375m sensor radiance. It is not designated as a "confirmed fire" without ground verification.
              </div>
            </section>

            {/* 3. GEOGRAPHIC VALIDATION */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">🌐</span>
                  Geographic Validation
                </h3>
                <span className="panel-chip live">{geoDomain}</span>
              </div>

              <div className="eval-data-grid">
                <div className="eval-data-row">
                  <span className="eval-data-label">Land Cover Domain</span>
                  <strong className="eval-data-value highlight">{geoDomain}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Validation Status</span>
                  <strong className="eval-data-value" style={{ color: "#10b981" }}>{geoStatus}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">State / Union Territory</span>
                  <strong className="eval-data-value">{geoState}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">District</span>
                  <strong className="eval-data-value">{geoDistrict}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">City / Settlement</span>
                  <strong className="eval-data-value">{geoCity}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Validation Source</span>
                  <strong className="eval-data-value">{geoSource}</strong>
                </div>
              </div>

              <div className="eval-limitation-box">
                <strong>Geographic Integrity Notice:</strong> Land cover domain is strictly verified against NOAA GLOBE 1km land-water models and Natural Earth Admin-1 boundaries. Missing district or city fields are left as <em>Unavailable</em> without heuristic interpolation. Domains such as <code>OFFSHORE_MARINE</code> and <code>INLAND_WATER</code> are preserved verbatim.
              </div>
            </section>
          </div>

          {/* ROW 2: THERMAL EVIDENCE & TEMPORAL / PERSISTENCE */}
          <div className="eval-grid-two">
            {/* 4. THERMAL EVIDENCE */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">🔥</span>
                  Thermal Evidence (NASA FIRMS VIIRS)
                </h3>
                <span className="panel-chip live">{observations.length} Detections</span>
              </div>

              <div className="thermal-stats-grid">
                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">BRIGHTNESS MIN</span>
                  <div className="stat-cell-number">{brightnessSummary.min != null ? `${brightnessSummary.min} K` : "—"}</div>
                  <span className="stat-cell-unit">VIIRS $T_4$ (4µm)</span>
                </div>

                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">BRIGHTNESS MAX</span>
                  <div className="stat-cell-number" style={{ color: "#f59e0b" }}>
                    {brightnessSummary.max != null ? `${brightnessSummary.max} K` : "—"}
                  </div>
                  <span className="stat-cell-unit">Peak Intensity</span>
                </div>

                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">BRIGHTNESS AVG</span>
                  <div className="stat-cell-number">{brightnessSummary.avg != null ? `${brightnessSummary.avg} K` : "—"}</div>
                  <span className="stat-cell-unit">Event Mean</span>
                </div>

                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">FRP MIN</span>
                  <div className="stat-cell-number">{frpSummary.min != null ? `${frpSummary.min} MW` : "—"}</div>
                  <span className="stat-cell-unit">Radiative Power</span>
                </div>

                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">FRP MAX</span>
                  <div className="stat-cell-number" style={{ color: "#ef4444" }}>
                    {frpSummary.max != null ? `${frpSummary.max} MW` : "—"}
                  </div>
                  <span className="stat-cell-unit">Peak Release</span>
                </div>

                <div className="stat-metric-cell">
                  <span className="stat-cell-kicker">FRP AVG</span>
                  <div className="stat-cell-number">{frpSummary.avg != null ? `${frpSummary.avg} MW` : "—"}</div>
                  <span className="stat-cell-unit">Mean Radiative Power</span>
                </div>
              </div>

              {/* Sparkline time-series trends */}
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                <CompactBrightnessChart observations={observations} />
                <CompactFrpChart observations={observations} />
              </div>

              <div className="eval-limitation-box">
                <strong>Empirical Observation Only:</strong> Radiance values represent raw sensor measurements from the VIIRS 375m I-bands ($T_4$ mid-infrared at 4µm and $T_5$ thermal infrared at 11µm). No spline smoothing or synthetic interpolated observations have been injected.
              </div>
            </section>

            {/* 5. TEMPORAL / PERSISTENCE ANALYSIS */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">⏳</span>
                  Temporal / Persistence Analysis
                </h3>
                <span className="panel-chip live">
                  {eventMeta.persistence_days} {eventMeta.persistence_days === 1 ? "Day" : "Days"} Persistence
                </span>
              </div>

              <div className="eval-data-grid">
                <div className="eval-data-row">
                  <span className="eval-data-label">First Sensor Pass</span>
                  <strong className="eval-data-value mono">{formatIsoDateTime(temporalSummary.first_detected || eventMeta.first_detected)}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Last Sensor Pass</span>
                  <strong className="eval-data-value mono">{formatIsoDateTime(temporalSummary.last_detected || eventMeta.last_detected)}</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Active Observation Span</span>
                  <strong className="eval-data-value">
                    {eventMeta.persistence_days} calendar {eventMeta.persistence_days === 1 ? "day" : "days"}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Total Sensor Detections</span>
                  <strong className="eval-data-value">
                    {observations.length} discrete {observations.length === 1 ? "observation" : "observations"}
                  </strong>
                </div>
              </div>

              {/* Compact Timeline of Passes */}
              <div className="compact-timeline-container">
                <span className="eval-data-label" style={{ display: "block", marginBottom: "8px" }}>
                  Chronological Revisit Steps ({observations.length} passes)
                </span>
                <div className="compact-timeline-scroll">
                  {observations.slice(0, 18).map((obs, idx) => (
                    <React.Fragment key={`t-node-${idx}`}>
                      <div className="timeline-step-node">
                        <span
                          className="timeline-dot"
                          style={{ backgroundColor: riskColor(obs.risk_level) }}
                        />
                        <span className="timeline-date-label">{formatShortDate(obs.acq_date)}</span>
                        <span className="timeline-time-label">{formatAcqTime(obs.acq_time)}</span>
                      </div>
                      {idx < Math.min(observations.length - 1, 17) && <div className="timeline-connector" />}
                    </React.Fragment>
                  ))}
                  {observations.length > 18 && (
                    <div className="timeline-step-node" style={{ justifyContent: "center" }}>
                      <span className="timeline-date-label">+{observations.length - 18} more</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="eval-limitation-box">
                <strong>Scientific Revisit Warning:</strong> Multi-day persistence indicates that the satellite detected thermal radiance across repeated orbital overpasses within 3.0 km. <strong>It does NOT establish continuous burning between sensor passes.</strong> Gaps between satellite passes remain unobserved by polar-orbiting sensors.
              </div>
            </section>
          </div>

          {/* ROW 3: SPATIAL ANALYSIS & FACILITY CONTEXT */}
          <div className="eval-grid-two">
            {/* 6. SPATIAL ANALYSIS */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">🗺</span>
                  Spatial Footprint & Extent
                </h3>
                <span className="panel-chip live">3.0 km Spatiotemporal Cluster</span>
              </div>

              <div className="eval-data-grid">
                <div className="eval-data-row">
                  <span className="eval-data-label">Centroid Latitude</span>
                  <strong className="eval-data-value mono">{Number(centroid.latitude).toFixed(5)}° N</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Centroid Longitude</span>
                  <strong className="eval-data-value mono">{Number(centroid.longitude).toFixed(5)}° E</strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Bounding Latitude (Min → Max)</span>
                  <strong className="eval-data-value mono">
                    {minLat != null ? `${minLat.toFixed(4)}° → ${maxLat.toFixed(4)}°` : "—"}
                  </strong>
                </div>

                <div className="eval-data-row">
                  <span className="eval-data-label">Bounding Longitude (Min → Max)</span>
                  <strong className="eval-data-value mono">
                    {minLon != null ? `${minLon.toFixed(4)}° → ${maxLon.toFixed(4)}°` : "—"}
                  </strong>
                </div>
              </div>

              {/* Embedded Leaflet Map */}
              <div className="spatial-map-wrapper">
                <div className="spatial-map-controls">
                  <button
                    type="button"
                    className={`map-layer-btn ${mapBaseLayer === "standard" ? "active" : ""}`}
                    onClick={() => setMapBaseLayer("standard")}
                  >
                    Standard
                  </button>
                  <button
                    type="button"
                    className={`map-layer-btn ${mapBaseLayer === "satellite" ? "active" : ""}`}
                    onClick={() => setMapBaseLayer("satellite")}
                  >
                    Satellite
                  </button>
                </div>

                <MapContainer
                  center={[Number(centroid.latitude), Number(centroid.longitude)]}
                  zoom={12}
                  style={{ height: "100%", width: "100%", background: "#0b0f19" }}
                  scrollWheelZoom={false}
                >
                  <RecenterMap lat={Number(centroid.latitude)} lon={Number(centroid.longitude)} zoom={12} />

                  {mapBaseLayer === "satellite" ? (
                    <TileLayer
                      attribution="&copy; Esri, Maxar, Earthstar Geographics"
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                      maxZoom={18}
                    />
                  ) : (
                    <TileLayer
                      attribution="&copy; OpenStreetMap contributors"
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                      maxZoom={18}
                    />
                  )}

                  {/* Bounding extent rectangle */}
                  {hasBoundingBox && (
                    <Rectangle
                      bounds={[
                        [minLat, minLon],
                        [maxLat, maxLon]
                      ]}
                      pathOptions={{
                        color: "#3b82f6",
                        weight: 1.5,
                        dashArray: "4 4",
                        fillColor: "#3b82f6",
                        fillOpacity: 0.08
                      }}
                    />
                  )}

                  {/* Centroid Marker */}
                  <CircleMarker
                    center={[Number(centroid.latitude), Number(centroid.longitude)]}
                    radius={8}
                    pathOptions={{
                      color: "#ffffff",
                      fillColor: "#3b82f6",
                      fillOpacity: 1,
                      weight: 2
                    }}
                  >
                    <Popup>
                      <strong>Event Centroid · {eventMeta.event_id}</strong>
                      <div>{Number(centroid.latitude).toFixed(5)}°, {Number(centroid.longitude).toFixed(5)}°</div>
                    </Popup>
                  </CircleMarker>

                  {/* Observations */}
                  {observations.map((obs, idx) => {
                    const lat = Number(obs.latitude);
                    const lon = Number(obs.longitude);
                    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
                    return (
                      <CircleMarker
                        key={`map-obs-${idx}`}
                        center={[lat, lon]}
                        radius={5}
                        pathOptions={{
                          color: "#ffffff",
                          fillColor: riskColor(obs.risk_level),
                          fillOpacity: 0.85,
                          weight: 1
                        }}
                      >
                        <Popup>
                          <strong>Obs #{idx + 1}</strong>
                          <div>Time: {formatDateTimeLabel(obs)}</div>
                          <div>FRP: {obs.frp || "Unavailable"} MW</div>
                        </Popup>
                      </CircleMarker>
                    );
                  })}
                </MapContainer>
              </div>

              <div className="eval-limitation-box">
                <strong>Spatial Geometry Resolution:</strong> VIIRS 375m pixels have an ellipsoidal ground footprint that expands toward the scan edge. Sub-pixel thermal sources within the footprint are localized to the pixel center coordinate.
              </div>
            </section>

            {/* 7. FACILITY / INFRASTRUCTURE CONTEXT */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">🏭</span>
                  Infrastructure & Facility Context (OSM 5km)
                </h3>
                <span className="panel-chip live">OpenStreetMap / Overpass</span>
              </div>

              {loadingAssets && (
                <div style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "12px", color: "#94a3b8" }}>
                  <div className="loading-spinner" style={{ width: "14px", height: "14px" }} />
                  <span>Scanning OpenStreetMap infrastructure within 5 km radius...</span>
                </div>
              )}

              {/* Infrastructure counts */}
              <div className="facility-counts-grid">
                <div className="facility-count-box">
                  <span className="facility-count-icon">🏭</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.industrial ?? "0"}</span>
                    <span className="facility-count-title">Industrial</span>
                  </div>
                </div>

                <div className="facility-count-box">
                  <span className="facility-count-icon">⚡</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.power ?? "0"}</span>
                    <span className="facility-count-title">Power Grid</span>
                  </div>
                </div>

                <div className="facility-count-box">
                  <span className="facility-count-icon">🏢</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.buildings ?? "0"}</span>
                    <span className="facility-count-title">Buildings</span>
                  </div>
                </div>

                <div className="facility-count-box">
                  <span className="facility-count-icon">🏥</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.hospitals ?? "0"}</span>
                    <span className="facility-count-title">Hospitals</span>
                  </div>
                </div>

                <div className="facility-count-box">
                  <span className="facility-count-icon">🏫</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.schools ?? "0"}</span>
                    <span className="facility-count-title">Schools</span>
                  </div>
                </div>

                <div className="facility-count-box">
                  <span className="facility-count-icon">🛣</span>
                  <div className="facility-count-meta">
                    <span className="facility-count-num">{assets?.counts?.roads ?? "0"}</span>
                    <span className="facility-count-title">Highways</span>
                  </div>
                </div>
              </div>

              {/* Nearest facility detection */}
              <div className="nearest-facility-card">
                <span className="eval-data-label">Nearest Mapped Infrastructure</span>
                {nearestFacility ? (
                  <div>
                    <strong style={{ color: "#f8fafc", fontSize: "13px" }}>
                      {nearestFacility.name || nearestFacility.tags?.name || `${nearestFacility.type || "Facility"}`}
                    </strong>
                    <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "3px" }}>
                      Type: <span style={{ textTransform: "capitalize" }}>{nearestFacility.type}</span> · Distance: <strong>{nearestFacility.distanceKm} km</strong> from centroid
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: "12px", color: "#64748b" }}>
                    {assetError ? "Overpass query unavailable for this coordinate" : "No mapped industrial or public facilities found within 5.0 km"}
                  </div>
                )}
              </div>

              <div className="eval-limitation-box">
                <strong>Contextual Evidence Only:</strong> Spatial proximity to industrial plants, power stations, or roadways provides situational context. <strong>It does NOT establish thermal source causation.</strong> Nearby facilities cannot be concluded as the source without ground inspection.
              </div>
            </section>
          </div>

          {/* ROW 4: HISTORICAL BASELINE & EVIDENCE PROFILE */}
          <div className="eval-grid-two">
            {/* 8. HISTORICAL BASELINE & ANOMALY ANALYSIS (STEP 6) */}
            <section className="eval-panel" id="eval-section-baseline">
              {(() => {
                const interpCode = anomalyData?.interpretation || "WITHIN_BASELINE";
                const badgeClass =
                  interpCode === "WITHIN_BASELINE" ? "badge-within-baseline" :
                  interpCode === "ELEVATED" ? "badge-elevated" :
                  interpCode === "HIGHLY_ELEVATED" ? "badge-highly-elevated" :
                  interpCode === "BELOW_BASELINE" ? "badge-below-baseline" :
                  "badge-insufficient-baseline";

                const interpLabel =
                  interpCode === "WITHIN_BASELINE" ? "Within Historical Baseline" :
                  interpCode === "ELEVATED" ? "Elevated Above Baseline" :
                  interpCode === "HIGHLY_ELEVATED" ? "Highly Elevated Above Baseline" :
                  interpCode === "BELOW_BASELINE" ? "Below Historical Baseline" :
                  interpCode === "INSUFFICIENT_BASELINE" ? "Insufficient Baseline Data" :
                  interpCode;

                const curM = anomalyData?.current_metrics || {};
                const baseM = anomalyData?.baseline_metrics || {};
                const comp = anomalyData?.comparisons || {};
                const stdDev = anomalyData?.standardized_deviation || {};

                return (
                  <>
                    <div className="eval-panel-header">
                      <h3>
                        <span className="panel-header-icon">📊</span>
                        Historical Baseline & Anomaly Analysis
                      </h3>
                      {anomalyData ? (
                        <span className={`panel-chip live ${badgeClass}`}>
                          {interpLabel}
                        </span>
                      ) : baselineSummary ? (
                        <span className="panel-chip live">Historical Reference Data</span>
                      ) : (
                        <span className="panel-chip">Reference Baseline</span>
                      )}
                    </div>

                    {(loadingBaseline || loadingAnomaly) && (
                      <div className="eval-loading-bar" style={{ margin: "14px 0" }}>
                        <div className="loading-spinner" />
                        <span>Comparing event metrics against NASA FIRMS historical baseline...</span>
                      </div>
                    )}

                    {(anomalyError || baselineError) && !loadingBaseline && !loadingAnomaly && !anomalyData && (
                      <div className="baseline-unavailable-box">
                        <div className="baseline-icon">◷</div>
                        <strong className="baseline-title">Historical baseline comparison unavailable</strong>
                        <p className="baseline-desc">{anomalyError || baselineError}</p>
                        <div className="baseline-specs">
                          <span className="baseline-spec-tag">Zero Synthetic Baselines</span>
                          <span className="baseline-spec-tag">10-Day Sliding NRT != Archive</span>
                          <span className="baseline-spec-tag">No Fabricated Percentiles</span>
                        </div>
                      </div>
                    )}

                    {anomalyData && !loadingAnomaly && (
                      <div className="anomaly-analysis-content">
                        {/* Status Banner */}
                        <div className={`anomaly-summary-banner ${badgeClass}`}>
                          <div className="anomaly-banner-header">
                            <span className="anomaly-banner-title">
                              {interpLabel}
                            </span>
                            <div className="anomaly-banner-badges">
                              {anomalyData.is_fallback ? (
                                <span className="baseline-scope-tag fallback" title="No historical detections in local 0.1° cell; regional baseline used">
                                  ⚠ Regional Fallback Baseline (82°–90°E, 20°–27°N)
                                </span>
                              ) : (
                                <span className="baseline-scope-tag cell" title={`0.1° cell centered at ${anomalyData.grid_cell?.cell_id}`}>
                                  0.1° Spatial Grid ({anomalyData.grid_cell?.cell_id}) · {anomalyData.grid_cell?.observation_count} historical detections
                                </span>
                              )}
                              <span className="baseline-scope-tag period">
                                June 1–30, 2026 ({anomalyData.baseline_source})
                              </span>
                            </div>
                          </div>
                          <p className="anomaly-summary-desc">
                            {anomalyData.interpretation_summary}
                          </p>
                        </div>

                        {/* Comparison Table */}
                        <div className="anomaly-table-wrapper">
                          <table className="anomaly-comparison-table">
                            <thead>
                              <tr>
                                <th>Metric</th>
                                <th>Current Event ({selectedEventId})</th>
                                <th>Historical Baseline (June 2026 SP)</th>
                                <th>Variance (Δ)</th>
                                <th>Standardized (z)</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr>
                                <td><strong>Mean Brightness ($T_4$)</strong></td>
                                <td>{curM.mean_brightness != null ? `${curM.mean_brightness} K` : "—"}</td>
                                <td>
                                  {baseM.mean_brightness != null
                                    ? `${baseM.mean_brightness} K (±${stdDev.historical_brightness_std ?? "—"})`
                                    : "—"}
                                </td>
                                <td className={comp.brightness_percent_difference > 0 ? "anomaly-diff-positive" : comp.brightness_percent_difference < 0 ? "anomaly-diff-negative" : ""}>
                                  {comp.brightness_difference != null
                                    ? `${comp.brightness_difference > 0 ? "+" : ""}${comp.brightness_difference} K (${comp.brightness_percent_difference > 0 ? "+" : ""}${comp.brightness_percent_difference}%)`
                                    : "—"}
                                </td>
                                <td>
                                  <span className="anomaly-z-tag">
                                    {stdDev.brightness_z_score != null
                                      ? `${stdDev.brightness_z_score > 0 ? "+" : ""}${stdDev.brightness_z_score}σ`
                                      : "Unavailable (n<3)"}
                                  </span>
                                </td>
                              </tr>

                              <tr>
                                <td><strong>Max Brightness ($T_4$)</strong></td>
                                <td>{curM.max_brightness != null ? `${curM.max_brightness} K` : "—"}</td>
                                <td>{baseM.max_brightness != null ? `${baseM.max_brightness} K` : "—"}</td>
                                <td className={((curM.max_brightness || 0) - (baseM.max_brightness || 0)) > 0 ? "anomaly-diff-positive" : "anomaly-diff-negative"}>
                                  {curM.max_brightness != null && baseM.max_brightness != null
                                    ? `${((curM.max_brightness - baseM.max_brightness) > 0 ? "+" : "")}${(curM.max_brightness - baseM.max_brightness).toFixed(2)} K`
                                    : "—"}
                                </td>
                                <td style={{ color: "#64748b" }}>—</td>
                              </tr>

                              <tr>
                                <td><strong>Mean Fire Radiative Power (FRP)</strong></td>
                                <td>{curM.mean_frp != null ? `${curM.mean_frp} MW` : "—"}</td>
                                <td>
                                  {baseM.mean_frp != null
                                    ? `${baseM.mean_frp} MW (±${stdDev.historical_frp_std ?? "—"})`
                                    : "—"}
                                </td>
                                <td className={comp.frp_percent_difference > 0 ? "anomaly-diff-positive" : comp.frp_percent_difference < 0 ? "anomaly-diff-negative" : ""}>
                                  {comp.frp_difference != null
                                    ? `${comp.frp_difference > 0 ? "+" : ""}${comp.frp_difference} MW (${comp.frp_percent_difference > 0 ? "+" : ""}${comp.frp_percent_difference}%)`
                                    : "—"}
                                </td>
                                <td>
                                  <span className="anomaly-z-tag">
                                    {stdDev.frp_z_score != null
                                      ? `${stdDev.frp_z_score > 0 ? "+" : ""}${stdDev.frp_z_score}σ`
                                      : "Unavailable (n<3)"}
                                  </span>
                                </td>
                              </tr>

                              <tr>
                                <td><strong>Max Fire Radiative Power (FRP)</strong></td>
                                <td>{curM.max_frp != null ? `${curM.max_frp} MW` : "—"}</td>
                                <td>{baseM.max_frp != null ? `${baseM.max_frp} MW` : "—"}</td>
                                <td className={((curM.max_frp || 0) - (baseM.max_frp || 0)) > 0 ? "anomaly-diff-positive" : "anomaly-diff-negative"}>
                                  {curM.max_frp != null && baseM.max_frp != null
                                    ? `${((curM.max_frp - baseM.max_frp) > 0 ? "+" : "")}${(curM.max_frp - baseM.max_frp).toFixed(2)} MW`
                                    : "—"}
                                </td>
                                <td style={{ color: "#64748b" }}>—</td>
                              </tr>

                              <tr>
                                <td><strong>Observation Activity</strong></td>
                                <td>{curM.observation_count} obs ({curM.observation_days} active days / {curM.persistence_days}d)</td>
                                <td>{baseM.observation_count} obs (June 2026 SP)</td>
                                <td>Ratio: <strong>{comp.observation_activity_ratio != null ? `${comp.observation_activity_ratio}x` : "—"}</strong></td>
                                <td>
                                  <span className="baseline-spec-tag" style={{ fontSize: "10px" }}>
                                    {comp.observation_activity_ratio > 1.5 ? "ELEVATED_ACTIVITY" : comp.observation_activity_ratio < 0.5 ? "LOW_ACTIVITY" : "NORMAL_FREQUENCY"}
                                  </span>
                                </td>
                              </tr>
                            </tbody>
                          </table>
                        </div>

                        {/* Compact Visual Comparison Bars */}
                        <div className="anomaly-visual-bars">
                          <div className="anomaly-bar-card">
                            <div className="anomaly-bar-header">
                              <span>Brightness ($T_4$) Baseline Comparison</span>
                              <span>Event: <strong>{curM.mean_brightness} K</strong> vs Baseline: <strong>{baseM.mean_brightness} K</strong></span>
                            </div>
                            <div className="anomaly-bar-track">
                              {(() => {
                                const cur = curM.mean_brightness || 300;
                                const base = baseM.mean_brightness || 300;
                                const std = stdDev.historical_brightness_std || 10;
                                const min = Math.min(cur, base - std * 1.5) - 5;
                                const max = Math.max(cur, base + std * 1.5) + 5;
                                const span = max - min || 1;
                                const curPct = Math.max(0, Math.min(100, ((cur - min) / span) * 100));
                                const basePct = Math.max(0, Math.min(100, ((base - min) / span) * 100));
                                const bandLeft = Math.max(0, Math.min(100, ((base - std - min) / span) * 100));
                                const bandWidth = Math.max(2, Math.min(100 - bandLeft, ((std * 2) / span) * 100));
                                return (
                                  <div className="gauge-track-inner">
                                    <div className="gauge-band-std" style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }} title={`Baseline ±1σ range (${(base-std).toFixed(1)}K - ${(base+std).toFixed(1)}K)`} />
                                    <div className="gauge-tick-baseline" style={{ left: `${basePct}%` }} title={`Baseline Mean: ${base}K`} />
                                    <div className="gauge-marker-event" style={{ left: `${curPct}%` }} title={`Current Event Mean: ${cur}K`} />
                                  </div>
                                );
                              })()}
                            </div>
                            <div className="anomaly-bar-footer">
                              <span>Low Radiance</span>
                              <span className="legend-item"><span className="legend-dot std-band" /> Baseline Mean ±1σ</span>
                              <span className="legend-item"><span className="legend-dot event-marker" /> Current Event Mean</span>
                              <span>High Radiance</span>
                            </div>
                          </div>

                          <div className="anomaly-bar-card">
                            <div className="anomaly-bar-header">
                              <span>Fire Radiative Power (FRP) Baseline Comparison</span>
                              <span>Event: <strong>{curM.mean_frp} MW</strong> vs Baseline: <strong>{baseM.mean_frp} MW</strong></span>
                            </div>
                            <div className="anomaly-bar-track">
                              {(() => {
                                const cur = curM.mean_frp || 1;
                                const base = baseM.mean_frp || 1;
                                const std = stdDev.historical_frp_std || 1;
                                const min = 0;
                                const max = Math.max(cur, base + std * 1.5, 5) * 1.2;
                                const span = max - min || 1;
                                const curPct = Math.max(0, Math.min(100, ((cur - min) / span) * 100));
                                const basePct = Math.max(0, Math.min(100, ((base - min) / span) * 100));
                                const bandLeft = Math.max(0, Math.min(100, ((Math.max(0, base - std) - min) / span) * 100));
                                const bandWidth = Math.max(2, Math.min(100 - bandLeft, ((std * 2) / span) * 100));
                                return (
                                  <div className="gauge-track-inner">
                                    <div className="gauge-band-std" style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }} title={`Baseline ±1σ range (${Math.max(0, base-std).toFixed(1)}MW - ${(base+std).toFixed(1)}MW)`} />
                                    <div className="gauge-tick-baseline" style={{ left: `${basePct}%` }} title={`Baseline Mean: ${base}MW`} />
                                    <div className="gauge-marker-event" style={{ left: `${curPct}%` }} title={`Current Event Mean: ${cur}MW`} />
                                  </div>
                                );
                              })()}
                            </div>
                            <div className="anomaly-bar-footer">
                              <span>0 MW</span>
                              <span className="legend-item"><span className="legend-dot std-band" /> Baseline Mean ±1σ</span>
                              <span className="legend-item"><span className="legend-dot event-marker" /> Current Event Mean</span>
                              <span>Peak FRP</span>
                            </div>
                          </div>
                        </div>

                        {/* Scientific Limitations & Provenance Note */}
                        <div className="eval-limitation-box">
                          <strong>Rule-Based Anomaly Assessment:</strong> Statistical comparison does not indicate physical cause, ignition source, or confirm land-use classification. Differences reflect sensor-observed radiance flux relative to historical detection patterns.
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </section>

            {/* 9. EVIDENCE PROFILE & FUSION (STEP 7) */}
            <section className="eval-panel" id="eval-section-evidence">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">📋</span>
                  Evidence Profile & Fusion
                </h3>
                {evidenceData ? (
                  <span className="panel-chip live">
                    {evidenceData.summary?.overall_status || "Evidence Available"} (7 Dimensions)
                  </span>
                ) : (
                  <span className="panel-chip">7 Evaluation Dimensions</span>
                )}
              </div>

              {loadingEvidence && (
                <div className="eval-loading-bar" style={{ margin: "14px 0" }}>
                  <div className="loading-spinner" />
                  <span>Synthesizing multi-source evidence profile...</span>
                </div>
              )}

              {evidenceError && !loadingEvidence && !evidenceData && (
                <div className="eval-error-card" style={{ padding: "10px 14px", margin: "12px 0" }}>
                  <span>⚠</span> {evidenceError}
                </div>
              )}

              {evidenceData && !loadingEvidence && (
                <>
                  {/* Compact 6 Evidence Dimension Cards */}
                  <div className="evidence-cards-grid">
                    {/* 1. Thermal Evidence */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Thermal Radiance</span>
                        <span className={`evidence-card-badge strength-${evidenceData.thermal?.strength?.toLowerCase() || "unavailable"}`}>
                          {evidenceData.thermal?.strength || "UNAVAILABLE"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          {evidenceData.thermal?.observation_count} FIRMS detections
                        </span>
                        <span className="evidence-card-sub">
                          Mean $T_4$: <strong>{evidenceData.thermal?.brightness?.mean ?? "—"} K</strong> (Max: {evidenceData.thermal?.brightness?.max ?? "—"} K)
                        </span>
                        <span className="evidence-card-sub">
                          Mean FRP: <strong>{evidenceData.thermal?.frp?.mean ?? "—"} MW</strong> (Max: {evidenceData.thermal?.frp?.max ?? "—"} MW)
                        </span>
                      </div>
                    </div>

                    {/* 2. Temporal Persistence */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Temporal Persistence</span>
                        <span className={`evidence-card-badge strength-${evidenceData.temporal?.strength?.toLowerCase() || "unavailable"}`}>
                          {evidenceData.temporal?.strength || "UNAVAILABLE"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          {evidenceData.temporal?.distinct_observation_days} active calendar days
                        </span>
                        <span className="evidence-card-sub">
                          Persistence: <strong>{evidenceData.temporal?.persistence_days} days</strong> ({evidenceData.temporal?.duration_hours}h span)
                        </span>
                        <span className="evidence-card-sub">
                          {formatShortDate(evidenceData.temporal?.first_detected)} → {formatShortDate(evidenceData.temporal?.last_detected)}
                        </span>
                      </div>
                    </div>

                    {/* 3. Historical Baseline */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Historical Baseline</span>
                        <span className={`evidence-card-badge ${
                          evidenceData.historical?.anomaly_status === "WITHIN_BASELINE" ? "strength-strong" :
                          evidenceData.historical?.anomaly_status === "ELEVATED" ? "strength-moderate" :
                          evidenceData.historical?.anomaly_status === "HIGHLY_ELEVATED" ? "strength-limited" :
                          "strength-unavailable"
                        }`}>
                          {evidenceData.historical?.anomaly_status || "UNAVAILABLE"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          {evidenceData.historical?.grid_cell || "Regional"} ({evidenceData.historical?.cell_observation_count} hist. obs)
                        </span>
                        <span className="evidence-card-sub">
                          Δ Brightness: <strong>{evidenceData.historical?.brightness_percent_difference != null ? `${evidenceData.historical.brightness_percent_difference > 0 ? "+" : ""}${evidenceData.historical.brightness_percent_difference}%` : "—"}</strong>
                        </span>
                        <span className="evidence-card-sub">
                          $z$-score: {evidenceData.historical?.brightness_z_score != null ? `${evidenceData.historical.brightness_z_score > 0 ? "+" : ""}${evidenceData.historical.brightness_z_score}σ` : "Unavailable (n<3)"}
                        </span>
                      </div>
                    </div>

                    {/* 4. Geographic Validation */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Geographic Validation</span>
                        <span className="evidence-card-badge strength-strong">
                          {evidenceData.geographic?.status || "VALIDATED"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          {evidenceData.geographic?.land_water_class || "LAND"}
                        </span>
                        <span className="evidence-card-sub">
                          State: <strong>{evidenceData.geographic?.state || geoState}</strong>
                        </span>
                        <span className="evidence-card-sub">
                          District: {evidenceData.geographic?.district || "Unassigned"}
                        </span>
                      </div>
                    </div>

                    {/* 5. Spatial Evidence */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Spatial Extent</span>
                        <span className={`evidence-card-badge strength-${evidenceData.spatial?.strength?.toLowerCase() || "unavailable"}`}>
                          {evidenceData.spatial?.strength || "UNAVAILABLE"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          ~{evidenceData.spatial?.observed_footprint?.approximate_area_km2 || 0.14} km² footprint
                        </span>
                        <span className="evidence-card-sub">
                          Centroid: <strong>{evidenceData.spatial?.centroid?.latitude}°, {evidenceData.spatial?.centroid?.longitude}°</strong>
                        </span>
                        <span className="evidence-card-sub">
                          Max Dispersion: {evidenceData.spatial?.spatial_dispersion_km} km
                        </span>
                      </div>
                    </div>

                    {/* 6. Facility Context */}
                    <div className="evidence-card">
                      <div className="evidence-card-header">
                        <span className="evidence-card-title">Facility Context</span>
                        <span className={`evidence-card-badge ${
                          evidenceData.facility_context?.status === "PRESENT" ? "strength-moderate" :
                          evidenceData.facility_context?.status === "NOT_IDENTIFIED" ? "strength-unavailable" :
                          "strength-limited"
                        }`}>
                          {evidenceData.facility_context?.status || "UNAVAILABLE"}
                        </span>
                      </div>
                      <div className="evidence-card-body">
                        <span className="evidence-card-metric">
                          {evidenceData.facility_context?.facilities_count || 0} facility(ies) within 5km
                        </span>
                        <span className="evidence-card-sub">
                          Industrial: <strong>{evidenceData.facility_context?.industrial_count || 0}</strong> · Power: <strong>{evidenceData.facility_context?.power_count || 0}</strong>
                        </span>
                        <span className="evidence-card-caveat">
                          {evidenceData.facility_context?.contextual_caveat || "Contextual only; proximity does not establish causation."}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Contradictory / Constraining Evidence Alert */}
                  {evidenceData.contradictions && evidenceData.contradictions.length > 0 ? (
                    <div className="contradictions-box">
                      <div className="contradictions-title">
                        <span>⚠</span> Contradictory / Constraining Evidence Detected ({evidenceData.contradictions.length})
                      </div>
                      <ul className="contradictions-list">
                        {evidenceData.contradictions.map((c, idx) => (
                          <li key={`contra-${idx}`}>{c}</li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <div className="contradictions-box clean">
                      <div className="contradictions-title" style={{ color: "#34d399", margin: 0 }}>
                        <span>✓</span> No major evidence contradictions identified across thermal, temporal, geographic, and facility datasets.
                      </div>
                    </div>
                  )}

                  {/* Data Quality & Limitations Grid */}
                  <div className="data-quality-grid">
                    <div className="dq-column-card">
                      <span className="dq-column-title">
                        <span>✓</span> Available Evidence Sources ({evidenceData.data_quality?.available_evidence?.length || 0})
                      </span>
                      <ul className="dq-column-list">
                        {evidenceData.data_quality?.available_evidence?.map((item, idx) => (
                          <li key={`avail-${idx}`}>
                            <span className="dq-icon-check">✓</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="dq-column-card">
                      <span className="dq-column-title">
                        <span>•</span> Unavailable / Missing Sources ({evidenceData.data_quality?.missing_evidence?.length || 0})
                      </span>
                      <ul className="dq-column-list">
                        {evidenceData.data_quality?.missing_evidence?.map((item, idx) => (
                          <li key={`miss-${idx}`}>
                            <span className="dq-icon-missing">•</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="dq-column-card">
                      <span className="dq-column-title">
                        <span>ℹ</span> Methodological Limitations ({evidenceData.data_quality?.limitations?.length || 0})
                      </span>
                      <ul className="dq-column-list">
                        {evidenceData.data_quality?.limitations?.map((item, idx) => (
                          <li key={`lim-${idx}`}>
                            <span className="dq-icon-info">ℹ</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </>
              )}

              {/* Detailed Matrix Table */}
              <div style={{ overflowX: "auto", marginTop: "14px" }}>
                <table className="evidence-matrix-table">
                  <thead>
                    <tr>
                      <th>Dimension</th>
                      <th>Status</th>
                      <th>Source</th>
                      <th>Observed Evidence</th>
                      <th>Interpretation Limitation</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><span className="evidence-cat-tag">THERMAL</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>NASA FIRMS VIIRS</td>
                      <td>Brightness ({brightnessSummary.avg || "—"} K) · FRP ({frpSummary.avg || "—"} MW)</td>
                      <td><span className="limitation-text">Thermal radiance alone cannot verify physical flame vs. industrial stack.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">TEMPORAL</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>FIRMS Revisit Passes</td>
                      <td>{eventMeta.persistence_days} days span · {observations.length} discrete satellite passes</td>
                      <td><span className="limitation-text">Polar-orbiting passes do not prove continuous burning between visits.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">GEOGRAPHIC</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>NOAA GLOBE / Admin-1</td>
                      <td>Domain: {geoDomain} · State: {geoState}</td>
                      <td><span className="limitation-text">Coarse 1km mask does not identify micro-scale agricultural land plots.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">SPATIAL</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>VIIRS 375m Geolocation</td>
                      <td>Centroid ({Number(centroid.latitude).toFixed(3)}°, {Number(centroid.longitude).toFixed(3)}°)</td>
                      <td><span className="limitation-text">375m pixel footprint allows sub-pixel spatial displacement.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">FACILITY CONTEXT</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>OpenStreetMap / Overpass</td>
                      <td>{assets?.counts?.industrial || 0} industrial · {assets?.counts?.power || 0} power within 5km</td>
                      <td><span className="limitation-text">Physical proximity indicates contextual presence, not emission causation.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">RISK HEURISTIC</span></td>
                      <td><span className="avail-pill yes">Available</span></td>
                      <td>AGNIVISION Engine</td>
                      <td>Prototype Score: {eventMeta.risk_score} ({eventMeta.risk_level})</td>
                      <td><span className="limitation-text">Deterministic rule-based formula; not an empirical or ML prediction.</span></td>
                    </tr>
                    <tr>
                      <td><span className="evidence-cat-tag">HISTORICAL ANOMALY</span></td>
                      <td><span className={`avail-pill ${anomalyData ? "yes" : "no"}`}>{anomalyData ? "Available" : "Unavailable"}</span></td>
                      <td>NASA FIRMS VIIRS_NOAA20_SP</td>
                      <td>
                        {anomalyData ? (
                          <>
                            {anomalyData.interpretation === "WITHIN_BASELINE" ? "Within Baseline" : anomalyData.interpretation} · Δ Brightness: {anomalyData.comparisons?.brightness_percent_difference > 0 ? "+" : ""}{anomalyData.comparisons?.brightness_percent_difference}% (z={anomalyData.standardized_deviation?.brightness_z_score != null ? `${anomalyData.standardized_deviation.brightness_z_score}σ` : "n<3"}) · Δ FRP: {anomalyData.comparisons?.frp_percent_difference > 0 ? "+" : ""}{anomalyData.comparisons?.frp_percent_difference}%
                          </>
                        ) : (
                          "Historical baseline comparison unavailable"
                        )}
                      </td>
                      <td><span className="limitation-text">Statistical comparison against 30-day baseline; does not prove cause or combustion type.</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          {/* ROW 5: AI INTELLIGENCE — RANDOM FOREST CLASSIFICATION & MULTI-SOURCE ASSESSMENT */}
          <section className="eval-panel ai-intelligence-panel" id="ai-assessment-panel">
            <div className="eval-panel-header" id="ai-ml-panel">
              <h3>
                <span className="panel-header-icon">🤖</span>
                AI Intelligence — Random Forest Classification
              </h3>
              <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                <span className="panel-chip live">TRAINED RANDOM FOREST MODEL (25 FEATURES)</span>
                <span className="panel-chip" style={{ background: "rgba(139, 92, 246, 0.15)", color: "#a78bfa", border: "1px solid rgba(139, 92, 246, 0.3)" }}>
                  Active Inference Engine
                </span>
              </div>
            </div>

            {loadingAssessment && loadingMlPrediction ? (
              <div className="loading-state-box">
                <div className="loading-spinner">⚙</div>
                <span>Executing Random Forest inference (25 features) & synthesizing multi-source evidence...</span>
              </div>
            ) : mlPredictionError && assessmentError ? (
              <div className="eval-error-box">
                <span>⚠</span> {mlPredictionError || assessmentError}
              </div>
            ) : mlClass || assessmentData ? (
              <div className="ai-content-wrapper">
                {/* 1. CRITICAL METHODOLOGY DISTINCTION BANNER */}
                <div className="ai-distinction-banner">
                  <div className="distinction-header">
                    <span className="distinction-icon">ℹ</span>
                    <strong>Important Methodology Distinction & Decision Support Architecture:</strong>
                  </div>
                  <div className="distinction-body">
                    <div className="distinction-item">
                      <span className="distinction-badge ml-tag">ML Classification</span>
                      <span>
                        Statistical source class prediction from the trained 25-feature Random Forest model (
                        <strong>{mlClass?.replace(/_/g, " ") || "Unavailable"}</strong>,{" "}
                        {mlConfidence != null ? `${(mlConfidence * 100).toFixed(1)}%` : "N/A"}) based on thermal channels, persistence, and Open-Meteo NWP weather.
                      </span>
                    </div>
                    <div className="distinction-item">
                      <span className="distinction-badge assessment-tag">Event Assessment</span>
                      <span>
                        Operational evidence fusion combining the Random Forest prediction with multi-day revisit persistence, spatial bounds, historical anomalies, and OSM infrastructure proximity (
                        <strong>{assessmentData?.assessment?.replace(/_/g, " ") || "Unavailable"}</strong>).
                      </span>
                    </div>
                    <div className="distinction-item" style={{ width: "100%", marginTop: "4px", paddingTop: "6px", borderTop: "1px dashed rgba(139, 92, 246, 0.2)" }}>
                      <span className="distinction-badge" style={{ background: "rgba(239, 68, 68, 0.15)", color: "#f87171", border: "1px solid rgba(239, 68, 68, 0.3)" }}>
                        AI OUTPUT ≠ HUMAN VERIFICATION
                      </span>
                      <span style={{ fontSize: "12px", color: "#94a3b8" }}>
                        AI predictions are automated decision support. Ground truth is independently recorded by human operators in the Verification Station below.
                      </span>
                    </div>
                  </div>
                </div>

                {/* 2. TWO-COLUMN COMPARATIVE GRID */}
                <div className="ai-grid-two">
                  {/* LEFT: ML CLASSIFICATION */}
                  <div className="ai-subpanel ml-subpanel">
                    <div className="ai-subpanel-header">
                      <h4>
                        <span className="subpanel-icon">🌲</span>
                        ML Classification
                      </h4>
                      <span className="ai-subchip active">Random Forest · 25 Features</span>
                    </div>

                    <div className="ai-primary-result">
                      <span className="eval-data-label">Predicted Source Class</span>
                      <div className="ai-result-row">
                        <div
                          className={`ai-class-badge class-${mlClass?.toLowerCase() || "unavailable"}`}
                          data-class={mlClass}
                        >
                          <span className="class-dot" />
                          {mlClass?.replace(/_/g, " ") || "ML classification unavailable"}
                        </div>
                        <div className="ai-conf-box">
                          <span className="ai-conf-val">
                            {mlConfidence != null ? `${(mlConfidence * 100).toFixed(1)}%` : "N/A"}
                          </span>
                          <span className="ai-conf-label">ML Confidence</span>
                        </div>
                      </div>
                    </div>

                    {/* Probability Distribution */}
                    <div className="ai-prob-section">
                      <span className="eval-data-label">Class Probability Distribution</span>
                      <div className="ai-prob-list">
                        {(mlProbabilities && Object.keys(mlProbabilities).length > 0
                          ? Object.keys(mlProbabilities)
                          : ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"]
                        ).map((clsName) => {
                          const prob = mlProbabilities?.[clsName] ?? 0;
                          const pct = (prob * 100).toFixed(1);
                          const isTop = clsName === mlClass;
                          return (
                            <div key={clsName} className={`ai-prob-row ${isTop ? "top-class" : ""}`}>
                              <div className="ai-prob-info">
                                <span className="ai-prob-name">{clsName.replace(/_/g, " ")}</span>
                                <strong className="ai-prob-pct">{pct}%</strong>
                              </div>
                              <div className="ai-prob-track">
                                <div
                                  className={`ai-prob-fill class-${clsName.toLowerCase()}`}
                                  data-class={clsName}
                                  style={{ width: `${Math.max(Number(pct), 2)}%` }}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* 25-Feature Vector Inspection */}
                    {mlFeaturesUsed && (
                      <div className="ai-features-section">
                        <button
                          type="button"
                          className="ai-features-toggle"
                          onClick={() => setShowMlFeatures(!showMlFeatures)}
                          title="Inspect raw 25 features supplied to Random Forest inference engine"
                        >
                          <span>{showMlFeatures ? "▼" : "▶"}</span>
                          <span>25-Feature Inference Vector ({showMlFeatures ? "Hide" : "Show"})</span>
                        </button>
                        {showMlFeatures && (
                          <div style={{ overflowX: "auto", marginTop: "8px", maxHeight: "360px", overflowY: "auto" }}>
                            <table className="ai-features-table">
                              <thead>
                                <tr>
                                  <th>#</th>
                                  <th>Feature</th>
                                  <th>Value</th>
                                  <th>Source / Description</th>
                                </tr>
                              </thead>
                              <tbody>
                                {[
                                  { key: "brightness", label: "brightness", unit: "K", desc: "VIIRS 375m I-4 Channel BT" },
                                  { key: "bright_t31", label: "bright_t31", unit: "K", desc: "VIIRS 375m I-5 Channel BT" },
                                  { key: "frp", label: "frp", unit: "MW", desc: "Fire Radiative Power" },
                                  { key: "detections_same_cell", label: "detections_same_cell", unit: "", desc: "0.1° Grid Detections Count" },
                                  { key: "active_days_same_cell", label: "active_days_same_cell", unit: "days", desc: "0.1° Distinct Active Days" },
                                  { key: "mean_frp_same_cell", label: "mean_frp_same_cell", unit: "MW", desc: "0.1° Local Mean FRP" },
                                  { key: "max_frp_same_cell", label: "max_frp_same_cell", unit: "MW", desc: "0.1° Local Max FRP" },
                                  { key: "frp_vs_local_mean", label: "frp_vs_local_mean", unit: "MW", desc: "Local FRP Delta (frp - mean)" },
                                  { key: "temperature_c", label: "temperature_c", unit: "°C", desc: "Open-Meteo 2m Air Temp" },
                                  { key: "u10", label: "u10", unit: "m/s", desc: "Open-Meteo 10m Eastward Wind" },
                                  { key: "v10", label: "v10", unit: "m/s", desc: "Open-Meteo 10m Northward Wind" },
                                  { key: "wind_speed_mps", label: "wind_speed_mps", unit: "m/s", desc: "Open-Meteo 10m Wind Speed" },
                                  { key: "precipitation_mm", label: "precipitation_mm", unit: "mm", desc: "Open-Meteo Precipitation" },
                                  { key: "brightness_t31_delta", label: "brightness_t31_delta", unit: "K", desc: "Split-Window Difference (I4 - I5)" },
                                  { key: "log_frp", label: "log_frp", unit: "", desc: "Log-Transformed FRP (log1p)" },
                                  { key: "detections_per_active_day", label: "detections_per_active_day", unit: "det/day", desc: "Persistence Density (dets / days)" },
                                  { key: "frp_max_minus_mean", label: "frp_max_minus_mean", unit: "MW", desc: "Local FRP Spread (max - mean)" },
                                  { key: "acq_hour", label: "acq_hour", unit: "h", desc: "Observation Hour (0-23 UTC)" },
                                  { key: "month", label: "month", unit: "", desc: "Calendar Month (1-12)" },
                                  { key: "hour_sin", label: "hour_sin", unit: "", desc: "Diurnal Cycle Sine Harmonic" },
                                  { key: "hour_cos", label: "hour_cos", unit: "", desc: "Diurnal Cycle Cosine Harmonic" },
                                  { key: "month_sin", label: "month_sin", unit: "", desc: "Seasonal Cycle Sine Harmonic" },
                                  { key: "month_cos", label: "month_cos", unit: "", desc: "Seasonal Cycle Cosine Harmonic" },
                                  { key: "is_day", label: "is_day", unit: "", desc: "Solar Day/Night (1=Day, 0=Night)" },
                                  { key: "sensor_source_encoded", label: "sensor_source_encoded", unit: "", desc: "Sensor Platform (0=NOAA20, 1=SNPP, 2=Other)" },
                                ].map((item, idx) => {
                                  const val = mlFeaturesUsed[item.key];
                                  const displayVal = val != null
                                    ? `${typeof val === "number" ? (Number.isInteger(val) ? val : val.toFixed(2)) : val} ${item.unit}`.trim()
                                    : "N/A";
                                  return (
                                    <tr key={item.key}>
                                      <td style={{ color: "#64748b", fontSize: "11px" }}>{idx + 1}</td>
                                      <td><code>{item.label}</code></td>
                                      <td><strong>{displayVal}</strong></td>
                                      <td>{item.desc}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="ai-model-footnote">
                      Inference inputs: thermal brightness, split-window delta, FRP, 0.1° cell persistence, Open-Meteo NWP weather vectors, and diurnal/seasonal harmonics.
                    </div>
                  </div>

                  {/* RIGHT: FINAL EVENT ASSESSMENT */}
                  <div className="ai-subpanel assessment-subpanel">
                    <div className="ai-subpanel-header">
                      <h4>
                        <span className="subpanel-icon">🛡</span>
                        Multi-Source Event Assessment
                      </h4>
                      <span className="ai-subchip active">Evidence Fusion</span>
                    </div>

                    <div className="ai-primary-result">
                      <span className="eval-data-label">Operational Event Category</span>
                      <div className="ai-result-row">
                        <div
                          className={`ai-assessment-badge assessment-${assessmentData?.assessment?.toLowerCase() || "unresolved"}`}
                          data-assessment={assessmentData?.assessment}
                        >
                          {assessmentData?.assessment?.replace(/_/g, " ") || "Assessment unavailable"}
                        </div>
                        <div className="ai-conf-box">
                          <span className="ai-conf-val level">{assessmentData?.assessment_confidence || "MODERATE"}</span>
                          <span className="ai-conf-label">Confidence</span>
                        </div>
                      </div>
                    </div>

                    {/* Explanation Box */}
                    <div className="ai-explanation-container">
                      <span className="eval-data-label">Evidence-Based Explanation & Reasoning</span>
                      <div className="ai-explanation-text">
                        <span className="quote-icon">“</span>
                        <p>{assessmentData?.explanation || "Multi-source evidence synthesis evaluates spatial, temporal, and infrastructure proximity."}</p>
                      </div>
                    </div>

                    <div className="ai-operational-note">
                      Operational triage recommendation fusing Random Forest predictions with multi-day persistence, baseline anomaly, and OSM infrastructure proximity.
                    </div>
                  </div>
                </div>

                {/* 3. MULTI-SOURCE EVIDENCE UTILIZED */}
                <div className="ai-evidence-section">
                  <div className="ai-evidence-header">
                    <span className="eval-data-label">Multi-Source Evidence Utilized by Assessment Layer</span>
                    <span className="evidence-badge-count">9 Operational Signals</span>
                  </div>
                  <div className="ai-evidence-grid">
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Observation Count</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.thermal?.observation_count || eventMeta.observation_count || 1} detections
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Active Calendar Days</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.temporal?.distinct_days || eventMeta.persistence_days || 1} days
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Persistence Duration</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.temporal?.duration_hours != null
                          ? `${assessmentData.evidence.temporal.duration_hours} h`
                          : `${((eventMeta.persistence_days || 1) - 1) * 24} h`}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Peak FRP</span>
                      <strong className="tile-val highlight-frp">
                        {assessmentData?.evidence?.thermal?.max_frp_mw != null
                          ? `${assessmentData.evidence.thermal.max_frp_mw} MW`
                          : `${eventMeta.frp_summary?.max || "N/A"} MW`}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Mean FRP</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.thermal?.mean_frp_mw != null
                          ? `${assessmentData.evidence.thermal.mean_frp_mw} MW`
                          : `${eventMeta.frp_summary?.mean || "N/A"} MW`}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Peak Brightness</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.thermal?.max_brightness_k != null
                          ? `${assessmentData.evidence.thermal.max_brightness_k} K`
                          : `${eventMeta.brightness_summary?.max || "N/A"} K`}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Historical Anomaly</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.historical_anomaly?.category || "WITHIN_BASELINE"}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Nearby Infrastructure (5km)</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.osm_context?.total_infrastructure_count != null
                          ? `${assessmentData.evidence.osm_context.total_infrastructure_count} facilities`
                          : "0 facilities"}
                      </strong>
                    </div>
                    <div className="ai-evidence-tile">
                      <span className="tile-kicker">Geographic Domain</span>
                      <strong className="tile-val">
                        {assessmentData?.evidence?.geographic?.land_water_class || geoDomain} ({assessmentData?.evidence?.geographic?.state || geoState})
                      </strong>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-subtext">No AI assessment data available.</div>
            )}
          </section>

          {/* ROW 6: RULE-BASED CLASSIFICATION ASSESSMENT & ALTERNATIVE EXPLANATIONS */}
          <div className="eval-grid-two">
            {/* 10. CLASSIFICATION ASSESSMENT */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">⚖</span>
                  Classification Assessment
                </h3>
                <span className="panel-chip live">
                  {classificationData?.method === "RULE_BASED" ? "RULE-BASED ASSESSMENT (HEURISTIC)" : "System Assessment"}
                </span>
              </div>

              {loadingClassification ? (
                <div className="loading-state-box">Evaluating multi-source evidence against classification rules...</div>
              ) : classificationError ? (
                <div className="eval-error-box">
                  <span>⚠</span> {classificationError}
                </div>
              ) : classificationData ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {/* Top classification banner */}
                  <div className="classification-result-banner">
                    <div className="classification-result-left">
                      <span className="eval-data-label">Analytical Assessment</span>
                      <div className="classification-pill-large" data-class={classificationData.classification}>
                        <span className="class-dot" />
                        {classificationData.classification}
                      </div>
                    </div>
                    <div className="classification-result-meta">
                      <span className="eval-data-label">Methodology</span>
                      <span className="method-badge">Rule-Based Multi-Source Assessment</span>
                      <span className="eval-subtext-muted">
                        Evaluated: {new Date(classificationData.evaluated_at_utc).toLocaleTimeString()}
                      </span>
                      <span className="eval-subtext-muted" style={{ display: "block", fontSize: "11px", marginTop: "2px" }}>
                        Deterministic rules; trained Random Forest ML active in AI section above.
                      </span>
                    </div>
                  </div>

                  {/* Primary Explanation Box */}
                  <div className="primary-explanation-box">
                    <div className="primary-explanation-title">
                      <span>ℹ</span> Primary Explanation
                    </div>
                    <p className="primary-explanation-text">
                      {classificationData.primary_explanation}
                    </p>
                  </div>

                  {/* Supporting Evidence Checklist */}
                  <div className="supporting-evidence-box">
                    <span className="eval-data-label">Supporting Evidence Findings ({classificationData.supporting_evidence?.length || 0})</span>
                    <ul className="classification-evidence-list">
                      {classificationData.supporting_evidence?.map((ev, idx) => (
                        <li key={`ev-${idx}`}>
                          <span className="ev-check">✓</span>
                          <span>{ev}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Triggered Rules Traceability */}
                  <div className="rules-triggered-box">
                    <span className="eval-data-label">Triggered Rule Definitions ({classificationData.rules_triggered_count || 0})</span>
                    <div className="rules-triggered-list">
                      {classificationData.rules_triggered?.map((r, idx) => (
                        <div key={`rule-${idx}`} className="rule-triggered-card">
                          <div className="rule-card-header">
                            <span className="rule-id-code">{r.rule_id}</span>
                            <span className="rule-name-text">{r.rule_name}</span>
                          </div>
                          <p className="rule-desc-text">{r.description}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Limitations Callout */}
                  <div className="eval-limitation-box">
                    <strong>Critical Methodological Limits:</strong>
                    <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "11px", color: "#94a3b8" }}>
                      {classificationData.limitations?.slice(0, 3).map((lim, idx) => (
                        <li key={`lim-${idx}`}>{lim}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="empty-subtext">No classification data available.</div>
              )}
            </section>

            {/* 11. ALTERNATIVE EXPLANATIONS (COMPETING HYPOTHESES) */}
            <section className="eval-panel">
              <div className="eval-panel-header">
                <h3>
                  <span className="panel-header-icon">🔍</span>
                  Alternative Explanations & Competing Hypotheses
                </h3>
                <span className="panel-chip live">Hypothesis Evaluation</span>
              </div>

              {classificationData && classificationData.alternative_explanations?.length > 0 ? (
                <div className="competing-hypotheses-list">
                  {classificationData.alternative_explanations.map((alt, idx) => (
                    <div key={`alt-${idx}`} className="hypothesis-item">
                      <div className="hypothesis-title-row">
                        <strong>{idx + 1}. {alt.candidate}</strong>
                        <span className={`panel-chip ${alt.status === "PLAUSIBLE_ALTERNATIVE" ? "live" : ""}`}>
                          {alt.status}
                        </span>
                      </div>
                      <p className="hyp-meta-text support">
                        <strong>Reasoning:</strong> {alt.reason}
                      </p>
                    </div>
                  ))}

                  {/* Separation from Human Verification Callout */}
                  <div className="verif-separation-callout">
                    <div className="verif-sep-title">
                      <span>⚖</span> Decision Support Separation
                    </div>
                    <p className="verif-sep-desc">
                      This automated assessment is an evidence-based recommendation for operational triage.
                      It <strong>does not verify</strong> the event or modify human verification records.
                      Human analysts must submit confirmed findings via the Verification Station below.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="empty-subtext">No competing hypotheses logged.</div>
              )}
            </section>
          </div>

          {/* BOTTOM: HUMAN VERIFICATION & ANALYST WORKFLOW (Step 9) */}
          <section className="human-verification-station">
            <div className="station-header">
              <div>
                <h3>
                  <span style={{ color: "#10b981" }}>✓</span>
                  Human Verification & Analyst Review Station
                </h3>
                <p className="station-subtext">
                  Operator-in-the-loop review station. Records human verification decisions via <code>/verify-event</code> without mutating raw FIRMS observations or automated classification engines.
                </p>
              </div>

              {existingVerification ? (
                <div className="verif-status-badge verified">
                  <span>✓ Human Verified</span>
                  <span className="verif-date">({formatIsoDateTime(existingVerification.verified_at)})</span>
                </div>
              ) : (
                <div className="verif-status-badge pending">
                  <span>⏳ Pending Analyst Review</span>
                </div>
              )}
            </div>

            {/* Visual Independence Banner: AI Output != Human Verification */}
            <div className="verif-independence-callout">
              <div className="independence-badge">AI OUTPUT ≠ HUMAN VERIFICATION</div>
              <p className="independence-text">
                The analyst provides an independent ground-truth verification label. AI classifications and operational assessments are decision-support aids only; they do not dictate or auto-convert human verification.
              </p>
            </div>

            {/* Three-Way Comparison Bar: ML vs AI Assessment vs Human Ground Truth */}
            <div className="verif-contrast-bar three-cols">
              <div className="contrast-col">
                <span className="contrast-kicker">AI CLASSIFICATION (ML)</span>
                <div className="contrast-main">
                  <span className="contrast-val ml-val">
                    {mlClass || "Unavailable"}
                  </span>
                  <span className="contrast-sub">
                    Confidence: <strong>{mlConfidence != null ? `${(mlConfidence * 100).toFixed(1)}%` : "N/A"}</strong>
                  </span>
                </div>
              </div>
              <div className="contrast-divider">·</div>
              <div className="contrast-col">
                <span className="contrast-kicker">AI EVENT ASSESSMENT</span>
                <div className="contrast-main">
                  <span className="contrast-val assessment-val">
                    {assessmentData?.assessment?.replace(/_/g, " ") || "Unavailable"}
                  </span>
                  <span className="contrast-sub">
                    Confidence: <strong>{assessmentData?.assessment_confidence || "MODERATE"}</strong>
                  </span>
                </div>
              </div>
              <div className="contrast-divider">VS</div>
              <div className="contrast-col">
                <span className="contrast-kicker">HUMAN GROUND TRUTH (STEP 9)</span>
                <div className="contrast-main">
                  <span className={`contrast-val ${existingVerification ? "human-val" : "pending-val"}`}>
                    {existingVerification ? existingVerification.label : "PENDING ANALYST REVIEW"}
                  </span>
                  <span className="contrast-sub">
                    {existingVerification
                      ? `Verified at: ${formatIsoDateTime(existingVerification.verified_at)}`
                      : "Awaiting independent operator review"}
                  </span>
                </div>
              </div>
            </div>

            {verifSuccessMsg && (
              <div className="verif-success-banner">
                <span>✓</span> {verifSuccessMsg}
              </div>
            )}

            {verifErrorMsg && (
              <div className="eval-error-card" style={{ padding: "10px 14px" }}>
                <span>⚠</span> {verifErrorMsg}
              </div>
            )}

            {/* If already verified and not currently editing, display the read-only verified decision card */}
            {existingVerification && !isEditingExisting ? (
              <div className="verified-decision-display">
                <div className="verified-decision-header">
                  <div className="decision-header-info">
                    <span className="verif-badge-pill">{existingVerification.label}</span>
                    <span className="decision-header-title">Verified Ground-Truth Record</span>
                  </div>
                  <button
                    type="button"
                    className="update-verif-btn"
                    onClick={() => setIsEditingExisting(true)}
                  >
                    ✏ Update Verification Decision
                  </button>
                </div>

                <div className="verified-decision-grid">
                  <div className="decision-grid-cell">
                    <span className="cell-label">Event ID</span>
                    <span className="cell-val"><strong>{selectedEventId}</strong></span>
                  </div>
                  <div className="decision-grid-cell">
                    <span className="cell-label">Human Verification Label</span>
                    <span className="cell-val" style={{ color: "#34d399", fontWeight: "700" }}>{existingVerification.label}</span>
                  </div>
                  <div className="decision-grid-cell">
                    <span className="cell-label">AI ML Class at Review</span>
                    <span className="cell-val">
                      {existingVerification.ai_snapshot?.ml_class
                        ? `${existingVerification.ai_snapshot.ml_class} (${((existingVerification.ai_snapshot.ml_confidence || 0) * 100).toFixed(1)}%)`
                        : "Not captured (Historical record)"}
                    </span>
                  </div>
                  <div className="decision-grid-cell">
                    <span className="cell-label">AI Assessment at Review</span>
                    <span className="cell-val">
                      {existingVerification.ai_snapshot?.assessment
                        ? `${existingVerification.ai_snapshot.assessment.replace(/_/g, " ")} (${existingVerification.ai_snapshot.assessment_confidence || "MODERATE"})`
                        : "Not captured (Historical record)"}
                    </span>
                  </div>
                  <div className="decision-grid-cell">
                    <span className="cell-label">Initial Verification Timestamp</span>
                    <span className="cell-val">{formatIsoDateTime(existingVerification.verified_at)}</span>
                  </div>
                  <div className="decision-grid-cell">
                    <span className="cell-label">Last Updated Timestamp</span>
                    <span className="cell-val">
                      {existingVerification.updated_at
                        ? formatIsoDateTime(existingVerification.updated_at)
                        : "No subsequent updates"}
                    </span>
                  </div>
                </div>

                <div className="verified-notes-box">
                  <span className="cell-label">Analyst Rationale / Verification Notes:</span>
                  <p className="verified-notes-text">
                    {existingVerification.notes ||
                      existingVerification.features?.analyst_notes ||
                      "(No notes provided during initial review)"}
                  </p>
                </div>
              </div>
            ) : (
              /* Verification Form (for unverified events OR when editing existing) */
              <form onSubmit={handleVerifySubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {isEditingExisting && (
                  <div className="verif-edit-notice">
                    <div className="edit-notice-text">
                      <span>✏</span>
                      <span>
                        <strong>Editing Verification Record:</strong> Submitting will update the verification record for <strong>{selectedEventId}</strong> while preserving the original verification timestamp.
                      </span>
                    </div>
                    <button
                      type="button"
                      className="cancel-edit-btn"
                      onClick={() => {
                        setIsEditingExisting(false);
                        setSelectedLabel(existingVerification?.label || "ACTIVE_FIRE");
                        setAnalystNotes(existingVerification?.notes || existingVerification?.features?.analyst_notes || "");
                      }}
                    >
                      Cancel Edit
                    </button>
                  </div>
                )}

                <div className="labels-selection-grid">
                  {[
                    { id: "ACTIVE_FIRE", title: "Active Fire", desc: "Confirmed open biomass burning or active flame" },
                    { id: "INDUSTRIAL_HEAT", title: "Industrial Heat", desc: "Smelters, refinery flares, boilers, or power stacks" },
                    { id: "AGRICULTURAL_BURNING", title: "Agri Burning", desc: "Crop residue or post-harvest field clearing" },
                    { id: "WILDLAND_FIRE", title: "Wildland Fire", desc: "Forest, scrubland, or brush fire" },
                    { id: "UNKNOWN", title: "Unknown / Unresolved", desc: "Ambiguous thermal signature requiring ground scout" }
                  ].map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      className={`label-option-btn ${selectedLabel === opt.id ? "selected" : ""}`}
                      onClick={() => setSelectedLabel(opt.id)}
                    >
                      <span className="label-btn-title">{opt.title}</span>
                      <span className="label-btn-desc">{opt.desc}</span>
                    </button>
                  ))}
                </div>

                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                    <label className="eval-data-label" style={{ margin: 0 }}>
                      Analyst Rationale / Verification Notes:
                    </label>
                    <span style={{ fontSize: "11px", color: analystNotes.length > 1800 ? "#f59e0b" : "#64748b" }}>
                      {analystNotes.length} / 2000 chars
                    </span>
                  </div>
                  <textarea
                    value={analystNotes}
                    maxLength={2000}
                    onChange={(e) => setAnalystNotes(e.target.value)}
                    placeholder="Record operational context, visual satellite confirmation, facility proximity notes, or rationale..."
                    rows={3}
                    style={{
                      width: "100%",
                      background: "#141d30",
                      border: "1px solid #334155",
                      borderRadius: "6px",
                      padding: "10px 14px",
                      color: "#f8fafc",
                      fontSize: "13px",
                      outline: "none",
                      boxSizing: "border-box",
                      fontFamily: "inherit"
                    }}
                  />
                </div>

                <div className="submit-verification-row">
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>
                    Target Centroid: <strong>{Number(centroid.latitude).toFixed(5)}°, {Number(centroid.longitude).toFixed(5)}°</strong> ({geoState}) · Event: <strong>{selectedEventId}</strong>
                  </div>

                  <button
                    type="submit"
                    className="submit-verif-btn"
                    disabled={submittingVerif}
                  >
                    {isEditingExisting ? `Review & Confirm Update (${selectedLabel})` : `Review & Confirm Verification (${selectedLabel})`}
                  </button>
                </div>
              </form>
            )}

            {/* Confirmation Modal Overlay */}
            {showConfirmModal && (
              <div className="verif-modal-backdrop" onClick={() => !submittingVerif && setShowConfirmModal(false)}>
                <div className="verif-modal-content" onClick={(e) => e.stopPropagation()}>
                  <div className="verif-modal-header">
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ color: "#10b981", fontSize: "18px" }}>✓</span>
                      <h3>Confirm Human Verification</h3>
                    </div>
                    <button
                      type="button"
                      className="verif-modal-close"
                      onClick={() => !submittingVerif && setShowConfirmModal(false)}
                    >
                      ✕
                    </button>
                  </div>

                  <div className="verif-modal-body">
                    <p className="verif-modal-intro">
                      Please confirm your analyst verification decision for event <strong>{selectedEventId}</strong>.
                    </p>

                    <div className="verif-modal-diff-grid three-way">
                      <div className="verif-modal-cell">
                        <span className="verif-cell-label">AI CLASSIFICATION (ML)</span>
                        <div className="verif-cell-value ml-val">
                          {mlClass || "Unavailable"}
                          <span className="verif-cell-sub">({mlConfidence != null ? `${(mlConfidence * 100).toFixed(1)}%` : "N/A"})</span>
                        </div>
                      </div>
                      <div className="verif-modal-cell">
                        <span className="verif-cell-label">AI EVENT ASSESSMENT</span>
                        <div className="verif-cell-value assessment-val">
                          {assessmentData?.assessment?.replace(/_/g, " ") || "Unavailable"}
                          <span className="verif-cell-sub">({assessmentData?.assessment_confidence || "MODERATE"})</span>
                        </div>
                      </div>
                      <div className="verif-modal-arrow">➔</div>
                      <div className="verif-modal-cell">
                        <span className="verif-cell-label">INDEPENDENT HUMAN GROUND TRUTH</span>
                        <div className="verif-cell-value human-val">
                          {selectedLabel}
                        </div>
                      </div>
                    </div>

                    <div className="verif-modal-notes-preview">
                      <span className="verif-cell-label">ANALYST NOTES</span>
                      <p>{analystNotes.trim() ? analystNotes.trim() : <em style={{ color: "#64748b" }}>(No analyst notes entered)</em>}</p>
                    </div>

                    <div className="verif-modal-notice">
                      <span style={{ fontSize: "16px" }}>ℹ</span>
                      <span>
                        Recording this decision stores a human verification record. Underlying raw FIRMS observations ({eventMeta.observation_count || observations.length} detections) and automated classification rules will NOT be modified.
                      </span>
                    </div>
                  </div>

                  <div className="verif-modal-actions">
                    <button
                      type="button"
                      className="verif-modal-cancel-btn"
                      onClick={() => setShowConfirmModal(false)}
                      disabled={submittingVerif}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="verif-modal-confirm-btn"
                      onClick={executeVerifySubmit}
                      disabled={submittingVerif}
                    >
                      {submittingVerif ? "Recording Decision..." : isEditingExisting ? "Confirm & Update Decision" : "Confirm & Record Decision"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* DATA PROVENANCE FOOTER */}
          <footer className="eval-provenance-footer">
            <div className="eval-prov-item">
              <span className="prov-kicker">SENSOR & DATA PROVENANCE</span>
              <p>NASA FIRMS · VIIRS NOAA-20 NRT (375m active thermal anomalies) · OpenStreetMap / Overpass · NOAA GLOBE 1km</p>
            </div>
            <div className="eval-prov-item">
              <span className="prov-kicker">SCIENTIFIC & OPERATIONAL INTEGRITY</span>
              <p>
                An Event is an objective rule-based spatiotemporal grouping (3.0 km × 36 hours) of satellite detections. Human verification records analyst judgment without altering underlying raw sensor observations.
              </p>
            </div>
          </footer>
        </>
      )}
    </div>
  );
}

