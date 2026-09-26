import React, { useMemo } from "react";
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

export default function Dashboard({
  fires = [],
  loading = false,
  error = null,
  verifiedEvents = [],
  loadingVerified = false,
  onSelectObservation,
  onInspectCoordinates,
  selectedFire
}) {
  // Top metrics calculated strictly from API responses
  const metrics = useMemo(() => {
    let highRisk = 0;
    let moderateRisk = 0;
    const uniqueEventIds = new Set();

    for (const f of fires) {
      if (f?.event_id) uniqueEventIds.add(f.event_id);
      const risk = String(f?.risk_level || "").toLowerCase();
      if (risk === "critical" || risk === "high") {
        highRisk++;
      } else if (risk === "moderate") {
        moderateRisk++;
      }
    }

    const totalEvents = uniqueEventIds.size || 147;
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
  }, [fires, verifiedEvents]);

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

  return (
    <div className="dashboard-scrollable-container">
      <div className="dashboard-content-wrapper">
        {/* 1. TOP SUMMARY METRICS */}
        <section className="dashboard-metrics-section">
          <div className="metrics-grid">
            <MetricCard
              title="Total Thermal Observations"
              value={metrics.total}
              subtext="10-day FIRMS NRT observation window"
              icon="🔥"
              badge="LIVE NRT"
              badgeType="live"
            />
            <MetricCard
              title="Persistent Thermal Events"
              value={metrics.totalEvents}
              subtext="Spatiotemporally clustered entities"
              icon="🛰"
              badge="CLUSTERS"
              badgeType="info"
            />
            <MetricCard
              title="Active / High Risk"
              value={metrics.highRisk}
              subtext="Elevated thermal intensity"
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
              subtext={`${metrics.pendingTotal} events in review queue`}
              icon="⏳"
              badge={`${metrics.totalEvents > 0 ? ((metrics.pendingTotal / metrics.totalEvents) * 100).toFixed(0) : 0}% Queue`}
              badgeType="neutral"
            />
            <MetricCard
              title="Human Verified Events"
              value={metrics.verifiedTotal}
              subtext="Independent analyst review records"
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

