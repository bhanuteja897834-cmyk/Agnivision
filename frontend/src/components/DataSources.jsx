import React from "react";

export default function DataSources() {
  return (
    <div className="dashboard-panel data-sources-panel">
      <div className="panel-title-row">
        <div>
          <h3>System Data Architecture & Provenance</h3>
          <p className="panel-subtitle">
            Transparent distinction between satellite observations, contextual layers, and deterministic heuristics
          </p>
        </div>
        <span className="source-pill">Transparency & Auditability</span>
      </div>

      <div className="sources-grid">
        <div className="source-card">
          <div className="source-card-header">
            <span className="source-type-tag tag-observed">OBSERVED DATA</span>
            <h4>NASA FIRMS</h4>
          </div>
          <p className="source-name">VIIRS NOAA-20 NRT 375m</p>
          <p className="source-detail">
            Near real-time 375m active thermal anomalies, brightness temperature (4µm & 11µm), Fire Radiative Power (FRP), and sensor detection confidence.
          </p>
          <div className="source-meta">
            <span>Provider: NASA EOSDIS / LANCE</span>
            <span>Update: Sliding 10-day NRT</span>
          </div>
        </div>

        <div className="source-card">
          <div className="source-card-header">
            <span className="source-type-tag tag-observed">GEOSPATIAL REFERENCE</span>
            <h4>NOAA GLOBE & Natural Earth</h4>
          </div>
          <p className="source-name">1km Land Mask & Admin-1 Boundaries</p>
          <p className="source-detail">
            NOAA GLOBE 1km digital elevation land-water model and Natural Earth Admin-1 geometries. Operates 100% offline via in-memory Shapely spatial indexing.
          </p>
          <div className="source-meta">
            <span>Layers: 36 Indian States & 76 Regional Lakes</span>
            <span>Lookup: &lt;0.1 ms/point</span>
          </div>
        </div>

        <div className="source-card">
          <div className="source-card-header">
            <span className="source-type-tag tag-context">INFRASTRUCTURE CONTEXT</span>
            <h4>OpenStreetMap / Overpass</h4>
          </div>
          <p className="source-name">Critical Infrastructure & Architecture</p>
          <p className="source-detail">
            Hospitals, schools, industrial facilities, power substations, and road networks within a 5 km radius. Polled with automatic disk caching and worker prefetching.
          </p>
          <div className="source-meta">
            <span>Cache TTL: 600s</span>
            <span>Endpoints: Overpass multi-fallback</span>
          </div>
        </div>

        <div className="source-card">
          <div className="source-card-header">
            <span className="source-type-tag tag-heuristic">DERIVED HEURISTICS</span>
            <h4>AGNIVISION Risk Engine</h4>
          </div>
          <p className="source-name">Deterministic Heuristic (Non-AI)</p>
          <p className="source-detail">
            Computes spatiotemporal repeat persistence (24-hour grid persistence) and scales risk scores (0–100) using brightness thresholds and sensor confidence weights.
          </p>
          <div className="source-meta">
            <span>Type: Deterministic formula</span>
            <span>Status: Prototype scoring</span>
          </div>
        </div>
      </div>
    </div>
  );
}

