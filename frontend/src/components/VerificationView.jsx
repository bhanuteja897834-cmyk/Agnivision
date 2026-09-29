import React, { useState, useEffect, useMemo } from "react";
import VerificationSummary from "./VerificationSummary";
import "./VerificationView.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";

const LABEL_BADGES = {
  ACTIVE_FIRE: { icon: "🔥", label: "Active Fire", color: "#dc2626", bg: "rgba(220, 38, 38, 0.15)", border: "#ef4444" },
  INDUSTRIAL_HEAT: { icon: "🏭", label: "Industrial Heat", color: "#38bdf8", bg: "rgba(56, 189, 248, 0.15)", border: "#38bdf8" },
  AGRICULTURAL_BURNING: { icon: "🌾", label: "Agricultural Burning", color: "#f59e0b", bg: "rgba(245, 158, 11, 0.15)", border: "#f59e0b" },
  WILDLAND_FIRE: { icon: "🌲", label: "Wildland Fire", color: "#10b981", bg: "rgba(16, 185, 129, 0.15)", border: "#10b981" },
  UNKNOWN: { icon: "❔", label: "Unknown / Unresolved", color: "#94a3b8", bg: "rgba(148, 163, 184, 0.15)", border: "#64748b" }
};

export default function VerificationView({
  fires = [],
  verifiedEvents = [],
  loadingVerified = false,
  onSelectObservation,
  onInspectCoordinates,
  onOpenEvaluation,
  onOpenTemporal,
  onRefreshVerified
}) {
  const [eventsList, setEventsList] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [eventsError, setEventsError] = useState(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState("ALL"); // ALL | UNVERIFIED | VERIFIED
  const [classFilter, setClassFilter] = useState("ALL");
  const [domainFilter, setDomainFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Fetch all persistent thermal events
  useEffect(() => {
    let active = true;
    async function fetchEvents() {
      try {
        setLoadingEvents(true);
        setEventsError(null);
        const res = await fetch(`${API_BASE}/events`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (active && Array.isArray(data?.events)) {
          setEventsList(data.events);
        }
      } catch (err) {
        if (active) setEventsError(err.message || "Failed to load events");
      } finally {
        if (active) setLoadingEvents(false);
      }
    }
    fetchEvents();
    return () => {
      active = false;
    };
  }, []);

  // Cache of authoritative rule-based classifications
  const [classifications, setClassifications] = useState({});

  useEffect(() => {
    let active = true;
    if (Array.isArray(verifiedEvents)) {
      verifiedEvents.forEach((v) => {
        const eid = v.event_id || v.features?.event_id;
        if (eid && !classifications[eid]) {
          fetch(`${API_BASE}/events/${eid}/classification`)
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
              if (active && data?.classification) {
                setClassifications((prev) => ({
                  ...prev,
                  [eid]: data.classification
                }));
              }
            })
            .catch(() => {});
        }
      });
    }
    return () => {
      active = false;
    };
  }, [verifiedEvents]);

  // Map events with verification records
  const enrichedEvents = useMemo(() => {
    return eventsList.map((e) => {
      const eid = e.event_id;
      // Match against verifiedEvents by event_id or centroid proximity
      const vMatch = verifiedEvents.find((v) => {
        const vEid = v.event_id || v.features?.event_id;
        if (vEid) {
          return Boolean(eid && vEid.toUpperCase() === eid.toUpperCase());
        }
        const vLat = Number(v.event?.latitude);
        const vLon = Number(v.event?.longitude);
        const cLat = Number(e.centroid?.latitude);
        const cLon = Number(e.centroid?.longitude);
        return (
          Number.isFinite(vLat) &&
          Number.isFinite(vLon) &&
          Number.isFinite(cLat) &&
          Number.isFinite(cLon) &&
          Math.abs(vLat - cLat) < 0.01 &&
          Math.abs(vLon - cLon) < 0.01
        );
      });

      return {
        ...e,
        isVerified: Boolean(vMatch),
        verificationRecord: vMatch || null,
        humanLabel: vMatch?.label || null,
        systemClassification: classifications[eid] || e.system_classification || "UNKNOWN"
      };
    });
  }, [eventsList, verifiedEvents, classifications]);

  // KPI Metrics
  const totalEvents = enrichedEvents.length;
  const verifiedCount = enrichedEvents.filter((e) => e.isVerified).length;
  const unverifiedCount = totalEvents - verifiedCount;
  const coveragePercent = totalEvents > 0 ? ((verifiedCount / totalEvents) * 100).toFixed(1) : "0.0";

  // Filtered Events
  const filteredEvents = useMemo(() => {
    return enrichedEvents.filter((e) => {
      // Status filter
      if (statusFilter === "VERIFIED" && !e.isVerified) return false;
      if (statusFilter === "UNVERIFIED" && e.isVerified) return false;

      // Classification filter
      if (classFilter !== "ALL" && e.systemClassification !== classFilter) return false;

      // Domain filter
      if (domainFilter !== "ALL" && (e.geographic_domain || e.geographic_validation?.domain) !== domainFilter) {
        return false;
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        const eid = String(e.event_id || "").toLowerCase();
        const state = String(e.state || e.geographic_validation?.state || "").toLowerCase();
        const district = String(e.district || e.geographic_validation?.district || "").toLowerCase();
        const label = String(e.humanLabel || "").toLowerCase();
        if (!eid.includes(q) && !state.includes(q) && !district.includes(q) && !label.includes(q)) {
          return false;
        }
      }

      return true;
    });
  }, [enrichedEvents, statusFilter, classFilter, domainFilter, searchQuery]);

  return (
    <div className="verification-view-container">
      <div className="verification-content-wrapper">
        
        {/* 1. HEADER */}
        <div className="verification-header">
          <div className="verification-header-left">
            <div className="verification-header-badge">
              <span>✓</span> Operator Verification Station
            </div>
            <h2 className="verification-header-title">
              Human Verification Workspace
            </h2>
            <p className="verification-header-desc">
              Analyst review station for evaluating multi-source evidence and recording verified labels.
            </p>
          </div>

          <div className="verification-header-actions">
            {onRefreshVerified && (
              <button
                type="button"
                onClick={onRefreshVerified}
                className="verification-refresh-btn"
              >
                ⟳ Refresh Dataset
              </button>
            )}
          </div>
        </div>

        {/* 2. VERIFICATION SUMMARY KPI CARDS */}
        <div className="verification-kpi-grid">
          <div className="verification-kpi-card">
            <span className="verification-kpi-label">Persistent Events</span>
            <strong className="verification-kpi-val">{loadingEvents ? "—" : totalEvents}</strong>
            <span className="verification-kpi-subtext">Spatial clusters</span>
          </div>

          <div className="verification-kpi-card verified">
            <span className="verification-kpi-label verified">Human Verified</span>
            <strong className="verification-kpi-val verified">{verifiedCount}</strong>
            <span className="verification-kpi-subtext">Verified registry</span>
          </div>

          <div className="verification-kpi-card pending">
            <span className="verification-kpi-label pending">Pending Review</span>
            <strong className="verification-kpi-val pending">{unverifiedCount}</strong>
            <span className="verification-kpi-subtext">Review queue</span>
          </div>

          <div className="verification-kpi-card">
            <span className="verification-kpi-label">Coverage</span>
            <strong className="verification-kpi-val coverage">{coveragePercent}%</strong>
            <span className="verification-kpi-subtext">Verified ratio</span>
          </div>
        </div>

        {/* 3. EVENT LIST & FILTERS */}
        <section className="verification-section-card">
          <div className="verification-section-header">
            <div>
              <h3 className="verification-section-title">
                Persistent Thermal Events Review Queue
              </h3>
              <p className="verification-section-subtitle">
                Compare rule-based System Classifications against Human Verification status. Select any event to evaluate multi-source evidence and record a verified decision.
              </p>
            </div>

            {/* Status Filter Tabs */}
            <div className="verification-filter-tabs">
              {[
                { id: "ALL", label: `All (${totalEvents})` },
                { id: "UNVERIFIED", label: `Unverified (${unverifiedCount})` },
                { id: "VERIFIED", label: `Verified (${verifiedCount})` }
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setStatusFilter(tab.id)}
                  className={`verification-filter-tab-btn ${statusFilter === tab.id ? "active" : ""}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Secondary Controls: Search & Dropdowns */}
          <div className="verification-controls-row">
            <input
              type="text"
              placeholder="Search Event ID, State, District..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="verification-search-input"
            />

            <select
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
              className="verification-select"
            >
              <option value="ALL">All System Classifications</option>
              <option value="INDUSTRIAL_HEAT">INDUSTRIAL_HEAT</option>
              <option value="ACTIVE_FIRE">ACTIVE_FIRE</option>
              <option value="UNKNOWN">UNKNOWN</option>
              <option value="AGRICULTURAL_BURNING">AGRICULTURAL_BURNING</option>
              <option value="WILDLAND_FIRE">WILDLAND_FIRE</option>
            </select>

            <select
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              className="verification-select"
            >
              <option value="ALL">All Domains</option>
              <option value="LAND">LAND</option>
              <option value="OFFSHORE_MARINE">OFFSHORE_MARINE</option>
              <option value="INLAND_WATER">INLAND_WATER</option>
            </select>

            <span className="verification-showing-text">
              Showing {filteredEvents.length} of {totalEvents} events
            </span>
          </div>

          {/* Events Table */}
          {loadingEvents ? (
            <div className="verification-message-box">Loading persistent events queue...</div>
          ) : eventsError ? (
            <div className="verification-error-box">
              Error loading events: {eventsError}
            </div>
          ) : filteredEvents.length === 0 ? (
            <div className="verification-message-box">No events matched the selected filters.</div>
          ) : (
            <div className="verification-table-container">
              <table className="verification-queue-table">
                <thead>
                  <tr>
                    <th>Event ID</th>
                    <th>System Classification</th>
                    <th>Human Verification</th>
                    <th>Domain & State</th>
                    <th>Observations</th>
                    <th>Last Detected</th>
                    <th>Risk Level</th>
                    <th style={{ textAlign: "right" }}>Analyst Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEvents.map((evt) => {
                    const badge = evt.humanLabel ? LABEL_BADGES[evt.humanLabel] || LABEL_BADGES.UNKNOWN : null;
                    const systemClassType = evt.systemClassification === "INDUSTRIAL_HEAT"
                      ? "industrial"
                      : evt.systemClassification === "ACTIVE_FIRE"
                        ? "active-fire"
                        : "neutral";

                    const riskClass = evt.risk_level === "Critical"
                      ? "critical"
                      : evt.risk_level === "High"
                        ? "high"
                        : evt.risk_level === "Moderate"
                          ? "moderate"
                          : "low";

                    return (
                      <tr key={evt.event_id}>
                        <td>
                          <strong className="event-id-cell">
                            {evt.event_id}
                          </strong>
                        </td>
                        <td>
                          <span className={`system-class-badge ${systemClassType}`}>
                            {evt.systemClassification}
                            <span style={{ fontSize: "9px", opacity: 0.8 }}>(RULE-BASED)</span>
                          </span>
                        </td>
                        <td>
                          {evt.isVerified && badge ? (
                            <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                              <span className={`verified-badge-pill ${evt.humanLabel || "UNKNOWN"}`}>
                                <span>{badge.icon}</span> {evt.humanLabel}
                              </span>
                              <span style={{ fontSize: "10px", color: "#64748b" }}>
                                {evt.verificationRecord?.verified_at ? new Date(evt.verificationRecord.verified_at).toLocaleDateString() : "Verified"}
                              </span>
                            </div>
                          ) : (
                            <span className="unverified-tag">
                              UNVERIFIED
                            </span>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", flexDirection: "column" }}>
                            <span className="geo-state-text">{evt.state || evt.geographic_validation?.state || "Unassigned"}</span>
                            <span className="geo-domain-text">{evt.geographic_domain || evt.geographic_validation?.domain || "LAND"}</span>
                          </div>
                        </td>
                        <td>
                          <span className="obs-count-text">{evt.observation_count}</span>
                          <span style={{ fontSize: "10px", color: "#64748b", marginLeft: "4px" }}>({evt.persistence_days}d)</span>
                        </td>
                        <td className="time-detected-text">
                          {evt.last_detected ? evt.last_detected.replace("T", " ").replace("Z", " UTC") : "—"}
                        </td>
                        <td>
                          <span className={`risk-badge ${riskClass}`}>
                            {evt.risk_level || "Nominal"} ({evt.risk_score ?? "—"})
                          </span>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <div style={{ display: "inline-flex", gap: "6px" }}>
                            {onOpenEvaluation && (
                              <button
                                type="button"
                                onClick={() => onOpenEvaluation(evt.event_id)}
                                className="btn-action-primary"
                              >
                                {evt.isVerified ? "Review Decision" : "Verify Event"}
                              </button>
                            )}
                            {onOpenTemporal && (
                              <button
                                type="button"
                                onClick={() => onOpenTemporal(evt.event_id)}
                                className="btn-action-secondary"
                              >
                                Timeline
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* 4. VERIFIED ANALYST AUDIT LEDGER */}
        <section className="dashboard-full-section">
          <VerificationSummary
            verifiedEvents={verifiedEvents}
            loading={loadingVerified}
            onInspectCoordinates={onInspectCoordinates}
          />
        </section>

      </div>
    </div>
  );
}

