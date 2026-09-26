import React, { useMemo } from "react";

export default function RecentNotifications({
  fires = [],
  verifiedEvents = [],
  isOnline = true,
  onInspectObservation
}) {
  const notifications = useMemo(() => {
    const list = [];

    // 1. Backend Connectivity Status
    if (!isOnline) {
      list.push({
        id: "sys-offline",
        icon: "🔌",
        title: "API Connection Offline",
        severity: "CRITICAL",
        description: "FastAPI backend at http://10.44.86.31:8001 is currently unreachable.",
        time: "Active now"
      });
      return list;
    }

    // 2. Active Batch Synchronized (NASA FIRMS)
    if (fires && fires.length > 0) {
      const latestDate = fires[0]?.acq_date || "Current Query";
      list.push({
        id: "batch-sync",
        icon: "🛰",
        title: "NASA FIRMS Synchronized",
        severity: "INFO",
        description: `Successfully ingested ${fires.length} active thermal observations (VIIRS NOAA-20 NRT).`,
        time: latestDate,
        actionText: "View Observations →",
        action: onInspectObservation && fires[0] ? () => onInspectObservation(fires[0]) : null
      });
    }

    // 3. Critical Risk Detections
    const criticalFires = fires.filter(
      (f) => String(f?.risk_level || "").toLowerCase() === "critical"
    );
    if (criticalFires.length > 0) {
      const topCritical = criticalFires[0];
      const maxFrp = Math.max(...criticalFires.map((f) => Number(f?.frp || 0)));
      list.push({
        id: "crit-risk",
        icon: "🚨",
        title: `${criticalFires.length} Critical Risk Anomalies`,
        severity: "CRITICAL",
        description: `Peak FRP ${maxFrp.toFixed(1)} MW detected near ${
          topCritical?.geographic_validation?.state || "unassigned coordinates"
        }. Elevated radiance requires priority inspection.`,
        time: topCritical?.acq_date || "Recent",
        actionText: "View Observation →",
        action: onInspectObservation ? () => onInspectObservation(topCritical) : null
      });
    }

    // 4. High Risk Detections
    const highFires = fires.filter(
      (f) => String(f?.risk_level || "").toLowerCase() === "high"
    );
    if (highFires.length > 0) {
      const topHigh = highFires[0];
      list.push({
        id: "high-risk",
        icon: "⚠",
        title: `${highFires.length} High Risk Observations`,
        severity: "WARNING",
        description:
          "Elevated thermal radiance identified across active land sectors in the current query window.",
        time: topHigh?.acq_date || "Recent",
        actionText: "View Observation →",
        action: onInspectObservation ? () => onInspectObservation(topHigh) : null
      });
    }

    // 5. Human Verifications
    if (verifiedEvents && verifiedEvents.length > 0) {
      const latestVerification = verifiedEvents[verifiedEvents.length - 1];
      const rawLabel = String(latestVerification?.label || "CLASSIFIED");
      const label = rawLabel.replace(/_/g, " ");

      let formattedTime = "Recorded";
      if (latestVerification?.verified_at) {
        try {
          const d = new Date(latestVerification.verified_at);
          const hh = String(d.getHours()).padStart(2, "0");
          const mm = String(d.getMinutes()).padStart(2, "0");
          formattedTime = `${hh}:${mm}`;
        } catch {
          formattedTime = "Recorded";
        }
      }

      list.push({
        id: "verified-entry",
        icon: "✓",
        title: "Human Verification",
        severity: "SUCCESS",
        description: `${verifiedEvents.length} operator verification record(s) cataloged in verified events registry. Latest: ${label}.`,
        time: formattedTime
      });
    }

    // 6. Water Body Hotspots (Inland or Marine)
    const waterFires = fires.filter((f) => {
      const d = f?.geographic_validation?.domain;
      return (
        d === "INLAND_WATER" ||
        d === "OFFSHORE_MARINE" ||
        d === "COASTAL_NEAR_SHORE"
      );
    });
    if (waterFires.length > 0) {
      const wf = waterFires[0];
      const domainName =
        wf?.geographic_validation?.domain === "INLAND_WATER"
          ? "Inland Water"
          : "Offshore Marine";
      list.push({
        id: "water-anomaly",
        icon: "💧",
        title: `${waterFires.length} Aquatic / Marine Hotspot(s)`,
        severity: "WARNING",
        description: `Observation classified as ${domainName} near ${
          wf?.geographic_validation?.city || wf?.geographic_validation?.state || "water sector"
        }. Requires domain inspection.`,
        time: wf?.acq_date || "Recent",
        actionText: "View Observation →",
        action: onInspectObservation ? () => onInspectObservation(wf) : null
      });
    }

    return list;
  }, [fires, verifiedEvents, isOnline, onInspectObservation]);

  return (
    <div className="dashboard-panel notifications-command-panel">
      {/* 1. HEADER */}
      <div className="panel-title-row">
        <div>
          <h3>System Event Notifications</h3>
          <p className="panel-subtitle">
            Live alerts synthesized directly from current API observations and operator actions
          </p>
        </div>
        <span className="window-pill">{notifications.length} Active</span>
      </div>

      {/* 2. NOTIFICATIONS FEED */}
      {notifications.length === 0 ? (
        <div className="panel-empty-state">No active event alerts in current observation window.</div>
      ) : (
        <div className="notifications-feed-list">
          {notifications.map((n) => (
            <div
              key={n.id}
              className={`alert-feed-card card-severity-${n.severity.toLowerCase()}`}
            >
              {/* LEFT: ICON */}
              <div className={`alert-icon-wrapper icon-severity-${n.severity.toLowerCase()}`}>
                <span className="alert-icon-symbol">{n.icon}</span>
              </div>

              {/* CONTENT AREA */}
              <div className="alert-content-area">
                {/* TOP ROW: TITLE (LEFT) + SEVERITY BADGE (RIGHT) */}
                <div className="alert-top-row">
                  <strong className="alert-title-text">{n.title}</strong>
                  <span className={`alert-severity-badge badge-${n.severity.toLowerCase()}`}>
                    {n.severity}
                  </span>
                </div>

                {/* DESCRIPTION */}
                <p className="alert-description-text">{n.description}</p>

                {/* BOTTOM ROW: TIMESTAMP (LEFT) + ACTION (RIGHT) */}
                <div className="alert-bottom-row">
                  <span className="alert-timestamp">{n.time}</span>
                  {n.action && (
                    <button
                      type="button"
                      className="alert-action-link"
                      onClick={n.action}
                      title="Inspect this observation in GIS Studio"
                    >
                      {n.actionText || "View Observation →"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

