import React, { useMemo } from "react";

export default function ThermalOverview({ fires = [] }) {
  const stats = useMemo(() => {
    if (!fires || fires.length === 0) return null;

    let frpSum = 0;
    let frpCount = 0;
    let minFrp = Infinity;
    let maxFrp = -Infinity;

    let bSum = 0;
    let bCount = 0;
    let minBrightness = Infinity;
    let maxBrightness = -Infinity;

    let confHigh = 0;
    let confNominal = 0;
    let confLow = 0;
    let confOther = 0;

    for (const f of fires) {
      const frpVal = Number(f?.frp);
      if (Number.isFinite(frpVal) && frpVal >= 0) {
        frpSum += frpVal;
        frpCount++;
        if (frpVal < minFrp) minFrp = frpVal;
        if (frpVal > maxFrp) maxFrp = frpVal;
      }

      const bVal = Number(f?.bright_ti4 || f?.brightness);
      if (Number.isFinite(bVal) && bVal > 0) {
        bSum += bVal;
        bCount++;
        if (bVal < minBrightness) minBrightness = bVal;
        if (bVal > maxBrightness) maxBrightness = bVal;
      }

      const c = String(f?.confidence || f?.confidence_label || "").trim().toLowerCase();
      if (c === "h" || c === "high") {
        confHigh++;
      } else if (c === "n" || c === "nominal") {
        confNominal++;
      } else if (c === "l" || c === "low") {
        confLow++;
      } else {
        confOther++;
      }
    }

    return {
      total: fires.length,
      avgFrp: frpCount > 0 ? (frpSum / frpCount).toFixed(2) : "—",
      minFrp: minFrp !== Infinity ? minFrp.toFixed(2) : "—",
      maxFrp: maxFrp !== -Infinity ? maxFrp.toFixed(2) : "—",
      avgBrightness: bCount > 0 ? (bSum / bCount).toFixed(1) : "—",
      minBrightness: minBrightness !== Infinity ? minBrightness.toFixed(1) : "—",
      maxBrightness: maxBrightness !== -Infinity ? maxBrightness.toFixed(1) : "—",
      confHigh,
      confNominal,
      confLow,
      confOther,
      highPct: fires.length > 0 ? ((confHigh / fires.length) * 100).toFixed(1) : "0",
      nominalPct: fires.length > 0 ? ((confNominal / fires.length) * 100).toFixed(1) : "0",
      lowPct: fires.length > 0 ? ((confLow / fires.length) * 100).toFixed(1) : "0"
    };
  }, [fires]);

  if (!stats) {
    return (
      <div className="dashboard-panel">
        <div className="panel-title-row">
          <h3>Thermal Activity Overview</h3>
          <span className="window-pill">Current FIRMS observation window</span>
        </div>
        <div className="panel-empty-state">No thermal observations in current query window.</div>
      </div>
    );
  }

  return (
    <div className="dashboard-panel thermal-overview-panel">
      <div className="panel-title-row">
        <div>
          <h3>Thermal Activity Overview</h3>
          <p className="panel-subtitle">
            Aggregated statistics derived directly from current VIIRS NOAA-20 NRT observations
          </p>
        </div>
        <span className="window-pill">Current FIRMS observation window</span>
      </div>

      <div className="thermal-stats-grid">
        {/* Fire Radiative Power */}
        <div className="stat-card">
          <div className="stat-label">FIRE RADIATIVE POWER (FRP)</div>
          <div className="stat-main-metric">
            <span className="stat-big-val">{stats.avgFrp}</span>
            <span className="stat-unit">MW avg</span>
          </div>
          <div className="stat-sub-metrics">
            <span>Min: <strong>{stats.minFrp} MW</strong></span>
            <span>•</span>
            <span>Max: <strong>{stats.maxFrp} MW</strong></span>
          </div>
        </div>

        {/* Brightness Temperature */}
        <div className="stat-card">
          <div className="stat-label">BRIGHTNESS TEMPERATURE (4µm)</div>
          <div className="stat-main-metric">
            <span className="stat-big-val">{stats.avgBrightness}</span>
            <span className="stat-unit">K avg</span>
          </div>
          <div className="stat-sub-metrics">
            <span>Min: <strong>{stats.minBrightness} K</strong></span>
            <span>•</span>
            <span>Max: <strong>{stats.maxBrightness} K</strong></span>
          </div>
        </div>

        {/* Confidence Breakdown */}
        <div className="stat-card">
          <div className="stat-label">OBSERVATION CONFIDENCE</div>
          <div className="confidence-bars">
            <div className="conf-bar-row">
              <span className="conf-name">Nominal</span>
              <div className="bar-track">
                <div
                  className="bar-fill nominal-fill"
                  style={{ width: `${stats.nominalPct}%` }}
                />
              </div>
              <span className="conf-val">{stats.confNominal} ({stats.nominalPct}%)</span>
            </div>

            <div className="conf-bar-row">
              <span className="conf-name">High</span>
              <div className="bar-track">
                <div
                  className="bar-fill high-fill"
                  style={{ width: `${stats.highPct}%` }}
                />
              </div>
              <span className="conf-val">{stats.confHigh} ({stats.highPct}%)</span>
            </div>

            <div className="conf-bar-row">
              <span className="conf-name">Low</span>
              <div className="bar-track">
                <div
                  className="bar-fill low-fill"
                  style={{ width: `${stats.lowPct}%` }}
                />
              </div>
              <span className="conf-val">{stats.confLow} ({stats.lowPct}%)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

