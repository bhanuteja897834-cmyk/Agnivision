# AGNIVISION-GIS: Satellite Thermal Intelligence & Verification Platform

AGNIVISION-GIS is a transparent, multi-source geospatial intelligence platform that ingests NASA FIRMS VIIRS satellite thermal detections, clusters discrete observations into persistent spatiotemporal thermal events, retrieves live atmospheric weather and wind telemetry from Open-Meteo, executes a 25-feature Random Forest thermal event classifier, synthesizes multi-source spatial and historical evidence into an explainable 6-class Event Assessment, and provides an operator-in-the-loop Human Verification station with automated AI snapshot preservation.

---

## 1. Quick Start

### Backend (FastAPI / Python 3.14)
```bash
# 1. Navigate to backend
cd backend

# 2. Configure environment
# Copy .env.example to .env and configure your NASA FIRMS MAP_KEY:
# cp .env.example .env

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run FastAPI server (runs on 0.0.0.0:8001)
python main.py
```

### Frontend (React 19 / Vite 8)
```bash
# 1. Navigate to frontend
cd frontend

# 2. Install dependencies (if not already installed)
npm install

# 3. Start development server (runs on 0.0.0.0:5173)
npm run dev

# 4. Production build
npm run build
```

---

## 2. Core Architecture & Pipeline

```
NASA FIRMS VIIRS NOAA-20 NRT Satellite Observations
                 ↓
Spatiotemporal Event Engine (3.0 km × 36h Clustering)
                 ↓
Geographic Validation (36 States & Inland Water Masks)
                 ↓
Open-Meteo Live Atmospheric Weather & Wind Telemetry
                 ↓
25-Feature Random Forest Classifier (AGRICULTURAL_BURNING / INDUSTRIAL_HEAT / WILDLAND_FIRE)
                 ↓
Historical Archival Baseline (India-Wide 0.1° Spatial Grid)
                 ↓
Contextual Infrastructure Proximity (OSM Overpass Indices)
                 ↓
Multi-Source Evidence Fusion Layer (6 Operational Categories)
                 ↓
Operator-in-the-Loop Human Verification & Ground-Truth Registry
                 ↓
Interactive Command-Center Workspace (Dark Tactical & Global Light Themes)
```

---

## 3. Scientific Invariants & Terminology

- **FIRMS Observation:** A single satellite sensor pixel detection (375m VIIRS resolution, Brightness Temperature $T_4$, Fire Radiative Power in MW, acquisition date/time UTC).
- **Persistent Thermal Event:** A coherent spatiotemporal cluster of proximate satellite detections across revisit passes (e.g. `EVT-000029` with 133 detections across 5 calendar days).
- **Active ML Model:** Pre-trained 400-estimator Random Forest model packaged in `backend/data/new_dataset/AGNIVISION_final_model.zip`, inferring 3 core thermal source classes:
  - `AGRICULTURAL_BURNING`
  - `INDUSTRIAL_HEAT`
  - `WILDLAND_FIRE`
- **The 25 ML Features (In Strict Order):**
  1. `brightness` (VIIRS Band I-4 brightness temp in Kelvin)
  2. `bright_t31` (VIIRS Band I-5/M-15 brightness temp in Kelvin)
  3. `frp` (Fire Radiative Power in MW)
  4. `detections_same_cell` (0.1° grid cell detection recurrence)
  5. `active_days_same_cell` (Distinct active calendar days in cell)
  6. `mean_frp_same_cell` (Mean FRP across detections in cell)
  7. `max_frp_same_cell` (Peak FRP across detections in cell)
  8. `frp_vs_local_mean` (Difference between FRP and local cell mean)
  9. `temperature_c` (2m ambient surface temperature in °C via Open-Meteo)
  10. `u10` (10m eastward wind vector component in m/s via Open-Meteo)
  11. `v10` (10m northward wind vector component in m/s via Open-Meteo)
  12. `wind_speed_mps` (10m wind speed magnitude in m/s via Open-Meteo)
  13. `precipitation_mm` (Surface precipitation in mm via Open-Meteo)
  14. `brightness_t31_delta` (Split-window temperature difference $T_4 - T_{31}$ in Kelvin)
  15. `log_frp` (Natural log transform $\ln(1 + \text{frp})$)
  16. `detections_per_active_day` (Persistence recurrence density ratio)
  17. `frp_max_minus_mean` (Spread of local radiative intensity)
  18. `acq_hour` (Observation acquisition hour UTC, 0–23)
  19. `month` (Observation acquisition calendar month, 1–12)
  20. `hour_sin` (Diurnal cycle harmonic sine component)
  21. `hour_cos` (Diurnal cycle harmonic cosine component)
  22. `month_sin` (Seasonal cycle harmonic sine component)
  23. `month_cos` (Seasonal cycle harmonic cosine component)
  24. `is_day` (Binary solar illumination flag: 1 = Day, 0 = Night)
  25. `sensor_source_encoded` (Platform encoding: 0 = NOAA-20, 1 = S-NPP, 2 = Other)
