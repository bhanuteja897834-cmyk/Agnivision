import React, { useState, useMemo } from "react";

function formatTime(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const s = String(value).trim().padStart(4, "0");
  if (/^\d{4}$/.test(s)) {
    return `${s.slice(0, 2)}:${s.slice(2, 4)} UTC`;
  }
  return String(value);
}

function riskColor(level) {
  switch (String(level || "").toLowerCase()) {
    case "critical":
      return "#dc2626";
    case "high":
      return "#ea580c";
    case "moderate":
      return "#d97706";
    default:
      return "#16a34a";
  }
}

function riskClass(level) {
  switch (String(level || "").toLowerCase()) {
    case "critical":
      return "critical";
    case "high":
      return "high";
    case "moderate":
      return "moderate";
    default:
      return "low";
  }
}

export default function ThermalEventTable({
  fires = [],
  onSelectObservation,
  selectedFire
}) {
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [filterState, setFilterState] = useState("ALL");
  const [filterRisk, setFilterRisk] = useState("ALL");
  const [filterDomain, setFilterDomain] = useState("ALL");

  // Extract available filter values
  const availableStates = useMemo(() => {
    const s = new Set();
    for (const f of fires) {
      const st = f?.geographic_validation?.state;
      if (st && st !== "Not applicable") s.add(st);
    }
    return Array.from(s).sort();
  }, [fires]);

  const filteredFires = useMemo(() => {
    return fires.filter((f) => {
      if (filterState !== "ALL" && f?.geographic_validation?.state !== filterState) {
        return false;
      }
      if (filterRisk !== "ALL" && f?.risk_level !== filterRisk) {
        return false;
      }
      if (filterDomain !== "ALL" && f?.geographic_validation?.domain !== filterDomain) {
        return false;
      }
      return true;
    });
  }, [fires, filterState, filterRisk, filterDomain]);

  const totalPages = Math.ceil(filteredFires.length / pageSize) || 1;
  const currentPage = Math.min(page, totalPages);
  const startIndex = (currentPage - 1) * pageSize;
  const paginatedFires = filteredFires.slice(startIndex, startIndex + pageSize);

  return (
    <div className="dashboard-panel thermal-table-panel">
      <div className="panel-title-row">
        <div>
          <h3>Recent Thermal Observations</h3>
          <p className="panel-subtitle">
            Individual satellite detections from NASA VIIRS NOAA-20 (No synthetic clustering applied)
          </p>
        </div>
        <div className="table-filter-toolbar">
          <select
            value={filterState}
            onChange={(e) => {
              setFilterState(e.target.value);
              setPage(1);
            }}
            className="table-filter-select"
          >
            <option value="ALL">All States ({availableStates.length})</option>
            {availableStates.map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>

          <select
            value={filterRisk}
            onChange={(e) => {
              setFilterRisk(e.target.value);
              setPage(1);
            }}
            className="table-filter-select"
          >
            <option value="ALL">All Risk Levels</option>
            <option value="Critical">Critical</option>
            <option value="High">High</option>
            <option value="Moderate">Moderate</option>
            <option value="Low">Low</option>
          </select>

          <select
            value={filterDomain}
            onChange={(e) => {
              setFilterDomain(e.target.value);
              setPage(1);
            }}
            className="table-filter-select"
          >
            <option value="ALL">All Domains</option>
            <option value="LAND">LAND</option>
            <option value="INLAND_WATER">INLAND WATER</option>
            <option value="COASTAL_NEAR_SHORE">COASTAL</option>
            <option value="OFFSHORE_MARINE">MARINE</option>
          </select>
        </div>
      </div>

      <div className="table-responsive">
        <table className="observation-table">
          <thead>
            <tr>
              <th>Observation</th>
              <th>Location</th>
              <th>State</th>
              <th>Domain</th>
              <th>FRP</th>
              <th>Brightness</th>
              <th>Confidence</th>
              <th>Risk</th>
              <th>Acquisition Time</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {paginatedFires.length === 0 ? (
              <tr>
                <td colSpan="10" className="table-empty-cell">
                  No observations match the selected criteria.
                </td>
              </tr>
            ) : (
              paginatedFires.map((fire, idx) => {
                const globalIndex = startIndex + idx + 1;
                const isSelected = selectedFire === fire;
                const lat = Number(fire?.latitude);
                const lon = Number(fire?.longitude);
                const geo = fire?.geographic_validation;
                const level = fire?.risk_level || "Low";

                return (
                  <tr
                    key={`obs-${globalIndex}-${fire?.latitude}-${fire?.longitude}-${fire?.acq_time}`}
                    className={`observation-row ${isSelected ? "selected-row" : ""}`}
                    onClick={() => onSelectObservation && onSelectObservation(fire)}
                  >
                    <td>
                      <span className="obs-tag">
                        Obs #{String(globalIndex).padStart(3, "0")}
                      </span>
                    </td>
                    <td>
                      <span className="coord-text">
                        {Number.isFinite(lat) ? lat.toFixed(4) : "—"},{" "}
                        {Number.isFinite(lon) ? lon.toFixed(4) : "—"}
                      </span>
                    </td>
                    <td>
                      <span className="state-cell">
                        {geo?.state || "Unassigned"}
                      </span>
                    </td>
                    <td>
                      <span className={`domain-chip chip-${geo?.domain || "UNKNOWN"}`}>
                        {geo?.domain || "UNKNOWN"}
                      </span>
                    </td>
                    <td>
                      <strong>{fire?.frp ?? "—"}</strong>{" "}
                      <span className="unit-label">MW</span>
                    </td>
                    <td>
                      <span>{fire?.bright_ti4 ?? fire?.brightness ?? "—"} K</span>
                    </td>
                    <td>
                      <span className="conf-cell">
                        {fire?.confidence_label || fire?.confidence || "—"}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`risk-badge-cell ${riskClass(level)}`}
                        style={{ color: riskColor(level) }}
                      >
                        {level} ({fire?.risk_score ?? 0})
                      </span>
                    </td>
                    <td>
                      <span className="time-cell">
                        {fire?.acq_date || "N/A"}{" "}
                        <small>{formatTime(fire?.acq_time)}</small>
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="inspect-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onSelectObservation) onSelectObservation(fire);
                        }}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="table-pagination-footer">
        <span className="pagination-info">
          Showing <strong>{paginatedFires.length > 0 ? startIndex + 1 : 0}</strong> to{" "}
          <strong>{Math.min(startIndex + pageSize, filteredFires.length)}</strong> of{" "}
          <strong>{filteredFires.length}</strong> observations
        </span>

        <div className="pagination-controls">
          <button
            type="button"
            className="page-btn"
            disabled={currentPage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <span className="page-current">
            Page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            className="page-btn"
            disabled={currentPage >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

