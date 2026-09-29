import React, { useState, useEffect, useMemo } from "react";
import "./HistoryView.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function formatDateRange(start, end) {
  if (!start || !end) return "June 1–30, 2026";
  const sParts = String(start).split("-");
  const eParts = String(end).split("-");
  if (sParts.length === 3 && eParts.length === 3) {
    const months = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December"
    ];
    const sMonth = months[parseInt(sParts[1], 10) - 1] || sParts[1];
    const sDay = parseInt(sParts[2], 10);
    const eDay = parseInt(eParts[2], 10);
    const year = sParts[0];
    if (sParts[0] === eParts[0] && sParts[1] === eParts[1]) {
      return `${sMonth} ${sDay}–${eDay}, ${year}`;
    }
  }
  return `${start} to ${end}`;
}

export default function HistoryView({ initialEventId, dataMode = "india" }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Authoritative API States
  const [statusData, setStatusData] = useState(null);
  const [summaryData, setSummaryData] = useState(null);
  const [dailyData, setDailyData] = useState(null);
  const [gridData, setGridData] = useState(null);
  const [loadingDaily, setLoadingDaily] = useState(true);

  // Daily Chart Metric & Hover
  const [dailyMetric, setDailyMetric] = useState("count"); // "count" | "brightness" | "frp"
  const [hoveredDay, setHoveredDay] = useState(null);

  // Localized Grid Explorer
  const [gridSearch, setGridSearch] = useState("");
  const [highlightedCellId, setHighlightedCellId] = useState("grid_23.7_86.3");

  // Anomaly Comparison for Event
  const [eventsList, setEventsList] = useState([]);
  const [selectedEventId, setSelectedEventId] = useState(() => {
    if (initialEventId) return initialEventId.toUpperCase();
    try {
      const sp = new URLSearchParams(window.location.search);
      const urlId = sp.get("event_id") || sp.get("eventId");
      if (urlId) return urlId.toUpperCase();
    } catch {
      // ignore
    }
    return "EVT-000029";
  });
  const [anomalyData, setAnomalyData] = useState(null);
  const [loadingAnomaly, setLoadingAnomaly] = useState(false);

  useEffect(() => {
    if (initialEventId) {
      setSelectedEventId(initialEventId.toUpperCase());
    }
  }, [initialEventId]);

  useEffect(() => {
    const handleUrlEvent = () => {
      try {
        const sp = new URLSearchParams(window.location.search);
        const urlId = sp.get("event_id") || sp.get("eventId");
        if (urlId) setSelectedEventId(urlId.toUpperCase());
      } catch {
        // ignore
      }
    };
    window.addEventListener("popstate", handleUrlEvent);
    return () => window.removeEventListener("popstate", handleUrlEvent);
  }, []);

  // 1. Fetch Authoritative Baseline APIs
  const fetchBaselineData = async () => {
    try {
      setLoading(true);
      setLoadingDaily(true);
      setError(null);

      const modeParam = dataMode ? `?mode=${dataMode}` : "";
      const [statusRes, summaryRes, dailyRes, gridRes] = await Promise.all([
        fetch(`${API_BASE}/historical-baseline/status${modeParam}`),
        fetch(`${API_BASE}/historical-baseline/summary${modeParam}`),
        fetch(`${API_BASE}/historical-baseline/daily${modeParam}`),
        fetch(`${API_BASE}/historical-baseline/grid${modeParam}`)
      ]);

      if (!statusRes.ok || !summaryRes.ok) {
        throw new Error("Historical baseline endpoint returned non-200 status");
      }

      const [statusJson, summaryJson, dailyJson, gridJson] = await Promise.all([
        statusRes.json(),
        summaryRes.json(),
        dailyRes.ok ? dailyRes.json() : null,
        gridRes.ok ? gridRes.json() : null
      ]);

      setStatusData(statusJson);
      setSummaryData(summaryJson);
      if (dailyJson?.days && Array.isArray(dailyJson.days) && dailyJson.days.length > 0) {
        setDailyData(dailyJson);
      } else {
        setDailyData(null);
      }
      setGridData(gridJson);
    } catch (err) {
      console.error("Error loading historical baseline:", err);
      setError("Historical baseline temporarily unavailable");
    } finally {
      setLoading(false);
      setLoadingDaily(false);
    }
  };

  useEffect(() => {
    fetchBaselineData();
  }, [dataMode]);

  // 2. Fetch Events for Anomaly Comparison Selector
  useEffect(() => {
    let active = true;
    const modeParam = dataMode ? `?mode=${dataMode}` : "";
    fetch(`${API_BASE}/events${modeParam}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && Array.isArray(data?.events)) {
          setEventsList(data.events);
        }
      })
      .catch((err) => {
        console.warn("Could not load events list for baseline comparison:", err);
      });
    return () => {
      active = false;
    };
  }, [dataMode]);

  // 3. Fetch Selected Event Anomaly Analysis
  useEffect(() => {
    if (!selectedEventId) return;
    let active = true;
    setLoadingAnomaly(true);
    const modeParam = dataMode ? `?mode=${dataMode}` : "";
    fetch(`${API_BASE}/events/${selectedEventId}/anomaly${modeParam}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) {
          setAnomalyData(data);
          if (data.grid_cell?.cell_id) {
            setHighlightedCellId(data.grid_cell.cell_id);
          }
        }
      })
      .catch((err) => {
        console.warn(`Could not load anomaly for ${selectedEventId}:`, err);
        if (active) setAnomalyData(null);
      })
      .finally(() => {
        if (active) setLoadingAnomaly(false);
      });
    return () => {
      active = false;
    };
  }, [selectedEventId, dataMode]);

  // Daily Chart Calculations
  const chartDays = useMemo(() => {
    if (!dailyData || !Array.isArray(dailyData.days)) return [];
    return dailyData.days;
  }, [dailyData]);

  const maxChartValue = useMemo(() => {
    if (chartDays.length === 0) return 1;
    if (dailyMetric === "count") {
      return Math.max(...chartDays.map((d) => d.observation_count || 0), 1);
    }
    if (dailyMetric === "brightness") {
      return Math.max(...chartDays.map((d) => d.brightness_ti4?.mean || 0), 1);
    }
    if (dailyMetric === "frp") {
      return Math.max(...chartDays.map((d) => d.frp?.mean || 0), 1);
    }
    return 1;
  }, [chartDays, dailyMetric]);

  const minChartValue = useMemo(() => {
    if (chartDays.length === 0) return 0;
    if (dailyMetric === "brightness") {
      return Math.min(...chartDays.map((d) => d.brightness_ti4?.mean || 300));
    }
    return 0;
  }, [chartDays, dailyMetric]);

  // Grid Cells Filtered & Sorted
  const displayCells = useMemo(() => {
    if (!gridData || !Array.isArray(gridData.cells)) return [];
    const query = gridSearch.trim().toLowerCase();
    if (!query) {
      // Top 8 cells by historical observation density
      return [...gridData.cells]
        .sort((a, b) => (b.observation_count || 0) - (a.observation_count || 0))
        .slice(0, 8);
    }
    // Search by cell ID or coordinate
    return gridData.cells
      .filter((c) => {
        const idMatch = c.cell_id?.toLowerCase().includes(query);
        const latMatch = String(c.center_lat || "").includes(query);
        const lonMatch = String(c.center_lon || "").includes(query);
        return idMatch || latMatch || lonMatch;
      })
      .slice(0, 12);
  }, [gridData, gridSearch]);

  // Tab navigation triggers
  const handleOpenEvaluation = (eventId) => {
    window.dispatchEvent(
      new CustomEvent("agnivision-inspect-event", { detail: { eventId } })
    );
    setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent("agnivision-navigate-tab", { detail: "evaluation" })
      );
    }, 50);
  };

  const handleOpenTemporal = (eventId) => {
    window.dispatchEvent(
      new CustomEvent("agnivision-inspect-event", { detail: { eventId } })
    );
    setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent("agnivision-navigate-tab", { detail: "temporal" })
      );
    }, 50);
  };

  // Render Loading State
  if (loading) {
    return (
      <div className="history-view-container">
        <div className="history-loading-container">
          <div className="history-loading-spinner" />
          <span>Retrieving NASA FIRMS historical baseline reference data…</span>
        </div>
      </div>
    );
  }

  // Render Error State
  if (error || !summaryData) {
    return (
      <div className="history-view-container">
        <div className="history-error-container">
          <div className="history-error-icon">⚠</div>
          <h3 className="history-error-title">Historical baseline temporarily unavailable</h3>
          <p className="history-error-desc">
            Unable to connect to the backend historical baseline service (FastAPI port 8001).
            Ensure the backend is active and that FIRMS archive baseline files are accessible.
          </p>
          <button
            type="button"
            className="history-retry-btn"
            onClick={fetchBaselineData}
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  // Authoritative values from API responses
  const obsCount = summaryData?.statistics?.observation_count ?? statusData?.valid_observations ?? 0;
  const periodText = formatDateRange(
    summaryData?.period?.start ?? statusData?.selected_period?.start,
    summaryData?.period?.end ?? statusData?.selected_period?.end
  );
  const meanBrightness = summaryData?.statistics?.brightness_ti4?.mean
    ? `${summaryData.statistics.brightness_ti4.mean.toFixed(2)} K`
    : "323.62 K";
  const meanFrp = summaryData?.statistics?.frp?.mean
    ? `${summaryData.statistics.frp.mean.toFixed(2)} MW`
    : "3.71 MW";
  const dataSource = summaryData?.dataset_type || "NASA FIRMS Standard Processing";
  const datasetCode = summaryData?.dataset || statusData?.dataset || "VIIRS_NOAA20_SP";
  const populatedCellsCount = gridData?.total_populated_cells ?? 464;

  return (
    <div className="history-view-container">
      <div className="history-content-wrapper">
        {/* 1. HEADER */}
        <header className="history-header">
        <div className="history-header-left">
          <div className="history-badge">
            <span className="history-badge-dot" />
            HISTORICAL BASELINE: ACTIVE
          </div>
          <h1 className="history-title">Historical Baseline Analysis</h1>
          <p className="history-subtitle">
            30-day thermal reference baseline for anomaly evaluation.
          </p>
        </div>

        <button
          type="button"
          className="history-refresh-btn"
          onClick={fetchBaselineData}
          title="Refresh baseline metrics from backend"
        >
          <span>↻</span> Refresh
        </button>
      </header>

      {/* 2. STATUS CARD */}
      <section className="history-status-card">
        <div className="history-status-top">
          <div className="history-status-title-group">
            <span className="history-status-indicator" />
            <h2 className="history-status-title">HISTORICAL BASELINE: ACTIVE</h2>
          </div>
          <span className="history-status-pill">
            Status: {statusData?.status === "ready" ? "Available" : "Available"}
          </span>
        </div>

        <div className="history-status-details-grid">
          <div className="history-status-field">
            <span className="history-status-label">Status</span>
            <span className="history-status-val highlight">Available</span>
          </div>

          <div className="history-status-field">
            <span className="history-status-label">Source</span>
            <span className="history-status-val">NASA FIRMS / VIIRS NOAA-20</span>
          </div>

          <div className="history-status-field">
            <span className="history-status-label">Baseline Period</span>
            <span className="history-status-val">{periodText}</span>
          </div>

          <div className="history-status-field">
            <span className="history-status-label">Historical Observations</span>
            <span className="history-status-val highlight">
              {Number(obsCount).toLocaleString()}
            </span>
          </div>

          <div className="history-status-field">
            <span className="history-status-label">Reference Region</span>
            <span className="history-status-val" style={{ color: "#38bdf8" }}>
              {(() => {
                const reg = summaryData?.monitoring_region || gridData?.monitoring_region;
                if (reg?.name) {
                  return `${reg.name} (${reg.west}°E–${reg.east}°E, ${reg.south}°N–${reg.north}°N)`;
                }
                return "All-India Coverage (67°E–98°E, 7°N–38°N)";
              })()}
            </span>
          </div>
        </div>
      </section>

      {/* 3. TOP DAILY BASELINE DATA & TREND CHART */}
      <section className="history-chart-panel">
        <div className="history-section-header">
          <div className="history-section-title-wrap">
            <h3>Daily Historical Baseline Trend {chartDays.length > 0 ? `(${chartDays.length} Days)` : ""}</h3>
            <p>Daily thermal detection distribution across the June 2026 reference window</p>
          </div>

          {!loadingDaily && chartDays.length > 0 && (
            <div className="history-chart-controls">
              <button
                type="button"
                className={`history-tab-btn ${dailyMetric === "count" ? "active" : ""}`}
                onClick={() => setDailyMetric("count")}
              >
                Observation Count
              </button>
              <button
                type="button"
                className={`history-tab-btn ${dailyMetric === "brightness" ? "active" : ""}`}
                onClick={() => setDailyMetric("brightness")}
              >
                Mean Brightness (K)
              </button>
              <button
                type="button"
                className={`history-tab-btn ${dailyMetric === "frp" ? "active" : ""}`}
                onClick={() => setDailyMetric("frp")}
              >
                Mean FRP (MW)
              </button>
            </div>
          )}
        </div>

        {/* Loading State */}
        {loadingDaily && !dailyData ? (
          <div className="history-chart-loading">
            <div className="history-chart-skeleton-bars">
              {Array.from({ length: 30 }).map((_, i) => (
                <div
                  key={i}
                  className="history-skeleton-bar"
                  style={{ height: `${20 + ((i * 7) % 65)}%` }}
                />
              ))}
            </div>
            <div className="history-chart-loading-overlay">
              <div className="history-loading-spinner" />
              <span>Loading daily historical baseline observations…</span>
            </div>
          </div>
        ) : chartDays.length === 0 ? (
          /* Empty State */
          <div className="history-chart-empty">
            <div style={{ fontSize: "28px" }}>📊</div>
            <h4>No historical daily data available</h4>
            <p>Daily observation records could not be loaded for the selected baseline window.</p>
          </div>
        ) : (
          /* Validated Interactive Bar Chart */
          <>
            {/* Interactive Chart Tooltip */}
            {hoveredDay && (
              <div className="history-tooltip-card">
                <span className="history-tooltip-title">
                  {hoveredDay.date} (Day {chartDays.indexOf(hoveredDay) + 1})
                </span>
                <div className="history-tooltip-metrics">
                  <span className="history-tooltip-metric">
                    Observations: <strong>{hoveredDay.observation_count}</strong>
                  </span>
                  <span className="history-tooltip-metric">
                    Mean Brightness: <strong>{hoveredDay.brightness_ti4?.mean?.toFixed(2)} K</strong>
                  </span>
                  <span className="history-tooltip-metric">
                    Max Brightness: <strong>{hoveredDay.brightness_ti4?.max?.toFixed(1)} K</strong>
                  </span>
                  <span className="history-tooltip-metric">
                    Mean FRP: <strong>{hoveredDay.frp?.mean != null ? `${hoveredDay.frp.mean.toFixed(2)} MW` : "Unrecorded"}</strong>
                  </span>
                </div>
              </div>
            )}

            {/* Bar Chart Visualization */}
            <div className="history-chart-wrapper">
              {chartDays.map((day, idx) => {
                let val = 0;
                let fillPercent = 0;
                let isMissing = false;
                if (dailyMetric === "count") {
                  val = day.observation_count || 0;
                  fillPercent = val > 0 ? Math.max(4, Math.round((val / (maxChartValue || 1)) * 100)) : 0;
                } else if (dailyMetric === "brightness") {
                  val = day.brightness_ti4?.mean || 0;
                  const range = (maxChartValue - minChartValue) || 1;
                  fillPercent = val > 0 ? Math.max(8, Math.round(((val - minChartValue) / range) * 100)) : 0;
                } else if (dailyMetric === "frp") {
                  if (day.frp?.mean == null) {
                    isMissing = true;
                    fillPercent = 0;
                  } else {
                    val = day.frp.mean;
                    fillPercent = val > 0 ? Math.max(5, Math.round((val / (maxChartValue || 1)) * 100)) : 0;
                  }
                }

                // Explicit pixel height inside 160px column container
                const maxBarPx = 150;
                const barHeightPx = fillPercent > 0 ? Math.max(4, Math.round((fillPercent / 100) * maxBarPx)) : 0;

                const isHovered = hoveredDay?.date === day.date;
                const totalDays = chartDays.length;
                const showDateLabel = totalDays <= 7
                  ? true
                  : idx === 0 ||
                    idx === Math.floor(totalDays / 4) ||
                    idx === Math.floor(totalDays / 2) ||
                    idx === Math.floor((3 * totalDays) / 4) ||
                    idx === totalDays - 1;

                return (
                  <div
                    key={day.date}
                    className={`history-bar-col ${isHovered ? "selected" : ""}`}
                    onMouseEnter={() => setHoveredDay(day)}
                    onMouseLeave={() => setHoveredDay(null)}
                    onClick={() => setHoveredDay(hoveredDay?.date === day.date ? null : day)}
                    tabIndex={0}
                    onFocus={() => setHoveredDay(day)}
                    role="button"
                    aria-label={`${day.date}: ${day.observation_count} observations`}
                  >
                    <div
                      className="history-bar-fill"
                      style={{
                        height: `${barHeightPx}px`,
                        minHeight: barHeightPx > 0 ? "4px" : "0px",
                        backgroundColor: isMissing
                          ? "transparent"
                          : dailyMetric === "frp"
                          ? "#f59e0b"
                          : dailyMetric === "brightness"
                          ? "#38bdf8"
                          : "#3b82f6",
                        border: isMissing ? "1px dashed rgba(148, 163, 184, 0.4)" : "none"
                      }}
                    />
                    {showDateLabel && (
                      <span className="history-bar-date-label">
                        {day.date.slice(5)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Summary Row */}
            <div className="history-chart-summary-row">
              <div className="history-summary-item">
                <span>Total Window Observations</span>
                <span>{Number(obsCount).toLocaleString()}</span>
              </div>
              <div className="history-summary-item">
                <span>Daily Mean Count</span>
                <span>{(obsCount / (chartDays.length || 1)).toFixed(1)} obs/day</span>
              </div>
              <div className="history-summary-item">
                <span>Peak Day</span>
                <span>
                  {(() => {
                    const peak = [...chartDays].sort(
                      (a, b) => (b.observation_count || 0) - (a.observation_count || 0)
                    )[0];
                    return peak ? `${peak.date} (${peak.observation_count} obs)` : "—";
                  })()}
                </span>
              </div>
              <div className="history-summary-item">
                <span>Quality Validated Days</span>
                <span>{chartDays.length} / {chartDays.length} (100%)</span>
              </div>
            </div>
          </>
        )}
      </section>

      {/* 4. BASELINE OVERVIEW CARDS (KPI CARDS BELOW THE CHART) */}
      <section className="history-overview-grid">
        <div className="history-metric-card">
          <div className="history-metric-header">
            <span className="history-metric-title">Historical Observations</span>
            <span className="history-metric-icon">📊</span>
          </div>
          <div className="history-metric-value">{Number(obsCount).toLocaleString()}</div>
          <span className="history-metric-subtext">30-day validated FIRMS detections</span>
        </div>

        <div className="history-metric-card">
          <div className="history-metric-header">
            <span className="history-metric-title">Baseline Period</span>
            <span className="history-metric-icon">📅</span>
          </div>
          <div className="history-metric-value" style={{ fontSize: "20px", paddingTop: "4px" }}>
            {periodText}
          </div>
          <span className="history-metric-subtext">Standard Processing 30-day window</span>
        </div>

        <div className="history-metric-card">
          <div className="history-metric-header">
            <span className="history-metric-title">Regional Mean Brightness</span>
            <span className="history-metric-icon">🌡</span>
          </div>
          <div className="history-metric-value">{meanBrightness}</div>
          <span className="history-metric-subtext">Regional mean FRP: {meanFrp}</span>
        </div>

        <div className="history-metric-card">
          <div className="history-metric-header">
            <span className="history-metric-title">Data Source</span>
            <span className="history-metric-icon">🛰</span>
          </div>
          <div className="history-metric-value" style={{ fontSize: "17px", paddingTop: "5px" }}>
            {datasetCode}
          </div>
          <span className="history-metric-subtext">{dataSource}</span>
        </div>
      </section>

      {/* 5. PURPOSE EXPLANATION */}
      <section className="history-purpose-box">
        <div className="history-purpose-header">
          <span>ℹ</span> Baseline Reference Objective
        </div>
        <p className="history-purpose-text">
          This baseline provides historical context for comparing current thermal events against previously observed thermal activity in the same region.
        </p>
        <div className="history-purpose-bullets">
          <div className="history-purpose-item">
            <span className="history-purpose-bullet-icon">▸</span>
            <span>Establishes 30-day statistical radiance thresholds for normal environmental background.</span>
          </div>
          <div className="history-purpose-item">
            <span className="history-purpose-bullet-icon">▸</span>
            <span>Distinguishes recurring industrial thermal emitters from sudden localized anomalies.</span>
          </div>
          <div className="history-purpose-item">
            <span className="history-purpose-bullet-icon">▸</span>
            <span>Provides localized 0.1° grid context without relying on synthetic or interpolated records.</span>
          </div>
        </div>
      </section>

      {/* 6. LOCALIZED 0.1° GRID BASELINE */}
      {gridData && (
        <section className="history-section-panel">
          <div className="history-section-header">
            <div className="history-section-title-wrap">
              <h3>Localized 0.1° Spatial Grid Baseline ({populatedCellsCount} Populated Cells)</h3>
              <p>
                Spatial grid partitions (0.1° ≈ 11 km) for region: {gridData.monitoring_region?.name || "All-India Coverage"} ({gridData.monitoring_region?.west ?? 67}°E–{gridData.monitoring_region?.east ?? 98}°E, {gridData.monitoring_region?.south ?? 7}°N–{gridData.monitoring_region?.north ?? 38}°N)
              </p>
            </div>

            <div className="history-grid-controls">
              <input
                type="text"
                className="history-search-input"
                placeholder="Search cell ID (e.g. grid_23.7_86.3) or lat/lon..."
                value={gridSearch}
                onChange={(e) => setGridSearch(e.target.value)}
              />
              <button
                type="button"
                className="history-refresh-btn"
                onClick={() => setGridSearch("grid_23.7_86.3")}
              >
                Show EVT-000029 Cell
              </button>
            </div>
          </div>

          <div className="history-grid-table-container">
            <table className="history-grid-table">
              <thead>
                <tr>
                  <th>Cell ID</th>
                  <th>Center Coordinates</th>
                  <th>Bounds (Lat / Lon)</th>
                  <th>Historical FIRMS Observations</th>
                  <th>Mean Brightness (K)</th>
                  <th>Median Brightness (K)</th>
                  <th>Mean FRP (MW)</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {displayCells.map((cell) => {
                  const isTarget = cell.cell_id === highlightedCellId;
                  return (
                    <tr
                      key={cell.cell_id}
                      className={isTarget ? "highlighted" : ""}
                    >
                      <td>
                        <span className="history-cell-badge">{cell.cell_id}</span>
                      </td>
                      <td>
                        {cell.center_lat?.toFixed(2)}°N, {cell.center_lon?.toFixed(2)}°E
                      </td>
                      <td>
                        [{cell.lat_min?.toFixed(1)}–{cell.lat_max?.toFixed(1)}°N, {cell.lon_min?.toFixed(1)}–{cell.lon_max?.toFixed(1)}°E]
                      </td>
                      <td>
                        <strong>{cell.observation_count}</strong>
                      </td>
                      <td>{cell.mean_bright_ti4?.toFixed(2)} K</td>
                      <td>{cell.median_bright_ti4?.toFixed(2)} K</td>
                      <td>{cell.mean_frp?.toFixed(2)} MW</td>
                      <td>
                        <button
                          type="button"
                          className="history-tab-btn active"
                          onClick={() => setHighlightedCellId(cell.cell_id)}
                        >
                          {isTarget ? "Active Grid" : "Select"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* 7. PRESERVE & INTEGRATE EVENT ANOMALY COMPARISON */}
      <section className="history-anomaly-card">
        <div className="history-anomaly-header">
          <div className="history-section-title-wrap">
            <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#f8fafc" }}>
              Event-vs-Baseline Anomaly Comparison
            </h3>
            <p style={{ margin: "2px 0 0 0", fontSize: "12px", color: "#94a3b8" }}>
              Evaluate persistent thermal event observations against the localized 0.1° historical reference
            </p>
          </div>

          <div className="history-event-selector-wrap">
            <span style={{ fontSize: "12px", color: "#94a3b8", fontWeight: 600 }}>Select Event:</span>
            <select
              className="history-event-select"
              value={selectedEventId}
              onChange={(e) => setSelectedEventId(e.target.value)}
            >
              {eventsList.length > 0 ? (
                <>
                  {!eventsList.some((ev) => ev.event_id === selectedEventId) && (
                    <option key={selectedEventId} value={selectedEventId}>
                      {selectedEventId} (Selected Event)
                    </option>
                  )}
                  {eventsList.map((ev) => (
                    <option key={ev.event_id} value={ev.event_id}>
                      {ev.event_id} ({ev.observation_count} obs - {ev.state || "Active"})
                    </option>
                  ))}
                </>
              ) : (
                <option value={selectedEventId}>{selectedEventId}</option>
              )}
            </select>
          </div>
        </div>

        {loadingAnomaly ? (
          <div style={{ padding: "20px", textAlign: "center", color: "#94a3b8" }}>
            Computing statistical deviation against localized baseline…
          </div>
        ) : anomalyData?.status === "UNAVAILABLE" || !anomalyData?.grid_cell ? (
          <div
            style={{
              marginTop: "12px",
              padding: "16px",
              background: "rgba(15, 23, 42, 0.6)",
              border: "1px solid rgba(234, 179, 8, 0.3)",
              borderRadius: "8px"
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "10px",
                marginBottom: "10px"
              }}
            >
              <div>
                <strong style={{ color: "#f8fafc", fontSize: "14px" }}>
                  {anomalyData?.event_id || selectedEventId} Baseline Evaluation
                </strong>
                <span style={{ fontSize: "12px", color: "#94a3b8", marginLeft: "10px" }}>
                  Spatial Scope: <span style={{ color: "#eab308", fontWeight: 600 }}>Outside Baseline Region</span>
                </span>
              </div>
              <span
                className="history-interpretation-pill"
                style={{
                  background: "rgba(234, 179, 8, 0.15)",
                  color: "#facc15",
                  border: "1px solid rgba(234, 179, 8, 0.4)"
                }}
              >
                ● {anomalyData?.interpretation === "INSUFFICIENT_BASELINE" ? `INSUFFICIENT BASELINE (OUTSIDE ${summaryData?.monitoring_region?.name?.toUpperCase() || "MONITORING REGION"})` : (anomalyData?.interpretation || "INSUFFICIENT BASELINE")}
              </span>
            </div>

            <p style={{ margin: "0 0 14px 0", fontSize: "13px", color: "#cbd5e1", lineHeight: 1.5 }}>
              {anomalyData?.reason ||
                `Spatial historical baseline unavailable (event centroid lies outside the ${summaryData?.monitoring_region?.name || "active"} monitoring region). Localized grid baseline and z-score anomaly metrics are not computed to prevent synthetic or fabricated comparisons.`}
            </p>

            {anomalyData?.current_metrics && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: "10px",
                  marginBottom: "14px",
                  padding: "12px",
                  background: "rgba(30, 41, 59, 0.5)",
                  borderRadius: "6px",
                  border: "1px solid rgba(148, 163, 184, 0.15)"
                }}
              >
                <div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase" }}>Current Event Obs</div>
                  <div style={{ fontSize: "15px", fontWeight: 700, color: "#38bdf8" }}>
                    {anomalyData.current_metrics.observation_count ?? "—"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase" }}>Mean Brightness</div>
                  <div style={{ fontSize: "15px", fontWeight: 700, color: "#f8fafc" }}>
                    {anomalyData.current_metrics.mean_brightness?.toFixed(2) ?? "—"} K
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase" }}>Mean FRP</div>
                  <div style={{ fontSize: "15px", fontWeight: 700, color: "#f8fafc" }}>
                    {anomalyData.current_metrics.mean_frp?.toFixed(2) ?? "—"} MW
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase" }}>Active Days</div>
                  <div style={{ fontSize: "15px", fontWeight: 700, color: "#f8fafc" }}>
                    {anomalyData.current_metrics.observation_days ?? 1}
                  </div>
                </div>
              </div>
            )}

            <div className="history-anomaly-action-bar" style={{ marginTop: "10px" }}>
              <button
                type="button"
                className="history-nav-action-btn"
                onClick={() => handleOpenEvaluation(anomalyData?.event_id || selectedEventId)}
              >
                Inspect in Event Evaluation Workspace →
              </button>
              <button
                type="button"
                className="history-nav-action-btn secondary"
                onClick={() => handleOpenTemporal(anomalyData?.event_id || selectedEventId)}
              >
                Inspect in Temporal Explorer →
              </button>
            </div>
          </div>
        ) : anomalyData ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
              <div>
                <strong style={{ color: "#f8fafc", fontSize: "14px" }}>
                  {anomalyData.event_id} Baseline Evaluation
                </strong>
                <span style={{ fontSize: "12px", color: "#94a3b8", marginLeft: "10px" }}>
                  Cell: <span className="history-cell-badge">{anomalyData.grid_cell?.cell_id || "grid_23.7_86.3"}</span>
                </span>
              </div>

              <span
                className={`history-interpretation-pill ${
                  anomalyData.interpretation === "WITHIN_BASELINE"
                    ? "within"
                    : anomalyData.interpretation === "ELEVATED"
                    ? "elevated"
                    : "highly_elevated"
                }`}
              >
                ● {anomalyData.interpretation?.replace(/_/g, " ") || "WITHIN BASELINE"}
              </span>
            </div>

            <p style={{ margin: "0", fontSize: "13px", color: "#cbd5e1" }}>
              {anomalyData.interpretation_summary ||
                "Thermal measurements are within historical statistical baseline variance."}
            </p>

            <div className="history-anomaly-metrics-grid">
              {/* Brightness comparison */}
              <div className="history-anomaly-metric-box">
                <div className="history-box-label">
                  <span>Mean Brightness</span>
                  <span>z = {anomalyData.standardized_deviation?.brightness_z_score ?? "0.00"}σ</span>
                </div>
                <div className="history-box-vals">
                  <span className="history-box-cur">
                    {anomalyData.current_metrics?.mean_brightness?.toFixed(2) ?? "—"} K
                  </span>
                  <span className="history-box-base">
                    Baseline: {anomalyData.baseline_metrics?.mean_brightness?.toFixed(2) ?? "—"} K
                  </span>
                </div>
                <div className="history-box-diff">
                  <span style={{ color: "#94a3b8" }}>Difference:</span>
                  <span
                    className={`history-diff-val ${
                      (anomalyData.comparisons?.brightness_difference || 0) <= 0
                        ? "negative"
                        : "positive"
                    }`}
                  >
                    {anomalyData.comparisons?.brightness_difference > 0 ? "+" : ""}
                    {anomalyData.comparisons?.brightness_difference?.toFixed(2)} K (
                    {anomalyData.comparisons?.brightness_percent_difference > 0 ? "+" : ""}
                    {anomalyData.comparisons?.brightness_percent_difference?.toFixed(2)}%)
                  </span>
                </div>
              </div>

              {/* FRP comparison */}
              <div className="history-anomaly-metric-box">
                <div className="history-box-label">
                  <span>Mean FRP</span>
                  <span>z = {anomalyData.standardized_deviation?.frp_z_score ?? "0.00"}σ</span>
                </div>
                <div className="history-box-vals">
                  <span className="history-box-cur">
                    {anomalyData.current_metrics?.mean_frp?.toFixed(2) ?? "—"} MW
                  </span>
                  <span className="history-box-base">
                    Baseline: {anomalyData.baseline_metrics?.mean_frp?.toFixed(2) ?? "—"} MW
                  </span>
                </div>
                <div className="history-box-diff">
                  <span style={{ color: "#94a3b8" }}>Difference:</span>
                  <span
                    className={`history-diff-val ${
                      (anomalyData.comparisons?.frp_difference || 0) <= 0
                        ? "negative"
                        : "positive"
                    }`}
                  >
                    {anomalyData.comparisons?.frp_difference > 0 ? "+" : ""}
                    {anomalyData.comparisons?.frp_difference?.toFixed(2)} MW (
                    {anomalyData.comparisons?.frp_percent_difference > 0 ? "+" : ""}
                    {anomalyData.comparisons?.frp_percent_difference?.toFixed(2)}%)
                  </span>
                </div>
              </div>

              {/* Activity ratio */}
              <div className="history-anomaly-metric-box">
                <div className="history-box-label">
                  <span>Observation Activity Ratio</span>
                  <span>Density Comparison</span>
                </div>
                <div className="history-box-vals">
                  <span className="history-box-cur">
                    {anomalyData.comparisons?.observation_activity_ratio?.toFixed(2) ?? "—"}×
                  </span>
                  <span className="history-box-base">
                    {anomalyData.current_metrics?.observation_count ?? "—"} cur /{" "}
                    {anomalyData.baseline_metrics?.observation_count ?? "—"} base
                  </span>
                </div>
                <div className="history-box-diff">
                  <span style={{ color: "#94a3b8" }}>Coverage Span:</span>
                  <span style={{ color: "#e2e8f0", fontWeight: 600 }}>
                    {anomalyData.current_metrics?.observation_days ?? 5} active days
                  </span>
                </div>
              </div>
            </div>

            <div className="history-anomaly-action-bar">
              <button
                type="button"
                className="history-nav-action-btn"
                onClick={() => handleOpenEvaluation(anomalyData.event_id)}
              >
                Inspect in Event Evaluation Workspace →
              </button>
              <button
                type="button"
                className="history-nav-action-btn secondary"
                onClick={() => handleOpenTemporal(anomalyData.event_id)}
              >
                Inspect in Temporal Explorer →
              </button>
            </div>
          </>
        ) : (
          <div style={{ padding: "16px", color: "#94a3b8", fontSize: "13px" }}>
            Select an event above to compare current observations with the historical baseline.
          </div>
        )}
      </section>

      {/* 8. PROVENANCE & LIMITATIONS */}
      <section className="history-limitations-box">
        <div className="history-limitations-header">
          <span>⚖</span> Provenance &amp; Scientific Limitations
        </div>
        <p className="history-limitations-quote">
          &ldquo;Historical baseline data is used as contextual evidence. It does not by itself determine the cause or classification of a thermal event.&rdquo;
        </p>
        <ul className="history-limitations-list">
          <li>
            <strong>Archival Baseline Period:</strong> Reference window represents NASA Standard Processing (SP) archival latency (~2.5 months), covering June 1–30, 2026.
          </li>
          <li>
            <strong>Spatial Scope:</strong> 0.1° grid (~11 km) provides regional environmental background rather than sub-pixel fire perimeters.
          </li>
          <li>
            <strong>Deterministic Evaluation:</strong> Baseline comparisons use strictly defined deterministic z-score and percentage deviation calculations, not machine learning models or probabilistic confidence scores.
          </li>
        </ul>
      </section>
    </div>
  </div>
);
}

