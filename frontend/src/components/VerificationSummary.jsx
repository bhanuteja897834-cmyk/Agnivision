import React from "react";

const LABEL_BADGES = {
  ACTIVE_FIRE: { icon: "🔥", label: "Active Fire", color: "#dc2626", bg: "#fef2f2" },
  INDUSTRIAL_HEAT: { icon: "🏭", label: "Industrial Heat", color: "#ea580c", bg: "#fff7ed" },
  AGRICULTURAL_BURNING: { icon: "🌾", label: "Agricultural Burning", color: "#ca8a04", bg: "#fefce8" },
  WILDLAND_FIRE: { icon: "🌲", label: "Wildland Fire", color: "#16a34a", bg: "#f0fdf4" },
  UNKNOWN: { icon: "❔", label: "Unknown", color: "#64748b", bg: "#f8fafc" }
};

export default function VerificationSummary({
  verifiedEvents = [],
  loading = false,
  onInspectCoordinates
}) {
  return (
    <div className="dashboard-panel verification-summary-panel">
      <div className="panel-title-row">
        <div>
          <h3>Human Verification</h3>
          <p className="panel-subtitle">
            Analyst-verified classifications collected via /verify-event for operational auditability
          </p>
        </div>
        <span className="source-pill">Verified Analyst Records</span>
      </div>

      <div className="verification-explanation-banner">
        <span className="banner-icon">ℹ</span>
        <p>
          These records represent manual human classifications. They are <strong>not</strong> model predictions or automated AI outputs.
        </p>
      </div>

      {loading ? (
        <div className="panel-empty-state">Loading verification records…</div>
      ) : verifiedEvents.length === 0 ? (
        <div className="panel-empty-state">
          No human-verified events in dataset yet. Operators can verify events using the Incident Inspection panel.
        </div>
      ) : (
        <div className="table-responsive">
          <table className="observation-table verification-table">
            <thead>
              <tr>
                <th>Observation / Event</th>
                <th>Human Label</th>
                <th>Review Date</th>
                <th>Context Features</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {verifiedEvents.map((item, index) => {
                const event = item?.event || {};
                const features = item?.features || {};
                const label = item?.label || "UNKNOWN";
                const badge = LABEL_BADGES[label] || LABEL_BADGES.UNKNOWN;
                const lat = Number(event?.latitude);
                const lon = Number(event?.longitude);

                return (
                  <tr key={`verified-${index}-${event?.latitude}-${event?.longitude}-${item?.verified_at}`}>
                    <td>
                      <div className="verified-obs-cell">
                        <strong>
                          {Number.isFinite(lat) ? lat.toFixed(5) : "—"},{" "}
                          {Number.isFinite(lon) ? lon.toFixed(5) : "—"}
                        </strong>
                        <small>
                          {event?.acq_date || "N/A"} · {event?.acq_time || "N/A"} UTC ({event?.source || "NASA FIRMS"})
                        </small>
                      </div>
                    </td>
                    <td>
                      <span
                        className="human-label-badge"
                        style={{
                          color: badge.color,
                          backgroundColor: badge.bg,
                          borderColor: badge.color
                        }}
                      >
                        {badge.icon} {badge.label}
                      </span>
                    </td>
                    <td>
                      <span className="time-cell">
                        {item?.verified_at
                          ? new Date(item.verified_at).toLocaleString()
                          : "Unknown"}
                      </span>
                    </td>
                    <td>
                      <div className="features-preview">
                        <span>FRP: {features.frp ?? "N/A"} MW</span>
                        <span>•</span>
                        <span>Bright: {features.brightness ?? "N/A"} K</span>
                        <span>•</span>
                        <span>Buildings (5km): {features.buildings_5km ?? 0}</span>
                      </div>
                    </td>
                    <td>
                      {Number.isFinite(lat) && Number.isFinite(lon) && onInspectCoordinates && (
                        <button
                          type="button"
                          className="inspect-btn"
                          onClick={() => onInspectCoordinates(lat, lon)}
                        >
                          View Map
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

