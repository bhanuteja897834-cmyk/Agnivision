import React, { useEffect, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap
} from "react-leaflet";

import IncidentInspectionDrawer from "./IncidentInspectionDrawer";

function MapViewport({ selectedFire }) {
  const map = useMap();

  useEffect(() => {
    if (!selectedFire) return;

    const lat = Number(selectedFire.latitude);
    const lon = Number(selectedFire.longitude);

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    map.flyTo([lat, lon], Math.max(map.getZoom(), 11), {
      duration: 0.7
    });
  }, [selectedFire, map]);

  useEffect(() => {
    const handleSearch = (event) => {
      const lat = Number(event?.detail?.lat);
      const lon = Number(event?.detail?.lon);

      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

      map.flyTo([lat, lon], 12, {
        duration: 0.7
      });
    };

    const handleZoomFacility = (event) => {
      const lat = Number(event?.detail?.lat);
      const lon = Number(event?.detail?.lon);
      const zoom = Number(event?.detail?.zoom) || 16;

      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

      map.flyTo([lat, lon], zoom, {
        duration: 0.8
      });
    };

    window.addEventListener("agnivision-search-coordinate", handleSearch);
    window.addEventListener("agnivision-zoom-facility", handleZoomFacility);
    return () => {
      window.removeEventListener("agnivision-search-coordinate", handleSearch);
      window.removeEventListener("agnivision-zoom-facility", handleZoomFacility);
    };
  }, [map]);

  return null;
}

