import React, { useMemo } from "react";

export default function CategorySummaryStrip({
  fires = [],
  verifiedEvents = []
}) {
  const counts = useMemo(() => {
    let activeFire = 0;
    let industrialHeat = 0;
    let agriculturalBurning = 0;
    let wildlandFire = 0;
    let unknown = 0;

    for (const v of verifiedEvents) {
      const lbl = String(v?.label || "").toUpperCase();
      if (lbl === "ACTIVE_FIRE") activeFire++;
      else if (lbl === "INDUSTRIAL_HEAT") industrialHeat++;
      else if (lbl === "AGRICULTURAL_BURNING") agriculturalBurning++;
      else if (lbl === "WILDLAND_FIRE") wildlandFire++;
      else unknown++;
    }

    let marineCoastal = 0;
    let inlandWater = 0;
    let continentalLand = 0;

    for (const f of fires) {
      const domain = f?.geographic_validation?.domain;
      if (domain === "LAND") {
        continentalLand++;
      } else if (domain === "INLAND_WATER") {
        inlandWater++;
      } else if (domain === "OFFSHORE_MARINE" || domain === "COASTAL_NEAR_SHORE") {
        marineCoastal++;
      }
    }

    return [
      {
        id: "active-fire",
        icon: "🔥",
        label: "Active Fire",
        count: activeFire,
        provenance: "Human Verified",
        color: "#dc2626"
      },
      {
        id: "industrial-heat",
        icon: "🏭",
        label: "Industrial Heat",
        count: industrialHeat,
        provenance: "Human Verified",
        color: "#ea580c"
      },
      {
        id: "agri-burning",
        icon: "🌾",
        label: "Agri Burning",
        count: agriculturalBurning,
        provenance: "Human Verified",
        color: "#ca8a04"
      },
      {
        id: "wildland-fire",
        icon: "🌲",
        label: "Wildland Fire",
        count: wildlandFire,
        provenance: "Human Verified",
        color: "#16a34a"
      },
      {
        id: "unknown",
        icon: "❔",
        label: "Non-Fire / Unknown",
        count: unknown,
        provenance: "Human Verified",
        color: "#64748b"
      },
      {
        id: "marine",
        icon: "⚓",
        label: "Marine / Coastal",
        count: marineCoastal,
        provenance: "NOAA Domain",
        color: "#0284c7"
      },
      {
        id: "inland-water",
        icon: "💧",
        label: "Inland Water",
        count: inlandWater,
        provenance: "HydroLAKES",
        color: "#0891b2"
      },
      {
        id: "land",
        icon: "⛰",
        label: "Continental Land",
        count: continentalLand,
        provenance: "NOAA GLOBE",
        color: "#059669"
      }
    ];
  }, [fires, verifiedEvents]);

  return (
    <div className="category-summary-strip">
      <div className="category-strip-header">
        <span className="strip-title">CATEGORY &amp; DOMAIN BREAKDOWN</span>
        <span className="strip-sub">Derived strictly from human verification &amp; geographic validation</span>
      </div>
      <div className="category-strip-grid">
        {counts.map((item) => (
          <div key={item.id} className="category-chip">
            <span className="chip-icon" style={{ borderColor: item.color }}>
              {item.icon}
            </span>
            <div className="chip-info">
              <span className="chip-count" style={{ color: item.color }}>
                {item.count}
              </span>
              <span className="chip-label">{item.label}</span>
              <span className="chip-provenance">{item.provenance}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

