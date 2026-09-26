import React from "react";

export default function MetricCard({
  title,
  value,
  subtext,
  icon,
  badge,
  badgeType = "default",
  unavailable = false,
  onClick
}) {
  return (
    <div
      className={`dashboard-metric-card ${onClick ? "clickable" : ""}`}
      onClick={onClick}
    >
      <div className="metric-header">
        <span className="metric-title">{title}</span>
        {icon && <span className="metric-icon">{icon}</span>}
      </div>

      <div className="metric-body">
        {unavailable ? (
          <div className="metric-unavailable">Not available</div>
        ) : (
          <div className="metric-value">{value ?? "—"}</div>
        )}
      </div>

      <div className="metric-footer">
        {subtext && <span className="metric-subtext">{subtext}</span>}
        {badge && (
          <span className={`metric-badge badge-${badgeType}`}>{badge}</span>
        )}
      </div>
    </div>
  );
}

