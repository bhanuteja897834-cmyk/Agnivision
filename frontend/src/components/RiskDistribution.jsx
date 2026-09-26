import React, { useMemo } from "react";

const RISK_CONFIG = {
  Critical: {
    color: "#dc2626",
    bgColor: "#fef2f2",
    description: "Intense thermal anomalies with repeat persistence"
  },
  High: {
    color: "#ea580c",
    bgColor: "#fff7ed",
    description: "Elevated brightness temperature and nominal/high confidence"
  },
  Moderate: {
    color: "#d97706",
    bgColor: "#fffbeb",
    description: "Standard active thermal observations"
  },
  Low: {
    color: "#16a34a",
    bgColor: "#f0fdf4",
    description: "Low confidence or low intensity thermal observations"
  }
};

export default function RiskDistribution({ fires = [] }) {
  const distribution = useMemo(() => {
    if (!fires || fires.length === 0) return [];

    const counts = {};
    for (const f of fires) {
      const level = f?.risk_level || "Unknown";
      counts[level] = (counts[level] || 0) + 1;
    }

    // Natural ordering: Critical, High, Moderate, Low, followed by any other
    const order = ["Critical", "High", "Moderate", "Low"];
    const allKeys = Object.keys(counts).sort((a, b) => {
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b);
    });

    return allKeys.map((key) => {
      const count = counts[key];
      const pct = ((count / fires.length) * 100).toFixed(1);
      const cfg = RISK_CONFIG[key] || {
        color: "#64748b",
        bgColor: "#f8fafc",
        description: "Prototype heuristic risk evaluation"
      };
      return {
        level: key,
        count,
        pct,
        ...cfg
      };
    });
  }, [fires]);

  return (
    <div className="dashboard-panel risk-distribution-panel">
      <div className="panel-title-row">
        <div>
          <h3>Risk Level Distribution</h3>
          <p className="panel-subtitle">
            Deterministic prototype heuristic combining brightness, confidence, and persistence
          </p>
        </div>
        <span className="heuristic-pill">Prototype Heuristic</span>
      </div>

      {distribution.length === 0 ? (
        <div className="panel-empty-state">No risk data available.</div>
      ) : (
        <div className="risk-level-list">
          {distribution.map((item) => (
            <div key={item.level} className="risk-level-card">
              <div className="risk-card-head">
                <div className="risk-badge-group">
                  <span
                    className="risk-dot"
                    style={{ backgroundColor: item.color }}
                  />
                  <strong className="risk-name">{item.level}</strong>
                </div>
                <div className="risk-metric">
                  <strong>{item.count}</strong>
                  <span className="risk-pct">({item.pct}%)</span>
                </div>
              </div>

              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${item.pct}%`,
                    backgroundColor: item.color
                  }}
                />
              </div>

              <div className="risk-desc">{item.description}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

