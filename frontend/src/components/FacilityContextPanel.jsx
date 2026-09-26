import React, { useState, useMemo } from "react";

function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (value) => (value * Math.PI) / 180;
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

export default function FacilityContextPanel({
  selectedFire,
  assets,
  loadingAssets = false,
  assetError = false
}) {
  const [activeFacility, setActiveFacility] = useState(null);

  const lat = Number(selectedFire?.latitude);
  const lon = Number(selectedFire?.longitude);

  // Parse and sort nearby facilities with computed distances
  const { industrialFacilities, nearestIndustrial, otherInfrastructure } = useMemo(() => {
    const rawList = Array.isArray(assets?.assets) ? assets.assets : [];
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || rawList.length === 0) {
      return {
        industrialFacilities: [],
        nearestIndustrial: null,
        otherInfrastructure: []
      };
    }

    const calculated = rawList
      .map((a) => {
        const alat = Number(a?.latitude);
        const alon = Number(a?.longitude);
        const dist =
          Number.isFinite(alat) && Number.isFinite(alon)
            ? haversineMeters(lat, lon, alat, alon)
            : null;
        return {
          ...a,
          distanceMeters: dist
        };
      })
      .sort((a, b) => (a.distanceMeters ?? Infinity) - (b.distanceMeters ?? Infinity));

    const industrials = calculated.filter(
      (a) => a.type === "industrial" || a.type === "power"
    );

    const nonIndustrials = calculated.filter(
      (a) => a.type !== "industrial" && a.type !== "power" && a.type !== "building"
    );

    return {
      industrialFacilities: industrials,
      nearestIndustrial: industrials[0] || null,
      otherInfrastructure: nonIndustrials
    };
  }, [assets, lat, lon]);

  const counts = assets?.counts || {
    industrial: 0,
    hospitals: 0,
    schools: 0,
    power: 0,
    roads: 0,
    buildings: 0
  };

  const displayedFacility = activeFacility || nearestIndustrial;

  return (
    <section className="inspection-section facility-context-section">
      <div className="section-title">
        <span>FACILITY CONTEXT</span>
        <small>{loadingAssets ? "LOADING" : "OSM 5KM"}</small>
      </div>

      {loadingAssets ? (
        <div className="asset-empty">
          <span className="spinner-dot" />
          Querying nearby OpenStreetMap infrastructure…
        </div>
      ) : assetError ? (
        <div className="data-unavailable compact">
          <span>⚠</span>
          <div>
            <strong>Facility data unavailable</strong>
            <p>Could not query OpenStreetMap Overpass servers for infrastructure context.</p>
          </div>
        </div>
      ) : (
        <div className="facility-context-body">
          {/* Proximity disclaimer */}
          <div className="context-evidence-note">
            <span>ℹ</span>
            <p>
              Facility proximity is <strong>contextual evidence only</strong>. Presence within 5 km does not establish causation of the thermal event.
            </p>
          </div>

          {/* Nearest Industrial Facility Card */}
          <div className="nearest-facility-card">
            <div className="nearest-card-head">
              <span className="nearest-icon">🏭</span>
              <div>
                <span className="nearest-kicker">NEAREST INDUSTRIAL FACILITY</span>
                <strong className="nearest-title">
                  {nearestIndustrial
                    ? nearestIndustrial.name || "Unnamed industrial facility"
                    : "No mapped industrial facilities within 5 km"}
                </strong>
              </div>
            </div>

            {nearestIndustrial ? (
              <div className="nearest-metrics-grid">
                <div className="f-metric">
                  <span>Distance:</span>
                  <strong>{formatDist(nearestIndustrial.distanceMeters)}</strong>
                </div>
                <div className="f-metric">
                  <span>Facility Type:</span>
                  <strong>{nearestIndustrial.type}</strong>
                </div>
                <div className="f-metric">
                  <span>Coordinates:</span>
                  <strong>
                    {Number(nearestIndustrial.latitude).toFixed(4)},{" "}
                    {Number(nearestIndustrial.longitude).toFixed(4)}
                  </strong>
                </div>
              </div>
            ) : (
              <div className="no-facility-msg">
                Zero mapped industrial sites or power facilities returned within a 5 km buffer.
              </div>
            )}
          </div>

          {/* Nearby Critical Infrastructure Summary */}
          <div className="critical-infra-summary">
            <span className="sub-section-title">NEARBY CRITICAL INFRASTRUCTURE (5 KM)</span>
            <div className="infra-pills-grid">
              <div className="infra-pill">
                <span className="infra-icon">✚</span>
                <div>
                  <strong>{counts.hospitals}</strong>
                  <small>Hospitals</small>
                </div>
              </div>
              <div className="infra-pill">
                <span className="infra-icon">⌂</span>
                <div>
                  <strong>{counts.schools}</strong>
                  <small>Schools</small>
                </div>
              </div>
              <div className="infra-pill">
                <span className="infra-icon">ϟ</span>
                <div>
                  <strong>{counts.power}</strong>
                  <small>Power Sites</small>
                </div>
              </div>
              <div className="infra-pill">
                <span className="infra-icon">═</span>
                <div>
                  <strong>{counts.roads}</strong>
                  <small>Major Roads</small>
                </div>
              </div>
            </div>
          </div>

          {/* Nearby Relevant Facilities List (Clickable) */}
          {industrialFacilities.length > 0 && (
            <div className="nearby-facilities-list-group">
              <span className="sub-section-title">
                POTENTIALLY RELEVANT FACILITIES ({industrialFacilities.length})
              </span>
              <div className="facilities-scroll-list">
                {industrialFacilities.map((fac, idx) => {
                  const isSelected = displayedFacility === fac;
                  return (
                    <div
                      key={`fac-${idx}-${fac.latitude}-${fac.longitude}`}
                      className={`facility-item-row ${isSelected ? "selected" : ""}`}
                      onClick={() => setActiveFacility(fac)}
                    >
                      <div className="fac-info">
                        <strong>{fac.name || "Unnamed facility"}</strong>
                        <small>{fac.type} • {formatDist(fac.distanceMeters)} away</small>
                      </div>
                      <span className="select-arrow">{isSelected ? "●" : "○"}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Detailed Selected Facility View */}
          {displayedFacility && (
            <div className="facility-details-card">
              <div className="fac-details-head">
                <span className="fac-tag">FACILITY DETAILS</span>
                <strong>{displayedFacility.name || "Unnamed Mapped Facility"}</strong>
              </div>

              <div className="fac-attr-list">
                <div className="fac-attr-row">
                  <span>Type / Category:</span>
                  <strong>{displayedFacility.type || "Industrial"}</strong>
                </div>
                <div className="fac-attr-row">
                  <span>Coordinates:</span>
                  <strong>
                    {Number(displayedFacility.latitude).toFixed(5)},{" "}
                    {Number(displayedFacility.longitude).toFixed(5)}
                  </strong>
                </div>
                <div className="fac-attr-row">
                  <span>Distance from Hotspot:</span>
                  <strong>{formatDist(displayedFacility.distanceMeters)}</strong>
                </div>
                <div className="fac-attr-row">
                  <span>Source:</span>
                  <strong>OpenStreetMap contributors (ODbL)</strong>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