export default function GeoMap({
  fires = [],
  filteredFires = [],
  selectedFire,
  selectIncident,
  closeIncident,
  assets,
  loadingAssets,
  assetError,
  baseLayer,
  setBaseLayer,
  layers,
  setLayers,
  eventFilters,
  setEventFilters,
  verification,
  setVerification,
  _verifiedLabel,
  _verifyingEvent,
  _verificationMessage,
  _verifySelectedEvent,
  criticalCount,
  highCount,
  persistentCount,
  helpers,
  dataMode = "india",
  setDataMode,
  onOpenEvaluation,
  onOpenTemporal
}) {
  const {
    num,
    riskColor,
    riskClass,
    _confidenceLabel,
    formatTime,
    assetLabel,
    assetIcon,
    assetColor
  } = helpers;

  const [highlightedFacility, setHighlightedFacility] = useState(null);

  useEffect(() => {
    setHighlightedFacility(null);
  }, [selectedFire]);

  const handleZoomFacility = (facility) => {
    setHighlightedFacility(facility);
    window.dispatchEvent(
      new CustomEvent("agnivision-zoom-facility", {
        detail: {
          lat: facility.latitude,
          lon: facility.longitude,
          zoom: 16
        }
      })
    );
  };

  const handleOpenHistory = () => {
    window.dispatchEvent(
      new CustomEvent("agnivision-navigate-tab", {
        detail: "history"
      })
    );
  };

  return (
    <main className="map-shell">
      <MapContainer
        center={[22.5, 79.0]}
        zoom={5}
        minZoom={4}
        zoomControl={true}
        className="map"
      >
        <MapViewport selectedFire={selectedFire} />

        {baseLayer === "standard" ? (
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
        ) : (
          <TileLayer
            attribution="Tiles &copy; Esri"
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          />
        )}

        {/* PROXIMITY ZONES */}
        {selectedFire &&
          layers.zones &&
          [5000, 2500, 1000].map((radius, index) => {
            const colors = ["#16a34a", "#ea580c", "#dc2626"];
            return (
              <Circle
                key={`zone-${radius}`}
                center={[num(selectedFire.latitude), num(selectedFire.longitude)]}
                radius={radius}
                pathOptions={{
                  color: colors[index],
                  fillColor: colors[index],
                  fillOpacity: 0.025,
                  weight: 2
                }}
              />
            );
          })}

        {/* OVERPASS ASSET MARKERS */}
        {selectedFire &&
          assets?.assets?.map((asset, index) => {
            const lat = num(asset?.latitude, null);
            const lon = num(asset?.longitude, null);
            if (lat === null || lon === null) return null;

            const type = String(asset?.type || "").toLowerCase();
            const visible =
              (type === "building" && layers.architecture) ||
              (type === "industrial" && layers.industrial) ||
              (type === "hospital" && layers.hospitals) ||
              (type === "school" && layers.schools) ||
              (type === "power" && layers.power) ||
              (type === "road" && layers.roads);

            if (!visible) return null;

            const color = assetColor(type);
            const isBuilding = type === "building";

            return (
              <CircleMarker
                key={`asset-${index}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={isBuilding ? 3 : 6}
                pathOptions={{
                  color,
                  fillColor: color,
                  fillOpacity: isBuilding ? 0.35 : 0.85,
                  weight: isBuilding ? 1 : 2
                }}
              >
                <Popup>
                  <div className="map-popup asset-popup">
                    <div className="popup-kicker">
                      {assetIcon(type)} {assetLabel(type)}
                    </div>
                    <strong>{asset?.name || "Unnamed mapped asset"}</strong>
                    <div className="popup-muted">
                      {lat.toFixed(5)}, {lon.toFixed(5)}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

        {/* FIRMS EVENTS */}
        {layers.thermal &&
          filteredFires.map((fire, index) => {
            const lat = num(fire?.latitude, null);
            const lon = num(fire?.longitude, null);
            if (lat === null || lon === null) return null;

            const level = fire?.risk_level || "Low";
            const color = riskColor(level);
            const selected = selectedFire === fire;

            return (
              <CircleMarker
                key={`fire-${index}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={selected ? 11 : 7}
                pathOptions={{
                  color: selected ? "#ffffff" : color,
                  fillColor: color,
                  fillOpacity: 0.95,
                  weight: selected ? 3 : 2
                }}
                eventHandlers={{
                  click: () => selectIncident(fire)
                }}
              >
                <Popup>
                  <div className="map-popup fire-popup">
                    <div className="popup-title-row">
                      <strong>🔥 Thermal Observation</strong>
                      <span className={`risk-chip ${riskClass(level)}`}>
                        {String(level).toUpperCase()}
                      </span>
                    </div>

                    <div className="popup-divider" />

                    <div className="popup-data-row">
                      <span>Observation ID</span>
                      <strong style={{ fontFamily: "monospace" }}>{fire?.observation_id || "N/A"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Event ID</span>
                      <strong style={{ color: "#f97316", fontFamily: "monospace" }}>{fire?.event_id || "N/A"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Domain</span>
                      <strong>{fire?.geographic_validation?.domain || "LAND"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>State</span>
                      <strong>{fire?.geographic_validation?.state || "N/A"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Risk score</span>
                      <strong>{fire?.risk_score ?? 0}/100</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Brightness</span>
                      <strong>{fire?.bright_ti4 ?? fire?.brightness ?? "N/A"} K</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>FRP</span>
                      <strong>{fire?.frp ?? "N/A"} MW</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Persistence</span>
                      <strong>{fire?.persistence_days ?? 1} day(s)</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Acquired</span>
                      <strong>
                        {fire?.acq_date || "N/A"} {formatTime(fire?.acq_time)}
                      </strong>
                    </div>

                    <div className="popup-coordinates">
                      📍 {lat.toFixed(4)}, {lon.toFixed(4)}
                    </div>

                    <div style={{ display: "flex", gap: "6px", marginTop: "8px" }}>
                      <button
                        className="popup-action"
                        onClick={() => selectIncident(fire)}
                        style={{ flex: 1 }}
                      >
                        INSPECT
                      </button>
                      {fire?.event_id && onOpenEvaluation && (
                        <button
                          className="popup-action"
                          onClick={() => onOpenEvaluation(fire.event_id)}
                          style={{
                            flex: 1,
                            background: "#ea580c",
                            color: "#ffffff",
                            borderColor: "#ea580c",
                            fontWeight: 700
                          }}
                        >
                          EVALUATE
                        </button>
                      )}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

        {/* HIGHLIGHTED FACILITY (WHEN ZOOMED TO FACILITY) */}
        {highlightedFacility &&
          Number.isFinite(Number(highlightedFacility.latitude)) &&
          Number.isFinite(Number(highlightedFacility.longitude)) && (
            <CircleMarker
              center={[
                Number(highlightedFacility.latitude),
                Number(highlightedFacility.longitude)
              ]}
              radius={12}
              pathOptions={{
                color: "#0284c7",
                fillColor: "#38bdf8",
                fillOpacity: 0.85,
                weight: 3
              }}
            >
              <Popup>
                <div className="map-popup facility-popup">
                  <div className="popup-title-row">
                    <strong>🏢 Mapped Facility</strong>
                    <span className="risk-chip low">
                      {(highlightedFacility.type || "Industrial").toUpperCase()}
                    </span>
                  </div>
                  <div className="popup-divider" />
                  <div className="popup-data-row">
                    <span>Name:</span>
                    <strong>{highlightedFacility.name || "Unnamed facility"}</strong>
                  </div>
                  <div className="popup-data-row">
                    <span>Coordinates:</span>
                    <strong>
                      {Number(highlightedFacility.latitude).toFixed(5)},{" "}
                      {Number(highlightedFacility.longitude).toFixed(5)}
                    </strong>
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          )}
      </MapContainer>

      {/* LEFT SIDEBAR */}
      <aside className="left-sidebar">
        <section className="control-panel">
          <div className="panel-heading">
            <span>FIRMS REGION</span>
            <span
              className="panel-status"
              style={{
                background: dataMode === "india" ? "rgba(34, 197, 94, 0.15)" : "rgba(56, 189, 248, 0.15)",
                color: dataMode === "india" ? "#16a34a" : "#0284c7",
                fontWeight: 700
              }}
            >
              {dataMode === "india" ? "ALL-INDIA" : "DEMO"}
            </span>
          </div>

          <label className="layer-row">
            <input
              type="radio"
              name="mapCoverageSelect"
              checked={dataMode === "india"}
              onChange={() => setDataMode && setDataMode("india")}
            />
            <span>All-India Coverage</span>
            <em style={{ color: "#16a34a", fontWeight: 700 }}>
              {dataMode === "india" ? fires.length : 2301}
            </em>
          </label>

          <label className="layer-row">
            <input
              type="radio"
              name="mapCoverageSelect"
              checked={dataMode === "eastern_india"}
              onChange={() => setDataMode && setDataMode("eastern_india")}
            />
            <span>Eastern India Demo</span>
            <em style={{ color: "#0284c7", fontWeight: 700 }}>
              {dataMode === "eastern_india" ? fires.length : 918}
            </em>
          </label>
        </section>

        <section className="control-panel">
          <div className="panel-heading">
            <span>MAP LAYERS</span>
            <span className="panel-status">LIVE</span>
          </div>

          <label className="layer-row">
            <input
              type="radio"
              checked={baseLayer === "standard"}
              onChange={() => setBaseLayer("standard")}
            />
            <span>Standard Map</span>
          </label>

          <label className="layer-row">
            <input
              type="radio"
              checked={baseLayer === "satellite"}
              onChange={() => setBaseLayer("satellite")}
            />
            <span>Satellite Imagery</span>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.thermal}
              onChange={() => setLayers((s) => ({ ...s, thermal: !s.thermal }))}
            />
            <span>Thermal Activity</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.zones}
              onChange={() => setLayers((s) => ({ ...s, zones: !s.zones }))}
            />
            <span>Risk / Proximity Zones</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.industrial}
              onChange={() =>
                setLayers((s) => ({ ...s, industrial: !s.industrial }))
              }
            />
            <span>Industrial Facilities</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.architecture}
              onChange={() =>
                setLayers((s) => ({ ...s, architecture: !s.architecture }))
              }
            />
            <span>Facility Architecture</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.roads}
              onChange={() => setLayers((s) => ({ ...s, roads: !s.roads }))}
            />
            <span>Roads</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.hospitals}
              onChange={() =>
                setLayers((s) => ({ ...s, hospitals: !s.hospitals }))
              }
            />
            <span>Hospitals</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.schools}
              onChange={() => setLayers((s) => ({ ...s, schools: !s.schools }))}
            />
            <span>Schools</span>
            <em>READY</em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.power}
              onChange={() => setLayers((s) => ({ ...s, power: !s.power }))}
            />
            <span>Power Infrastructure</span>
            <em>READY</em>
          </label>
        </section>

        <section className="control-panel">
          <div className="panel-heading">
            <span>RISK LEVEL FILTERS</span>
          </div>

          <label className="filter-row">
            <input
              type="checkbox"
              checked={eventFilters.critical}
              onChange={() =>
                setEventFilters((s) => ({ ...s, critical: !s.critical }))
              }
            />
            <span className="category-dot" style={{ background: "#dc2626" }} />
            <span>Critical risk events</span>
          </label>

          <label className="filter-row">
            <input
              type="checkbox"
              checked={eventFilters.high}
              onChange={() =>
                setEventFilters((s) => ({ ...s, high: !s.high }))
              }
            />
            <span className="category-dot" style={{ background: "#ea580c" }} />
            <span>High-risk events</span>
          </label>

          <label className="filter-row">
            <input
              type="checkbox"
              checked={eventFilters.moderate}
              onChange={() =>
                setEventFilters((s) => ({ ...s, moderate: !s.moderate }))
              }
            />
            <span className="category-dot" style={{ background: "#d97706" }} />
            <span>Moderate events</span>
          </label>

          <label className="filter-row">
            <input
              type="checkbox"
              checked={eventFilters.low}
              onChange={() =>
                setEventFilters((s) => ({ ...s, low: !s.low }))
              }
            />
            <span className="category-dot" style={{ background: "#16a34a" }} />
            <span>Low-risk events</span>
          </label>
        </section>

        <section className="control-panel">
          <div className="panel-heading">
            <span>VERIFICATION STATUS</span>
          </div>

          {["NEW", "UNDER REVIEW", "NEEDS VERIFICATION", "CONFIRMED"].map(
            (status) => (
              <label className="radio-row" key={status}>
                <input
                  type="radio"
                  checked={verification === status}
                  onChange={() => setVerification(status)}
                />
                <span>{status}</span>
              </label>
            )
          )}
        </section>

        <section className="monitor-strip">
          <div>
            <strong>{fires.length}</strong>
            <span>EVENTS</span>
          </div>
          <div>
            <strong>{criticalCount}</strong>
            <span>CRITICAL</span>
          </div>
          <div>
            <strong>{highCount}</strong>
            <span>HIGH</span>
          </div>
          <div>
            <strong>{persistentCount}</strong>
            <span>PERSISTENT</span>
          </div>
        </section>
      </aside>

      {/* RIGHT INSPECTION DRAWER */}
      {selectedFire && (
        <IncidentInspectionDrawer
          selectedFire={selectedFire}
          fires={fires}
          closeIncident={() => {
            setHighlightedFacility(null);
            closeIncident();
          }}
          assets={assets}
          loadingAssets={loadingAssets}
          assetError={assetError}
          onZoomFacility={handleZoomFacility}
          onOpenHistory={(eventId) => {
            if (onOpenTemporal) {
              onOpenTemporal(eventId || selectedFire?.event_id);
            } else {
              handleOpenHistory();
            }
          }}
          onOpenEvaluation={(eventId) => {
            if (onOpenEvaluation) {
              onOpenEvaluation(eventId || selectedFire?.event_id);
            }
          }}
        />
      )}

      {/* MAP STATUS STRIP */}
      <div className="map-status">
        <span>
          FIRMS / VIIRS NOAA-20 NRT •{" "}
          {dataMode === "india" ? "INDIA-WIDE" : "EASTERN INDIA DEMO"}
        </span>
        <span>•</span>
        <span>{fires.length} OBSERVATIONS</span>
        <span>•</span>
        <span>
          {dataMode === "india" ? "67°E–98°E, 7°N–38°N" : "82°E–90°E, 20°N–27°N"}
        </span>
        <span>•</span>
        <span>NOAA 1KM &amp; NATURAL EARTH DOMAINS</span>
        <span>•</span>
        <span>OPENSTREETMAP CONTEXT</span>
      </div>
    </main>
  );
}

