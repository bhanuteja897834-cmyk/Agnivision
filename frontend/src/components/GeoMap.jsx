import React, { useEffect, useState, useMemo } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap
} from "react-leaflet";

import IncidentInspectionDrawer from "./IncidentInspectionDrawer";
import TemporalFirmsControl from "./TemporalFirmsControl";
import { useFIRMSHotspots } from "../hooks/useFIRMSHotspots";

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

  useEffect(() => {
    if (!map) return;
    const timer = setTimeout(() => map.invalidateSize(), 200);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

export default function GeoMap({
  fires = [],
  filteredFires = [],
  dateRange,
  setDateRange,
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

  const {
    hotspots: firmsHotspots,
    clusters: firmsClusters,
    total: firmsTotal,
    loading: firmsLoading,
    error: firmsError,
    startDate: firmsStartDate,
    endDate: firmsEndDate,
    playbackDate: firmsPlaybackDate,
    playbackDates: firmsPlaybackDates,
    isPlaying: firmsIsPlaying,
    togglePlay: toggleFirmsPlay,
    nextDay: nextFirmsDay,
    prevDay: prevFirmsDay,
    setPlaybackDate: setFirmsPlaybackDate,
    activePreset: firmsPreset,
    selectPreset: selectFirmsPreset,
    applyCustomRange: applyFirmsCustomRange,
    retry: retryFirms,
    validationError: firmsValidationError
  } = useFIRMSHotspots({
    initialPreset: dateRange?.preset || "10D",
    externalDateRange: dateRange
  });

  // Sync dateRange back to top-level React state when modified via Geo Map controls
  useEffect(() => {
    if (
      setDateRange &&
      firmsStartDate &&
      firmsEndDate &&
      (firmsStartDate !== dateRange?.startDate ||
        firmsEndDate !== dateRange?.endDate ||
        (firmsPreset && firmsPreset !== dateRange?.preset))
    ) {
      setDateRange({
        preset: firmsPreset,
        startDate: firmsStartDate,
        endDate: firmsEndDate
      });
    }
  }, [firmsStartDate, firmsEndDate, firmsPreset, dateRange?.startDate, dateRange?.endDate, dateRange?.preset, setDateRange]);

  // SINGLE SOURCE OF TRUTH: Filter clustered thermal incidents strictly by active playback/range date
  const activeClusteredFires = useMemo(() => {
    const targetDate = firmsPlaybackDate || firmsStartDate;
    if (!targetDate) return [];
    return (filteredFires || []).filter((f) => {
      const d = f?.acq_date;
      if (!d) return false;
      return d === targetDate;
    });
  }, [filteredFires, firmsPlaybackDate, firmsStartDate]);

  const activeCriticalCount = useMemo(
    () => activeClusteredFires.filter((f) => riskClass(f?.risk_level) === "critical").length,
    [activeClusteredFires, riskClass]
  );

  const activeHighCount = useMemo(
    () => activeClusteredFires.filter((f) => riskClass(f?.risk_level) === "high").length,
    [activeClusteredFires, riskClass]
  );

  const activePersistentCount = useMemo(
    () => activeClusteredFires.filter((f) => num(f?.persistence_days, 1) >= 2).length,
    [activeClusteredFires, num]
  );

  const [showFIRMSHotspots, setShowFIRMSHotspots] = useState(true);
  const [showFIRMSClusters, setShowFIRMSClusters] = useState(true);

  const [highlightedFacility, setHighlightedFacility] = useState(null);

  useEffect(() => {
    setHighlightedFacility(null);
  }, [selectedFire]);

  useEffect(() => {
    if (closeIncident) {
      closeIncident();
    }
  }, [firmsStartDate, firmsEndDate, firmsPlaybackDate]);

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

        {/* SPATIO-TEMPORAL CLUSTERS (STAGE 3) */}
        {showFIRMSClusters &&
          (firmsClusters || []).map((cluster, index) => {
            const lat = num(cluster?.centroid?.latitude, null);
            const lon = num(cluster?.centroid?.longitude, null);
            if (lat === null || lon === null) return null;

            const count = cluster.observation_count || 1;
            const intensity = cluster.frp_intensity || "LOW";
            const intensityColors = {
              LOW: "#3b82f6",
              MODERATE: "#f59e0b",
              HIGH: "#ea580c",
              VERY_HIGH: "#dc2626"
            };
            const strokeColor = intensityColors[intensity] || "#3b82f6";
            const markerRadius = Math.min(22, Math.max(9, Math.round(7 + Math.log2(count + 1) * 3.5)));

            const formatDetectionTime = (dtStr) => {
              if (!dtStr) return "N/A";
              try {
                const s = String(dtStr).replace("Z", "+00:00");
                const parts = s.split("T");
                const d = parts[0];
                const t = parts[1] ? parts[1].slice(0, 5) + " UTC" : "";
                return `${d} ${t}`.trim();
              } catch {
                return String(dtStr);
              }
            };

            return (
              <CircleMarker
                className="spatiotemporal-cluster-marker"
                key={`firms-cluster-${cluster.cluster_id || index}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={markerRadius}
                pathOptions={{
                  className: "spatiotemporal-cluster-marker",
                  color: strokeColor,
                  fillColor: strokeColor,
                  fillOpacity: 0.65,
                  weight: 2.5
                }}
              >
                <Popup>
                  <div className="map-popup firms-cluster-popup">
                    <div className="popup-title-row">
                      <strong>🛰️ SPATIO-TEMPORAL CLUSTER</strong>
                      <span className={`risk-chip ${intensity.toLowerCase().replace('_', '-')}`}>
                        {intensity.replace('_', ' ')}
                      </span>
                    </div>

                    <div className="popup-divider" />

                    <div className="popup-data-row">
                      <span>Cluster ID</span>
                      <strong style={{ fontFamily: "monospace", color: strokeColor }}>
                        {cluster.cluster_id || "N/A"}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Observations</span>
                      <strong style={{ color: "#0f172a", fontWeight: 800 }}>
                        {count} {count === 1 ? "hotspot" : "hotspots"}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Operational State</span>
                      <strong style={{ fontSize: "9px" }}>
                        {cluster.operational_state || "ISOLATED_ACTIVITY"}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Total FRP</span>
                      <strong style={{ color: strokeColor }}>
                        {Number(cluster.total_frp ?? 0).toFixed(1)} MW
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Mean / Max FRP</span>
                      <strong>
                        {Number(cluster.mean_frp ?? 0).toFixed(1)} / {Number(cluster.max_frp ?? 0).toFixed(1)} MW
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Persistence</span>
                      <strong>
                        {cluster.persistence_duration_hours != null
                          ? `${cluster.persistence_duration_hours.toFixed(1)} hrs`
                          : "0.0 hrs"}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>First Detection</span>
                      <strong>
                        {formatDetectionTime(cluster.first_detected || cluster.first_detection)}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Last Detection</span>
                      <strong>
                        {formatDetectionTime(cluster.last_detected || cluster.latest_detection)}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Satellites</span>
                      <strong style={{ fontSize: "10px" }}>
                        {(cluster.satellites || []).join(", ") || "NOAA-20"}
                      </strong>
                    </div>

                    <div className="popup-coordinates">
                      📍 Centroid: {lat.toFixed(4)}, {lon.toFixed(4)}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

        {/* NASA FIRMS TEMPORAL HOTSPOTS (STAGE 2A) */}
        {showFIRMSHotspots &&
          firmsHotspots.map((hotspot, index) => {
            const lat = num(hotspot?.latitude, null);
            const lon = num(hotspot?.longitude, null);
            if (lat === null || lon === null) return null;

            const frpValue = Number(hotspot?.frp ?? 0);
            const markerRadius = Math.min(8, Math.max(4, Math.round(3 + Math.sqrt(Math.max(0, frpValue)))));

            return (
              <CircleMarker
                className="firms-temporal-marker"
                key={`firms-hotspot-${hotspot.id || index}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={markerRadius}
                pathOptions={{
                  className: "firms-temporal-marker",
                  color: "#c2410c",
                  fillColor: "#ea580c",
                  fillOpacity: 0.85,
                  weight: 1.5
                }}
              >
                <Popup>
                  <div className="map-popup firms-hotspot-popup">
                    <div className="popup-title-row">
                      <strong>🔥 FIRMS HOTSPOT</strong>
                      <span className="risk-chip moderate">
                        {String(hotspot?.confidence || "nominal").toUpperCase()}
                      </span>
                    </div>

                    <div className="popup-divider" />

                    <div className="popup-data-row">
                      <span>Date</span>
                      <strong>{hotspot?.acq_date || "N/A"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Time</span>
                      <strong>{formatTime(hotspot?.acq_time)}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Satellite</span>
                      <strong>{hotspot?.satellite || "NOAA-20"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>FRP</span>
                      <strong style={{ color: "#ea580c" }}>
                        {Number.isFinite(frpValue) && frpValue > 0 ? `${frpValue.toFixed(2)} MW` : "N/A"}
                      </strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Confidence</span>
                      <strong>{hotspot?.confidence || "nominal"}</strong>
                    </div>

                    <div className="popup-data-row">
                      <span>Source</span>
                      <strong style={{ fontSize: "11px", fontFamily: "monospace" }}>
                        {hotspot?.source || "VIIRS_NOAA20_NRT"}
                      </strong>
                    </div>

                    {hotspot?.brightness != null && (
                      <div className="popup-data-row">
                        <span>Brightness</span>
                        <strong>{Number(hotspot.brightness).toFixed(1)} K</strong>
                      </div>
                    )}

                    <div className="popup-coordinates">
                      📍 {lat.toFixed(4)}, {lon.toFixed(4)}
                    </div>

                    <div style={{ marginTop: "8px" }}>
                      <button
                        className="popup-action"
                        onClick={() => selectIncident({
                          ...hotspot,
                          id: hotspot.id,
                          observation_id: hotspot.id ? `OBS-H-${hotspot.id}` : "N/A",
                          event_id: null,
                          risk_level: hotspot.confidence === "h" || hotspot.confidence === "high" ? "High" : "Moderate",
                          persistence_days: 1,
                          brightness: hotspot.brightness || hotspot.bright_ti4,
                          frp: hotspot.frp,
                          geographic_validation: hotspot.geographic_validation || { domain: "LAND", state: hotspot.state || null }
                        })}
                        style={{ width: "100%" }}
                      >
                        INSPECT
                      </button>
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}

        {/* CLUSTERED INCIDENTS & THERMAL EVENTS */}
        {layers.thermal &&
          activeClusteredFires.map((fire, index) => {
            const lat = num(fire?.latitude, null);
            const lon = num(fire?.longitude, null);
            if (lat === null || lon === null) return null;

            const level = fire?.risk_level || "Low";
            const color = riskColor(level);
            const selected = selectedFire === fire;

            return (
              <CircleMarker
                className="incident-event-marker"
                key={`fire-${index}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={selected ? 11 : 7}
                pathOptions={{
                  className: "incident-event-marker",
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

      {/* EMPTY OBSERVATION OVERLAY */}
      {activeClusteredFires.length === 0 &&
        firmsHotspots.length === 0 &&
        firmsClusters.length === 0 &&
        !firmsLoading && (
          <div className="firms-map-empty-overlay" role="status">
            <span>🛰️ No thermal observations for {firmsPlaybackDate || firmsStartDate}</span>
          </div>
        )}

      {/* LEFT SIDEBAR */}
      <aside className="left-sidebar">
        {/* NASA FIRMS TEMPORAL FILTER (STAGE 2A) */}
        <TemporalFirmsControl
          startDate={firmsStartDate}
          endDate={firmsEndDate}
          playbackDate={firmsPlaybackDate}
          playbackDates={firmsPlaybackDates}
          isPlaying={firmsIsPlaying}
          togglePlay={toggleFirmsPlay}
          nextDay={nextFirmsDay}
          prevDay={prevFirmsDay}
          setPlaybackDate={setFirmsPlaybackDate}
          total={firmsTotal}
          loading={firmsLoading}
          error={firmsError}
          activePreset={firmsPreset}
          selectPreset={selectFirmsPreset}
          applyCustomRange={applyFirmsCustomRange}
          retry={retryFirms}
          validationError={firmsValidationError}
        />

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
              {dataMode === "india" ? activeClusteredFires.length : 2301}
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
              {dataMode === "eastern_india" ? activeClusteredFires.length : 918}
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
              checked={showFIRMSHotspots}
              onChange={() => setShowFIRMSHotspots((v) => !v)}
            />
            <span>FIRMS Hotspots</span>
            <em style={{ color: "#ea580c", fontWeight: 700 }}>
              {firmsLoading ? "…" : firmsTotal.toLocaleString()}
            </em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={showFIRMSClusters}
              onChange={() => setShowFIRMSClusters((v) => !v)}
            />
            <span>Spatio-Temporal Clusters</span>
            <em style={{ color: "#3b82f6", fontWeight: 700 }}>
              {firmsLoading ? "…" : (firmsClusters?.length || 0).toLocaleString()}
            </em>
          </label>

          <label className="layer-row">
            <input
              type="checkbox"
              checked={layers.thermal}
              onChange={() => setLayers((s) => ({ ...s, thermal: !s.thermal }))}
            />
            <span>Clustered Incidents</span>
            <em>{activeClusteredFires.length}</em>
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

          {["ALL", "NEW", "UNDER REVIEW", "CONFIRMED"].map(
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
            <strong>{activeClusteredFires.length}</strong>
            <span>EVENTS</span>
          </div>
          <div>
            <strong>{activeCriticalCount}</strong>
            <span>CRITICAL</span>
          </div>
          <div>
            <strong>{activeHighCount}</strong>
            <span>HIGH</span>
          </div>
          <div>
            <strong>{activePersistentCount}</strong>
            <span>PERSISTENT</span>
          </div>
        </section>
      </aside>

      {/* RIGHT INSPECTION DRAWER */}
      {selectedFire && (
        <IncidentInspectionDrawer
          selectedFire={selectedFire}
          fires={activeClusteredFires}
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
          NASA FIRMS VIIRS •{" "}
          {dataMode === "india" ? "INDIA-WIDE" : "EASTERN INDIA DEMO"}
        </span>
        <span>•</span>
        <span style={{ color: "#ea580c", fontWeight: 700 }}>
          {firmsTotal.toLocaleString()} TEMPORAL HOTSPOTS
        </span>
        <span>•</span>
        <span style={{ color: "#38bdf8", fontWeight: 700 }}>
          PLAYBACK DATE: {firmsPlaybackDate || firmsStartDate}
        </span>
        <span>•</span>
        <span style={{ color: "#a855f7", fontWeight: 700 }}>
          {activeClusteredFires.length.toLocaleString()} CLUSTERED INCIDENTS
        </span>
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

