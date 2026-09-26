import React, { useMemo } from "react";

const DOMAIN_METADATA = {
  LAND: {
    label: "Continental Land",
    icon: "⛰",
    color: "#16a34a",
    bgColor: "#f0fdf4",
    desc: "Continental terrain validated via NOAA GLOBE 1km land-water mask"
  },
  INLAND_WATER: {
    label: "Inland Water",
    icon: "💧",
    color: "#0284c7",
    bgColor: "#f0f9ff",
    desc: "Lakes, reservoirs, or major interior freshwater bodies"
  },
  COASTAL_NEAR_SHORE: {
    label: "Coastal / Near Shore",
    icon: "🌊",
    color: "#0d9488",
    bgColor: "#f0fdfa",
    desc: "Intertidal or marine waters within 5 km of land"
  },
  OFFSHORE_MARINE: {
    label: "Offshore Marine",
    icon: "⚓",
    color: "#2563eb",
    bgColor: "#eff6ff",
    desc: "Open sea or ocean waters greater than 5 km from land"
  },
  UNKNOWN_UNRESOLVED: {
    label: "Unknown / Unresolved",
    icon: "❔",
    color: "#64748b",
    bgColor: "#f8fafc",
    desc: "Invalid or out-of-bounds observation coordinates"
  }
};

export default function DomainDistribution({ fires = [] }) {
  const domainData = useMemo(() => {
    if (!fires || fires.length === 0) return [];

    const counts = {
      LAND: 0,
      INLAND_WATER: 0,
      COASTAL_NEAR_SHORE: 0,
      OFFSHORE_MARINE: 0,
      UNKNOWN_UNRESOLVED: 0
    };

    for (const f of fires) {
      const d = f?.geographic_validation?.domain || "UNKNOWN_UNRESOLVED";
      if (counts[d] !== undefined) {
        counts[d]++;
      } else {
        counts.UNKNOWN_UNRESOLVED++;
      }
    }

    return Object.entries(counts).map(([domainKey, count]) => {
      const meta = DOMAIN_METADATA[domainKey] || DOMAIN_METADATA.UNKNOWN_UNRESOLVED;
      const pct = fires.length > 0 ? ((count / fires.length) * 100).toFixed(1) : "0";
      return {
        key: domainKey,
        count,
        pct,
        ...meta
      };
    });
  }, [fires]);

  return (
    <div className="dashboard-panel domain-distribution-panel">
      <div className="panel-title-row">
        <div>
          <h3>Geographic & Land-Cover Domains</h3>
          <p className="panel-subtitle">
            NOAA GLOBE 1km land-ocean mask and regional surface hydrology classification
          </p>
        </div>
        <span className="source-pill">NOAA GLOBE 1km</span>
      </div>

      <div className="domain-grid">
        {domainData.map((d) => (
          <div
            key={d.key}
            className={`domain-card ${d.count > 0 ? "has-data" : "zero-data"}`}
          >
            <div className="domain-card-head">
              <div className="domain-icon-title">
                <span className="domain-icon">{d.icon}</span>
                <div>
                  <strong className="domain-title">{d.label}</strong>
                  <div className="domain-code">{d.key}</div>
                </div>
              </div>
              <div className="domain-stat">
                <strong className="domain-count">{d.count}</strong>
                <span className="domain-pct">{d.pct}%</span>
              </div>
            </div>

            <div className="bar-track">
              <div
                className="bar-fill"
                style={{
                  width: `${d.pct}%`,
                  backgroundColor: d.color
                }}
              />
            </div>

            <p className="domain-desc">{d.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

