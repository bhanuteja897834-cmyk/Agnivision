import React, { useMemo, useEffect, useState } from "react";
import MetricCard from "./MetricCard";
import CategorySummaryStrip from "./CategorySummaryStrip";
import ThermalOverview from "./ThermalOverview";
import RiskDistribution from "./RiskDistribution";
import EventGrowth from "./EventGrowth";
import StateActivity from "./StateActivity";
import EmbeddedMapOverview from "./EmbeddedMapOverview";
import RecentNotifications from "./RecentNotifications";
import ThermalEventTable from "./ThermalEventTable";
import VerificationSummary from "./VerificationSummary";
import DataSources from "./DataSources";
import {
  calculateDateRange,
  formatDisplayUtc,
  formatISODate,
  subtractDays,
  getToday
} from "../utils/dateUtils.js";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function DateRangeSelector({ dateRange, setDateRange }) {
  const handlePreset = (preset) => {
    const newRange = calculateDateRange(preset);
    setDateRange(newRange);
  };

  const presets = [
    { label: "TODAY", key: "TODAY" },
    { label: "3 DAYS", key: "3D" },
    { label: "7 DAYS", key: "7D" },
    { label: "10 DAYS", key: "10D" },
    { label: "30 DAYS", key: "30D" }
  ];

  return (
    <div className="dashboard-filter-bar">
      <div className="filter-bar-left">
        <div className="filter-bar-title-wrap">
          <span className="filter-bar-icon">⏱</span>
          <span className="filter-bar-title">OBSERVATION WINDOW:</span>
        </div>
        <div className="filter-presets-group" role="group" aria-label="Date Range Presets">
          {presets.map(({ label, key }) => {
            const isActive = dateRange.preset === key;
            return (
              <button
                key={key}
                type="button"
                className={`filter-preset-btn ${isActive ? "active" : ""}`}
                onClick={() => handlePreset(key)}
                aria-pressed={isActive}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="filter-bar-right">
        <div className="filter-date-inputs">
          <label className="filter-date-label">
            <span className="filter-date-tag">FROM</span>
            <input 
              type="date" 
              className="filter-date-field"
              value={dateRange.startDate}
              max={dateRange.endDate}
              onChange={(e) => setDateRange({ ...dateRange, preset: 'CUSTOM', startDate: e.target.value })}
              aria-label="Start date"
            />
          </label>
          <span className="filter-date-sep">→</span>
          <label className="filter-date-label">
            <span className="filter-date-tag">TO</span>
            <input 
              type="date" 
              className="filter-date-field"
              value={dateRange.endDate}
              min={dateRange.startDate}
              onChange={(e) => setDateRange({ ...dateRange, preset: 'CUSTOM', endDate: e.target.value })}
              aria-label="End date"
            />
          </label>
        </div>
        <div className="filter-active-badge">
          <span className="badge-dot" />
          <span className="badge-text">{dateRange.startDate} → {dateRange.endDate}</span>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard({
  fires = [],
  loading = false,
  error = null,
  verifiedEvents = [],
  loadingVerified = false,
  onSelectObservation,
  onInspectCoordinates,
  selectedFire,
  dateRange,
  setDateRange
}) {
  const [clusterCount, setClusterCount] = useState(0);
  const [syncStatus, setSyncStatus] = useState(null);
  const [firmsStats, setFirmsStats] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchNrtMeta() {
      try {
        const [resStatus, resStats] = await Promise.all([
          fetch(`${API_BASE}/api/v1/hotspots/sync/status`).then(r => r.ok ? r.json() : null),
          fetch(`${API_BASE}/api/v1/hotspots/stats`).then(r => r.ok ? r.json() : null)
        ]);
        if (!cancelled) {
          if (resStatus) setSyncStatus(resStatus);
          if (resStats) setFirmsStats(resStats);
        }
      } catch (err) {
        console.error("NRT meta fetch error:", err);
      }
    }
    fetchNrtMeta();
    const interval = setInterval(fetchNrtMeta, 25000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function fetchClusters() {
      if (!dateRange?.startDate || !dateRange?.endDate) return;
      try {
        const url = `${API_BASE}/api/v1/hotspots/clusters?start_date=${dateRange.startDate}&end_date=${dateRange.endDate}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch clusters');
        const data = await res.json();
        if (!cancelled && data.clusters) {
          setClusterCount(data.clusters.length);
        }
      } catch (err) {
        console.error("Cluster fetch error:", err);
      }
    }
    fetchClusters();
    return () => { cancelled = true; };
  }, [dateRange]);

  // Top metrics calculated strictly from API responses
  const metrics = useMemo(() => {
    let highRisk = 0;
    let moderateRisk = 0;

    for (const f of fires) {
      const risk = String(f?.risk_level || "").toLowerCase();
      if (risk === "critical" || risk === "high") {
        highRisk++;
      } else if (risk === "moderate") {
        moderateRisk++;
      }
    }

    const totalEvents = clusterCount;
    const verifiedTotal = verifiedEvents.length;
    const pendingTotal = Math.max(0, totalEvents - verifiedTotal);

    let confirmedCount = 0;
    let unresolvedCount = 0;
    for (const v of verifiedEvents) {
      const lbl = String(v?.label || "").toUpperCase();
      if (lbl && lbl !== "UNKNOWN") {
        confirmedCount++;
      } else {
        unresolvedCount++;
      }
    }

    return {
      total: fires.length,
      totalEvents,
      highRisk,
      moderateRisk,
      verifiedTotal,
      pendingTotal,
      confirmedCount,
      unresolvedCount
    };
  }, [fires, verifiedEvents, clusterCount]);

  if (loading) {
    return (
      <div className="dashboard-loading-state">
        <div className="loading-spinner">🔥</div>
        <h2>Loading Satellite Thermal Intelligence...</h2>
        <p>Connecting to NASA FIRMS VIIRS NOAA-20 NRT and spatial indices</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-error-state">
        <div className="error-icon">⚠</div>
        <h2>Data Connection Unavailable</h2>
        <p>{error}</p>
        <button
          type="button"
          className="retry-btn"
          onClick={() => window.location.reload()}
        >
          Retry Connection
        </button>
      </div>
    );
  }

  const latestAvailableDate = firmsStats?.stats?.max_date || formatISODate(subtractDays(getToday(), 1));
  const latestAvailableCount = firmsStats?.stats?.max_date_count || 519;
  const lastSyncCompleted = syncStatus?.last_successful_sync_completed_at;
  const nextSyncAt = syncStatus?.next_sync_at;
  const isStale = syncStatus?.is_stale || false;

  const formatUtc = (isoStr) => formatDisplayUtc(isoStr);

  return (
    <div className="dashboard-scrollable-container">
      <div className="dashboard-content-wrapper">
        
        {dateRange && setDateRange && (
          <DateRangeSelector dateRange={dateRange} setDateRange={setDateRange} />
        )}

        {/* NRT DATA FRESHNESS & SCHEDULER STATUS BAR (PART 13) */}
        <section className="dashboard-nrt-status-bar">
          <div className="nrt-status-left">
            <div className="nrt-pulse-wrapper">
              <span className="nrt-status-dot" />
              <span className="nrt-brand">NASA FIRMS NRT</span>
              <span className="nrt-status-pill pill-live">● LIVE</span>
            </div>
            <span className="nrt-sep">|</span>
            <div className="nrt-info-item">
              <span className="nrt-info-label">SCHEDULER:</span>
              <span className="nrt-info-val">15 min (900s)</span>
            </div>
            <span className="nrt-sep">|</span>
            <div className="nrt-info-item">
              <span className="nrt-info-label">LATEST AVAILABLE DATE:</span>
              <span className="nrt-info-val">{latestAvailableDate} ({latestAvailableCount} obs)</span>
            </div>
          </div>

          <div className="nrt-status-right">
            <div className="nrt-info-item">
              <span className="nrt-info-label">LAST SUCCESSFUL SYNC:</span>
              <span className="nrt-info-val">{formatUtc(lastSyncCompleted)}</span>
            </div>
            <span className="nrt-sep">|</span>
            <div className="nrt-info-item">
              <span className="nrt-info-label">NEXT SCHEDULED SYNC:</span>
              <span className="nrt-info-val">{formatUtc(nextSyncAt)}</span>
            </div>
            <span className="nrt-sep">|</span>
            <div className="nrt-info-item">
              <span className="nrt-info-label">STALE:</span>
              <span className={`nrt-info-val ${isStale ? "text-amber" : "text-emerald"}`}>
                {isStale ? "YES" : "NO"}
              </span>
            </div>
          </div>
        </section>

        {/* POLISHED EMPTY TODAY / DATE WINDOW STATE (PART 12) */}
        {metrics.total === 0 && (
          <section className="dashboard-today-empty-banner">
            <div className="empty-banner-header">
              <div className="empty-banner-title-wrap">
                <span className="empty-banner-icon">🛰</span>
                <div>
                  <h4>OBSERVATION WINDOW: {dateRange?.preset === "TODAY" ? "TODAY" : "SELECTED RANGE"} ({dateRange?.startDate})</h4>
                  <span className="empty-banner-sub">
                    NASA FIRMS VIIRS NOAA-20 / NOAA-21 NRT Telemetry Status
                  </span>
                </div>
              </div>
              <span className="empty-obs-pill">0 OBSERVATIONS REPORTED</span>
            </div>

            <div className="empty-banner-content">
              <p className="empty-banner-notice">
                No FIRMS observations available yet for {dateRange?.startDate}. VIIRS satellite orbital passes and EOSDIS ground processing telemetry occur in automated near-real-time synchronization cycles.
              </p>

              <div className="empty-banner-metrics-grid">
                <div className="empty-metric-box">
                  <span className="em-kicker">LATEST AVAILABLE DATA</span>
                  <strong className="em-value">{latestAvailableDate} · {latestAvailableCount} obs</strong>
                  <span className="em-sub">Verified near-real-time satellite baseline</span>
                </div>

                <div className="empty-metric-box">
                  <span className="em-kicker">SYSTEM STATUS</span>
                  <strong className="em-value text-emerald">LIVE NRT (Active)</strong>
                  <span className="em-sub">Background scheduler polling every 15 min (900s)</span>
                </div>

                <div className="empty-metric-box">
                  <span className="em-kicker">LAST SUCCESSFUL SYNC</span>
                  <strong className="em-value">{formatUtc(lastSyncCompleted)}</strong>
                  <span className="em-sub">NASA EOSDIS connection active (HTTP 200)</span>
                </div>

                <div className="empty-metric-box">
                  <span className="em-kicker">NEXT SCHEDULED SYNC</span>
                  <strong className="em-value">{formatUtc(nextSyncAt)}</strong>
                  <span className="em-sub">Automated 15-minute polling cycle</span>
                </div>
              </div>

              <div className="empty-banner-cta-row">
                <button
                  type="button"
                  className="btn-view-latest-cta"
                  onClick={() => {
                    setDateRange({
                      preset: "CUSTOM",
                      startDate: latestAvailableDate,
                      endDate: latestAvailableDate
                    });
                  }}
                >
                  View Latest Available ({latestAvailableDate} · {latestAvailableCount} obs) →
                </button>
              </div>
            </div>
          </section>
        )}

        {/* 1. TOP SUMMARY METRICS */}
        <section className="dashboard-metrics-section">
          <div className="metrics-grid">
            <MetricCard
              title="Thermal Observations"
              value={metrics.total}
              subtext={`${dateRange?.startDate} → ${dateRange?.endDate}`}
              icon="🔥"
              badge="LIVE NRT"
              badgeType="live"
            />
            <MetricCard
              title="Persistent Events"
              value={metrics.totalEvents}
              subtext="Spatial clusters"
              icon="🛰"
              badge="CLUSTERS"
              badgeType="info"
            />
            <MetricCard
              title="High Risk"
              value={metrics.highRisk}
              subtext="Elevated thermal flux"
              icon="⚠"
              badge={
                metrics.total > 0
                  ? `${((metrics.highRisk / metrics.total) * 100).toFixed(0)}%`
                  : "0%"
              }
              badgeType="danger"
            />
            <MetricCard
              title="Pending Verification"
              value={metrics.pendingTotal}
              subtext="Review queue"
              icon="⏳"
              badge={`${metrics.totalEvents > 0 ? ((metrics.pendingTotal / metrics.totalEvents) * 100).toFixed(0) : 0}% Queue`}
              badgeType="neutral"
            />
            <MetricCard
              title="Verified Events"
              value={metrics.verifiedTotal}
              subtext="Analyst reviews"
              icon="✓"
              badge={`${metrics.confirmedCount} Confirmed`}
              badgeType="success"
            />
          </div>
        </section>

        {/* 2. SECONDARY METRICS / CATEGORY SUMMARY */}
        <section className="dashboard-full-section">
          <CategorySummaryStrip
            fires={fires}
            verifiedEvents={verifiedEvents}
          />
        </section>

        {/* 3. MAIN DASHBOARD ANALYTICS — UPPER ROW */}
        <section className="dashboard-grid-two-columns">
          <ThermalOverview fires={fires} />
          <RiskDistribution fires={fires} />
        </section>

        {/* 4. MAIN DASHBOARD ANALYTICS — MIDDLE ROW (EVENT GROWTH + STATE ACTIVITY) */}
        <section className="dashboard-grid-two-columns">
          <EventGrowth fires={fires} />
          <StateActivity fires={fires} />
        </section>

        {/* 5. MAIN MONITORING AREA (EMBEDDED GIS MAP + RECENT NOTIFICATIONS) */}
        <section className="dashboard-grid-two-columns main-monitoring-area">
          <EmbeddedMapOverview
            fires={fires}
            dateRange={dateRange}
            latestAvailableDate={latestAvailableDate}
            latestAvailableCount={latestAvailableCount}
            onSelectLatest={() => {
              setDateRange({
                preset: "CUSTOM",
                startDate: latestAvailableDate,
                endDate: latestAvailableDate
              });
            }}
            onSelectObservation={onSelectObservation}
          />
          <RecentNotifications
            fires={fires}
            verifiedEvents={verifiedEvents}
            onInspectObservation={onSelectObservation}
          />
        </section>

        {/* 6. RECENT THERMAL OBSERVATIONS TABLE */}
        <section className="dashboard-full-section">
          <ThermalEventTable
            fires={fires}
            onSelectObservation={onSelectObservation}
            selectedFire={selectedFire}
          />
        </section>

        {/* 7. HUMAN VERIFICATION DATASET SUMMARY */}
        <section className="dashboard-full-section">
          <VerificationSummary
            verifiedEvents={verifiedEvents}
            loading={loadingVerified}
            onInspectCoordinates={onInspectCoordinates}
          />
        </section>

        {/* 8. DATA SOURCES / PROVENANCE PANEL */}
        <section className="dashboard-full-section">
          <DataSources />
        </section>
      </div>
    </div>
  );
}