- **Multi-Source Event Assessment:** Multi-criteria evidence fusion combining the 3-class ML prediction with persistence duration, observation count, FRP magnitude, historical baseline anomaly, OSM infrastructure context, and geographic boundaries to produce 6 operational categories:
  1. `FOREST_FIRE`
  2. `AGRICULTURAL_FIRE`
  3. `GAS_FLARE`
  4. `INDUSTRIAL_FIRE`
  5. `OTHER_THERMAL_EVENT`
  6. `UNKNOWN`
- **Human Verification:** Independent analyst ground-truth review station (`verified_events.json`). Human verification records do NOT alter raw FIRMS observations or automated classification rules.
- **AI Snapshot Preservation:** Every analyst verification automatically captures the complete AI state (ML prediction, 3-class probabilities, 25 feature inputs, operational assessment, and multi-source evidence signals) for future model evaluation without data fabrication.

---

## 4. Key Demonstration Events

- **`EVT-000029` (Persistent Industrial Gas Flare):**
  - Location: Bokaro / Dhanbad, Jharkhand (23.76127°N, 86.39550°E)
  - Observations: 133 discrete detections across 5 calendar days (118.5h duration, peak FRP 6.88 MW)
  - ML Prediction (3-Class): `WILDLAND_FIRE` (51.34%), `AGRICULTURAL_BURNING` (33.61%), `INDUSTRIAL_HEAT` (15.05%)
  - Operational Assessment (6-Class): `GAS_FLARE` (HIGH confidence; 5-day stationary persistence in industrial corridor isolates flaring from uncontrolled fire)
  - Human Ground Truth: `INDUSTRIAL_HEAT`
- **`EVT-000002` (Episodic Agricultural Residue Burning):**
  - Location: Bhojpur / Arrah agricultural belt, West Bengal / Bihar border (22.37662°N, 87.28043°E)
  - Observations: 1 detection, 4.58 MW FRP on terrestrial agricultural land
  - ML Prediction (3-Class): `AGRICULTURAL_BURNING` (53.01%), `WILDLAND_FIRE` (43.19%), `INDUSTRIAL_HEAT` (3.80%)
  - Operational Assessment (6-Class): `AGRICULTURAL_FIRE` (MODERATE confidence; crop residue clearing)
  - Human Ground Truth: `ACTIVE_FIRE`
- **`EVT-000230` (Wildland / Forest Canopy Fire):**
  - Location: Dense forest zone, Jharkhand (16.82669°N, 79.29771°E)
  - Observations: 1 detection, 6.58 MW FRP, brightness 326.6 K
  - ML Prediction (3-Class): `WILDLAND_FIRE` (65.36%), `AGRICULTURAL_BURNING` (31.95%), `INDUSTRIAL_HEAT` (2.69%)
  - Operational Assessment (6-Class): `FOREST_FIRE` (MODERATE confidence; remote forest canopy)
  - Human Ground Truth: `WILDLAND_FIRE`
- **`EVT-000059` (Acute Industrial Fire):**
  - Location: Hazira Industrial Belt, Gujarat (21.1054°N, 72.6412°E)
  - Observations: 69 detections, 4 active days, peak FRP 22.73 MW ($>15.0$ MW threshold)
  - Operational Assessment (6-Class): `INDUSTRIAL_FIRE` (HIGH confidence; high-energy anomaly in refinery zone)
- **`EVT-000010` (Marginal / Other Thermal Event):**
  - Observations: 1 detection, low FRP 1.20 MW ($<2.0$ MW), brightness 303.6 K
  - Operational Assessment (6-Class): `OTHER_THERMAL_EVENT` (MODERATE confidence; sub-threshold benign thermal signature)

---

## 5. Important API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/fires` | GET | Active FIRMS satellite thermal observations with risk scores |
| `/events` | GET | Spatiotemporally clustered persistent thermal events (Eastern India or all-India) |
| `/events/{id}` | GET | Full event metadata enriched with ML prediction & Event Assessment |
| `/events/{id}/history` | GET | Chronological pass-by-pass observation history |
| `/events/{id}/assessment` | GET | Multi-source explainable 6-class Event Assessment |
| `/ml/predict` | GET | Random Forest 25-feature ML inference for an event |
| `/ml/metadata` | GET | Active model specification, 400 estimators, and 25-feature schema |
| `/historical-baseline/summary` | GET | 30-day statistical baseline parameters |
| `/verify-event` | POST | Operator verification capturing complete live AI snapshot |
| `/verified-events` | GET | List of human-verified events with audit metadata and AI snapshots |
| `/assets` | GET | OpenStreetMap Overpass nearby infrastructure counts within radius |

---

## 6. System Limitations & Boundaries

- **No Live Cadastral Parcels:** Parcel-level agricultural field ownership boundaries are not integrated; agricultural events require operator confirmation.
- **Thermal Radiance vs Optical Photography:** Satellite VIIRS 375m pixels detect integrated mid-infrared radiance flux rather than optical fire photography.
- **Taxonomic Independence:** Human verification ground truth and automated ML classes operate on separate schemas and are never forced or auto-converted.
- **Infrastructure Proximity:** Proximity to mapped OSM industrial POIs provides spatial context; it does not constitute physical proof of smoke emission.
