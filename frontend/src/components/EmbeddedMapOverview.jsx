import React, { useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Popup
} from "react-leaflet";

function getRiskColor(level) {
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

export default function EmbeddedMapOverview({
  fires = [],
  onSelectObservation
}) {
  const stats = useMemo(() => {
    let critical = 0;
    let high = 0;
    for (const f of fires) {
      const r = String(f?.risk_level || "").toLowerCase();
      if (r === "critical") critical++;
      else if (r === "high") high++;
    }
    return { critical, high, total: fires.length };
  }, [fires]);

  // Center of India
  const center = [22.5, 79.0];

  return (
    <div className="dashboard-panel embedded-map-panel">
      <div className="panel-title-row">
        <div>
          <h3>GIS Live Observation Map</h3>
          <p className="panel-subtitle">
            VIIRS NOAA-20 NRT spatial thermal distribution ({stats.total} points)
          </p>
        </div>
        <div className="embedded-map-actions">
          <span className="source-pill">NASA FIRMS LIVE</span>
          {onSelectObservation && fires.length > 0 && (
            <button
              type="button"
              className="open-studio-btn"
              onClick={() => onSelectObservation(fires[0])}
            >
              Open GIS Studio ↗
            </button>
          )}
        </div>
      </div>

      <div className="embedded-map-container">
        <MapContainer
          center={center}
          zoom={4}
          minZoom={3}
          maxZoom={11}
          scrollWheelZoom={false}
          className="dashboard-leaflet-map"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {fires.map((fire, idx) => {
            const lat = Number(fire.latitude);
            const lon = Number(fire.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

            const risk = String(fire.risk_level || "low").toLowerCase();
            const color = getRiskColor(risk);
            const isHighPriority = risk === "critical" || risk === "high";

            return (
              <CircleMarker
                key={`embed-marker-${idx}-${lat}-${lon}`}
                center={[lat, lon]}
                radius={isHighPriority ? 6 : 4}
                pathOptions={{
                  color: isHighPriority ? "#ffffff" : color,
                  fillColor: color,
                  fillOpacity: isHighPriority ? 0.9 : 0.7,
                  weight: isHighPriority ? 1.5 : 1
                }}
              >
                <Popup>
                  <div className="map-popup fire-popup">
                    <div className="popup-title-row">
                      <strong>🔥 Thermal Observation</strong>
                      <span
                        className="risk-chip"
                        style={{
                          backgroundColor: color + "20",
                          color: color,
                          borderColor: color
                        }}
                      >
                        {risk.toUpperCase()}
                      </span>
                    </div>
                    <div className="popup-divider" />
                    <div className="popup-data-row">
                      <span>Coordinates:</span>
                      <strong>
                        {lat.toFixed(4)}, {lon.toFixed(4)}
                      </strong>
                    </div>
                    <div className="popup-data-row">
                      <span>State:</span>
                      <strong>{fire?.geographic_validation?.state || "N/A"}</strong>
                    </div>
                    <div className="popup-data-row">
                      <span>FRP:</span>
                      <strong>{fire?.frp ?? "N/A"} MW</strong>
                    </div>
                    <div className="popup-data-row">
                      <span>Brightness:</span>
                      <strong>{fire?.bright_ti4 ?? fire?.brightness ?? "N/A"} K</strong>
                    </div>
                    {onSelectObservation && (
                      <button
                        type="button"
                        className="popup-action"
                        onClick={() => onSelectObservation(fire)}
                        style={{ marginTop: "8px" }}
                      >
                        Inspect in GIS Studio ➔
                      </button>
                    )}
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>

        <div className="map-legend-overlay">
          <div className="legend-chip">
            <span className="legend-dot" style={{ background: "#dc2626" }} />
            Critical ({stats.critical})
          </div>
          <div className="legend-chip">
            <span className="legend-dot" style={{ background: "#ea580c" }} />
            High ({stats.high})
          </div>
          <div className="legend-chip">
            <span className="legend-dot" style={{ background: "#d97706" }} />
            Moderate
          </div>
          <div className="legend-chip">
            <span className="legend-dot" style={{ background: "#16a34a" }} />
            Low
          </div>
        </div>
      </div>
    </div>
  );
}

