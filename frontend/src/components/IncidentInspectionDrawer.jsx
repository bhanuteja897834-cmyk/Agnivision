import React, { useState, useMemo } from "react";

function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function formatTime(value) {
  if (!value) return "N/A";
  const str = String(value).padStart(4, "0");
  const hh = str.slice(0, 2);
  const mm = str.slice(2, 4);
  return `${hh}:${mm} UTC`;
}

function confidenceLabel(value) {
  const v = String(value ?? "").trim().toLowerCase();
  if (v === "l" || v === "low") return "Low";
  if (v === "n" || v === "nominal") return "Nominal";
  if (v === "h" || v === "high") return "High";
  return "Nominal";
}

function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (v) => (v * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function formatDist(meters) {
  if (meters === null || meters === undefined || !Number.isFinite(meters)) return "N/A";
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(2)} km`;
  }
  return `${Math.round(meters)} m`;
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

export default function IncidentInspectionDrawer({
  selectedFire,
  fires = [],
  closeIncident,
  assets,
  loadingAssets = false,
  assetError = false,
  onZoomFacility,
  onOpenHistory,
  onOpenEvaluation
}) {
  const [selectedFacility, setSelectedFacility] = useState(null);
  const [showHistoryModal, setShowHistoryModal] = useState(false);

  const lat = num(selectedFire?.latitude, null);
  const lon = num(selectedFire?.longitude, null);

  // Calculate Observation ID from list index
  const obsIndex = useMemo(() => {
    if (!selectedFire || !fires.length) return 1;
    const idx = fires.findIndex(
      (f) =>
        f === selectedFire ||
        (f.latitude === selectedFire.latitude &&
          f.longitude === selectedFire.longitude &&
          f.acq_time === selectedFire.acq_time)
    );
    return idx >= 0 ? idx + 1 : 1;
  }, [selectedFire, fires]);

  const obsId = `OBS #${String(obsIndex).padStart(3, "0")}`;

  // Parse and calculate distance to nearby facilities
  const { facilities, nearestFacility } = useMemo(() => {
    const rawList = Array.isArray(assets?.assets) ? assets.assets : [];
    if (lat === null || lon === null || rawList.length === 0) {
      return { facilities: [], nearestFacility: null };
    }

    const calculated = rawList
      .map((a) => {
        const alat = num(a?.latitude, null);
        const alon = num(a?.longitude, null);
        const dist =
          alat !== null && alon !== null
            ? haversineMeters(lat, lon, alat, alon)
            : null;
        return {
          ...a,
          distanceMeters: dist
        };
      })
      .filter((a) => a.distanceMeters !== null)
      .sort((a, b) => a.distanceMeters - b.distanceMeters);

    return {
      facilities: calculated,
      nearestFacility: calculated[0] || null
    };
  }, [assets, lat, lon]);

  const counts = assets?.counts || {};
  const activeFacility = selectedFacility || nearestFacility;

  // Handle Zoom to Facility
  const handleZoom = () => {
    if (activeFacility && onZoomFacility) {
      onZoomFacility(activeFacility);
    }
  };

  if (!selectedFire) return null;

  // Geographic validation fields formatting
  const domain = selectedFire?.geographic_validation?.domain;
  const state = selectedFire?.geographic_validation?.state;
  const district = selectedFire?.geographic_validation?.district;
  const city = selectedFire?.geographic_validation?.city;
  const source =
    selectedFire?.geographic_validation?.source ||
    "NOAA GLOBE 1km Land Mask / Natural Earth";

  let displayDomain = "LAND";
  let displayState = state || "Not applicable";
  let displayDistrict = district || "Not applicable";
  let displayCity = city || "Not applicable";
  let displaySource = source;

  if (domain === "OFFSHORE_MARINE") {
    displayDomain = "OFFSHORE MARINE";
    displayState = "Not applicable";
    displayDistrict = "Not applicable";
    displayCity = "Not applicable";
    displaySource = "NOAA GLOBE 1km Land Mask";
  } else if (domain === "COASTAL_NEAR_SHORE") {
    displayDomain = "COASTAL NEAR-SHORE";
    displayState = "Not applicable";
    displayDistrict = "Not applicable";
    displayCity = "Not applicable";
  } else if (domain === "INLAND_WATER") {
    displayDomain = "INLAND WATER";
    displayState = state || "Not available";
    displayDistrict = district || "Not available";
    displayCity = city || "Not available";
  } else if (domain === "UNKNOWN_UNRESOLVED") {
    displayDomain = "UNKNOWN / UNRESOLVED";
    displayState = "Not available";
    displayDistrict = "Not available";
    displayCity = "Not available";
  }

  // Day/Night text
  const dayNightVal = selectedFire?.daynight ?? selectedFire?.day_night;
  const dayNightText =
    dayNightVal === "D"
      ? "Day"
      : dayNightVal === "N"
      ? "Night"
      : dayNightVal || "N/A";

  const riskLevelText = String(selectedFire?.risk_level || "Low");
  const rColor = riskColor(riskLevelText);

  return (
    <aside className="inspection-drawer" aria-label="Selected Observation Inspection">
      {/* 1. HEADER */}
      <div className="drawer-header">
        <div className="drawer-header-content">
          <span className="drawer-kicker">OBSERVATION / EVENT INSPECTION</span>
          <h2 className="drawer-title">Thermal Observation</h2>
          <span className="drawer-subbrand">NASA FIRMS · VIIRS NOAA-20</span>
          <div className="drawer-metadata-line">
            <span>{selectedFire?.acq_date || "N/A"}</span>
            <span className="meta-sep">·</span>
            <span>{formatTime(selectedFire?.acq_time)}</span>
            <span className="meta-sep">·</span>
            <span>
              {lat !== null ? lat.toFixed(5) : "—"},{" "}
              {lon !== null ? lon.toFixed(5) : "—"}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="drawer-close-btn"
          onClick={closeIncident}
          title="Close inspection"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {/* SCROLLABLE BODY */}
      <div className="drawer-body">
        {/* 2. SELECTED OBSERVATION SECTION */}
        <section className="drawer-section">
          <div className="section-head">
            <span className="section-title">SELECTED OBSERVATION</span>
          </div>
          <div className="two-column-list">
            <div className="table-row">
              <span className="row-label">Observation ID</span>
              <span className="row-value obs-id-val" style={{ fontFamily: "monospace", fontWeight: 700 }}>
                {selectedFire?.observation_id || obsId}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Event ID</span>
              <span className="row-value" style={{ fontWeight: 700, color: "#f97316", fontFamily: "monospace" }}>
                {selectedFire?.event_id || "Event ID unavailable"}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Acquisition date</span>
              <span className="row-value">{selectedFire?.acq_date || "N/A"}</span>
            </div>
            <div className="table-row">
              <span className="row-label">Acquisition time</span>
              <span className="row-value">{formatTime(selectedFire?.acq_time)}</span>
            </div>
            <div className="table-row">
              <span className="row-label">Latitude / Longitude</span>
              <span className="row-value">
                {lat !== null ? lat.toFixed(5) : "—"},{" "}
                {lon !== null ? lon.toFixed(5) : "—"}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Brightness</span>
              <span className="row-value">
                {selectedFire?.bright_ti4 ?? selectedFire?.brightness ?? "N/A"} K
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">FRP</span>
              <span className="row-value">
                {selectedFire?.frp !== undefined && selectedFire?.frp !== null
                  ? `${selectedFire.frp} MW`
                  : "N/A"}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Confidence</span>
              <span className="row-value">
                {confidenceLabel(
                  selectedFire?.confidence_label || selectedFire?.confidence
                )}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Persistence</span>
              <span className="row-value">
                {selectedFire?.persistence_days ?? 1} day
                {selectedFire?.persistence_days === 1 ? "" : "s"}
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Risk</span>
              <span className="row-value">
                <strong>{selectedFire?.risk_score ?? 0}</strong> / 100
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Risk level</span>
              <span className="row-value">
                <span
                  className="risk-tag"
                  style={{
                    color: rColor,
                    borderColor: rColor,
                    backgroundColor: rColor + "15"
                  }}
                >
                  {riskLevelText.toUpperCase()}
                </span>
              </span>
            </div>
            <div className="table-row">
              <span className="row-label">Satellite</span>
              <span className="row-value">{selectedFire?.satellite || "NOAA-20"}</span>
            </div>
            <div className="table-row">
              <span className="row-label">Instrument</span>
              <span className="row-value">{selectedFire?.instrument || "VIIRS"}</span>
            </div>
            <div className="table-row">
              <span className="row-label">Day / Night</span>
              <span className="row-value">{dayNightText}</span>
            </div>
          </div>
        </section>

        {/* 3. GEOGRAPHIC VALIDATION SECTION */}
        <section className="drawer-section">
          <div className="section-head">
            <span className="section-title">GEOGRAPHIC VALIDATION</span>
          </div>
          <div className="two-column-list">
            <div className="table-row">
              <span className="row-label">Domain</span>
              <span className="row-value domain-highlight">{displayDomain}</span>
            </div>
            <div className="table-row">
              <span className="row-label">State / UT</span>
              <span className="row-value">{displayState}</span>
            </div>
            <div className="table-row">
              <span className="row-label">District</span>
              <span className="row-value">{displayDistrict}</span>
            </div>
            <div className="table-row">
              <span className="row-label">City / Town</span>
              <span className="row-value">{displayCity}</span>
            </div>
            <div className="table-row">
              <span className="row-label">Validation source</span>
              <span className="row-value source-text">{displaySource}</span>
            </div>
          </div>
        </section>

        {/* 4. FACILITY CONTEXT SECTION */}
        <section className="drawer-section">
          <div className="section-head">
            <span className="section-title">FACILITY CONTEXT</span>
            {loadingAssets && <span className="section-pill">Querying OSM…</span>}
          </div>

          {loadingAssets ? (
            <div className="drawer-loading-msg">
              <span className="loading-dot" />
              <span>Querying OpenStreetMap infrastructure (5 km radius)…</span>
            </div>
          ) : assetError ? (
            <div className="drawer-error-msg">
              <span>⚠ OpenStreetMap Overpass context currently unavailable</span>
            </div>
          ) : (
            <>
              {/* Nearest / Selected Facility */}
              <div className="sub-header-row">
                <span>
                  {selectedFacility ? "Selected Facility" : "Nearest Facility"}
                </span>
                {selectedFacility && (
                  <button
                    type="button"
                    className="btn-link-reset"
                    onClick={() => setSelectedFacility(null)}
                  >
                    Reset to nearest
                  </button>
                )}
              </div>

              <div className="two-column-list">
                <div className="table-row">
                  <span className="row-label">Facility name</span>
                  <span className="row-value font-medium">
                    {activeFacility
                      ? activeFacility.name || "Unnamed industrial facility"
                      : "None identified within 5 km"}
                  </span>
                </div>
                {activeFacility && (
                  <>
                    <div className="table-row">
                      <span className="row-label">Facility type</span>
                      <span className="row-value type-tag">
                        {activeFacility.type || "Industrial"}
                      </span>
                    </div>
                    <div className="table-row">
                      <span className="row-label">Distance</span>
                      <span className="row-value highlight-dist">
                        {formatDist(activeFacility.distanceMeters)}
                      </span>
                    </div>
                    <div className="table-row">
                      <span className="row-label">Coordinates</span>
                      <span className="row-value">
                        {num(activeFacility.latitude).toFixed(5)},{" "}
                        {num(activeFacility.longitude).toFixed(5)}
                      </span>
                    </div>
                    <div className="table-row">
                      <span className="row-label">Source</span>
                      <span className="row-value">OpenStreetMap</span>
                    </div>
                  </>
                )}
              </div>

              {/* Nearby Infrastructure Summary */}
              <div className="sub-header-row" style={{ marginTop: "12px" }}>
                <span>Nearby Infrastructure (5 km)</span>
              </div>
              <div className="two-column-list">
                <div className="table-row">
                  <span className="row-label">Hospitals</span>
                  <span className="row-value">{counts.hospitals ?? 0}</span>
                </div>
                <div className="table-row">
                  <span className="row-label">Schools</span>
                  <span className="row-value">{counts.schools ?? 0}</span>
                </div>
                <div className="table-row">
                  <span className="row-label">Power</span>
                  <span className="row-value">{counts.power ?? 0}</span>
                </div>
                <div className="table-row">
                  <span className="row-label">Industrial</span>
                  <span className="row-value">{counts.industrial ?? 0}</span>
                </div>
                {counts.buildings !== undefined && (
                  <div className="table-row">
                    <span className="row-label">Buildings</span>
                    <span className="row-value">{counts.buildings}</span>
                  </div>
                )}
                {counts.roads !== undefined && (
                  <div className="table-row">
                    <span className="row-label">Roads</span>
                    <span className="row-value">{counts.roads}</span>
                  </div>
                )}
              </div>

              {/* Proximity Disclaimer */}
              <p className="facility-disclaimer-text">
                Facility proximity is contextual evidence only and does not establish causation.
              </p>
            </>
          )}
        </section>

        {/* 5. NEARBY FACILITIES LIST (IF MULTIPLE) */}
        {!loadingAssets && !assetError && facilities.length > 1 && (
          <section className="drawer-section">
            <div className="section-head">
              <span className="section-title">
                NEARBY FACILITIES ({facilities.length})
              </span>
            </div>
            <div className="facilities-compact-table">
              <div className="fac-table-header">
                <span className="col-name">Facility Name</span>
                <span className="col-type">Type</span>
                <span className="col-dist">Distance</span>
              </div>
              <div className="fac-table-rows">
                {facilities.slice(0, 15).map((fac, idx) => {
                  const isSelected = activeFacility === fac;
                  return (
                    <div
                      key={`fac-row-${idx}-${fac.latitude}-${fac.longitude}`}
                      className={`fac-compact-row ${isSelected ? "selected" : ""}`}
                      onClick={() => setSelectedFacility(fac)}
                      role="button"
                      tabIndex={0}
                      title="Click to inspect this facility"
                    >
                      <span className="col-name">
                        {fac.name || "Unnamed facility"}
                      </span>
                      <span className="col-type">{fac.type || "industrial"}</span>
                      <span className="col-dist">
                        {formatDist(fac.distanceMeters)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        )}
      </div>

      {/* THERMAL HISTORY MODAL / POPUP (IF CLICKED) */}
      {showHistoryModal && (
        <div className="history-modal-overlay" onClick={() => setShowHistoryModal(false)}>
          <div className="history-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-top">
              <strong>◷ Observation Temporal Record</strong>
              <button
                type="button"
                className="modal-close"
                onClick={() => setShowHistoryModal(false)}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="modal-info-row">
                <span>Acquisition Timestamp:</span>
                <strong>{selectedFire?.acq_date} · {formatTime(selectedFire?.acq_time)}</strong>
              </div>
              <div className="modal-info-row">
                <span>Active Window:</span>
                <strong>NASA FIRMS 10-Day NRT (Rolling)</strong>
              </div>
              <div className="modal-info-row">
                <span>Multi-year Archive:</span>
                <span className="badge-planned">Planned Ingestion</span>
              </div>
              <p className="modal-note">
                Long-term historical baselines (2012–Present archives) are planned for ingestion in a subsequent phase. AGNIVISION does not simulate or invent historical time series.
              </p>
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="btn-history-nav"
                onClick={() => {
                  setShowHistoryModal(false);
                  if (onOpenHistory) onOpenHistory(selectedFire?.event_id);
                }}
              >
                Open Full History Workspace ➔
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 6. FIXED ACTION BAR */}
      <div
        className="drawer-action-bar"
        style={{
          display: "grid",
          gridTemplateColumns: selectedFire?.event_id ? "1.2fr 1fr 1fr" : "1fr 1fr",
          gap: "6px"
        }}
      >
        {selectedFire?.event_id && (
          <button
            type="button"
            className="drawer-action-btn btn-eval-event"
            onClick={() => onOpenEvaluation && onOpenEvaluation(selectedFire.event_id)}
            style={{
              background: "#ea580c",
              color: "#ffffff",
              fontWeight: 700,
              borderColor: "#ea580c"
            }}
            title={`Evaluate persistent event ${selectedFire.event_id}`}
          >
            <span className="btn-icon">⚡</span>
            <span>Evaluate</span>
          </button>
        )}

        <button
          type="button"
          className="drawer-action-btn btn-history"
          onClick={() => {
            if (onOpenHistory) {
              onOpenHistory(selectedFire?.event_id);
            } else {
              setShowHistoryModal(true);
            }
          }}
          title="Inspect temporal history for this event"
        >
          <span className="btn-icon">◷</span>
          <span>History</span>
        </button>

        <button
          type="button"
          className="drawer-action-btn btn-zoom"
          onClick={handleZoom}
          disabled={!activeFacility}
          title={
            activeFacility
              ? `Zoom to ${activeFacility.name || "nearby facility"} (${formatDist(activeFacility.distanceMeters)})`
              : "No nearby facility available"
          }
        >
          <span className="btn-icon">⌖</span>
          <span>
            {activeFacility ? "Facility" : "No facility"}
          </span>
        </button>
      </div>
    </aside>
  );
}

