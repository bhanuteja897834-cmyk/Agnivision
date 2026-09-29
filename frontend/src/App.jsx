import React, {
  Component,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import "leaflet/dist/leaflet.css";
import "./App.css";

import Navbar from "./components/Navbar";
import Dashboard from "./components/Dashboard";
import GeoMap from "./components/GeoMap";
import VerificationView from "./components/VerificationView";
import TemporalExplorer from "./components/TemporalExplorer";
import EventEvaluation from "./components/EventEvaluation";
import HistoryView from "./components/HistoryView";
import { calculateDateRange } from "./utils/dateUtils.js";


/* =========================================================
   ERROR BOUNDARY
========================================================= */

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("AGNIVISION UI ERROR:", error, info);
    this.setState({ error, errorInfo: info });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="fatal-screen">
          <div className="fatal-card" style={{ maxWidth: "850px", textAlign: "left" }}>
            <div className="fatal-icon" style={{ textAlign: "center" }}>⚠</div>
            <h2 style={{ textAlign: "center" }}>AGNIVISION-GIS</h2>
            <p style={{ textAlign: "center" }}>The dashboard encountered a display error.</p>
            <pre
              id="fatal-error-details"
              style={{
                background: "#090d16",
                color: "#f87171",
                padding: "16px",
                borderRadius: "6px",
                fontSize: "12px",
                overflowX: "auto",
                whiteSpace: "pre-wrap",
                lineHeight: 1.4,
                border: "1px solid #dc2626"
              }}
            >
              {String(this.state.error?.stack || this.state.error?.message || this.state.error)}
              {"\n\n"}
              {String(this.state.errorInfo?.componentStack || "")}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{ display: "block", margin: "16px auto 0" }}
            >
              RELOAD DASHBOARD
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}


/* =========================================================
   HELPERS & CONSTANTS
========================================================= */

const API_BASE = import.meta.env.VITE_API_BASE || "";


const EMPTY_COUNTS = {
  hospitals: 0,
  schools: 0,
  buildings: 0,
  roads: 0,
  power: 0,
  industrial: 0
};

function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function confidenceLabel(value) {
  const v = String(value ?? "").trim().toLowerCase();
  if (v === "l" || v === "low") return "Low";
  if (v === "n" || v === "nominal") return "Nominal";
  if (v === "h" || v === "high") return "High";
  return "Unknown";
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

function formatTime(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const s = String(value).trim().padStart(4, "0");
  if (/^\d{4}$/.test(s)) {
    return `${s.slice(0, 2)}:${s.slice(2, 4)} UTC`;
  }
  return String(value);
}

function assetLabel(type) {
  const labels = {
    building: "Architecture",
    industrial: "Industrial facility",
    hospital: "Hospital",
    school: "School",
    power: "Power infrastructure",
    road: "Road"
  };
  return labels[String(type || "").toLowerCase()] || "Mapped asset";
}

function assetIcon(type) {
  const icons = {
    building: "▦",
    industrial: "▥",
    hospital: "✚",
    school: "⌂",
    power: "ϟ",
    road: "═"
  };
  return icons[String(type || "").toLowerCase()] || "•";
}

function assetColor(type) {
  const colors = {
    building: "#64748b",
    industrial: "#ea580c",
    hospital: "#dc2626",
    school: "#ca8a04",
    power: "#7c3aed",
    road: "#0284c7"
  };
  return colors[String(type || "").toLowerCase()] || "#64748b";
}

function fireKey(fire) {
  return [
    fire?.latitude,
    fire?.longitude,
    fire?.acq_date,
    fire?.acq_time
  ].join("|");
}

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

function classifyRisk(h) {
  const brightness = Number(h?.bright_ti4 || 0);
  const frp = Number(h?.frp || 0);
  const conf = String(h?.confidence || '').toLowerCase();
  
  let score = 0;
  if (brightness > 360) score += 40;
  else if (brightness > 340) score += 30;
  else if (brightness > 320) score += 20;
  else score += 10;
  
  if (frp > 50) score += 30;
  else if (frp > 20) score += 20;
  else if (frp > 5) score += 10;
  
  if (conf === 'h' || conf === 'high') score += 20;
  else if (conf === 'n' || conf === 'nominal') score += 10;
  
  if (score >= 70) return 'Critical';
  if (score >= 50) return 'High';
  if (score >= 30) return 'Moderate';
  return 'Low';
}


/* =========================================================
   MAIN APP CONTROLLER
========================================================= */

function AppMain() {
  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem("agnivision_theme");
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      // Ignore
    }
    return "light";
  });

  useEffect(() => {
    try {
      localStorage.setItem("agnivision_theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
    } catch {
      // Ignore
    }
  }, [theme]);

  const [activeTab, setActiveTab] = useState("dashboard");
  const [dateRange, setDateRange] = useState(() => calculateDateRange("10D"));
  
  const [fires, setFires] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState(null);
  const [isOnline, setIsOnline] = useState(true);

  const [temporalEventId, setTemporalEventId] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      const urlId = sp.get("event_id") || sp.get("eventId");
      if (urlId) return urlId.toUpperCase();
    } catch {
      // Ignore
    }
    return null;
  });

  useEffect(() => {
    const parseUrlParams = () => {
      try {
        const sp = new URLSearchParams(window.location.search);
        const urlId = sp.get("event_id") || sp.get("eventId");
        const tab = sp.get("tab") || (window.location.pathname.includes("history") ? "temporal" : null);
        if (urlId) {
          setTemporalEventId(urlId.toUpperCase());
        }
        if (tab) {
          setActiveTab(tab === "history" ? "temporal" : tab);
        }
      } catch {
        // Ignore
      }
    };
    parseUrlParams();
    window.addEventListener("popstate", parseUrlParams);
    return () => window.removeEventListener("popstate", parseUrlParams);
  }, []);

  useEffect(() => {
    const handleNav = (e) => {
      if (e?.detail) setActiveTab(e.detail);
    };
    const handleNavEvent = (e) => {
      if (e?.detail?.eventId) {
        setTemporalEventId(e.detail.eventId);
        setActiveTab("temporal");
      }
    };
    window.addEventListener("agnivision-navigate-tab", handleNav);
    window.addEventListener("agnivision-inspect-event", handleNavEvent);
    return () => {
      window.removeEventListener("agnivision-navigate-tab", handleNav);
      window.removeEventListener("agnivision-inspect-event", handleNavEvent);
    };
  }, []);

  const [verifiedEvents, setVerifiedEvents] = useState([]);
  const [loadingVerified, setLoadingVerified] = useState(false);

  const [selectedFire, setSelectedFire] = useState(null);

  const [assets, setAssets] = useState(null);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [assetError, setAssetError] = useState(false);

  const [baseLayer, setBaseLayer] = useState("standard");

  const [layers, setLayers] = useState({
    thermal: true,
    architecture: true,
    industrial: true,
    hospitals: true,
    schools: true,
    roads: true,
    power: true,
    zones: true
  });

  const [eventFilters, setEventFilters] = useState({
    low: true,
    moderate: true,
    high: true,
    critical: true
  });

  const [verification, setVerification] = useState("ALL");
  const [verifiedLabel, setVerifiedLabel] = useState(null);
  const [verifyingEvent, setVerifyingEvent] = useState(false);
  const [verificationMessage, setVerificationMessage] = useState("");

  const [searchText, setSearchText] = useState("");
  const [dataMode, setDataMode] = useState("india");

  const assetCache = useRef(new Map());
  const firesCache = useRef(new Map());
  const assetControllerRef = useRef(null);


  /* -------------------------------------------------------
     LOAD FIRMS (INDIA-WIDE NATIONAL COVERAGE / DEMO BACKUP)
  ------------------------------------------------------- */

  useEffect(() => {
    let cancelled = false;

    async function loadFires() {
      const modeParam = dataMode === 'eastern_india' ? 'eastern_india' : 'india';

      // Eastern India demo mode uses legacy /fires endpoint
      if (modeParam === 'eastern_india') {
        if (firesCache.current.has('eastern_india')) {
          setFires(firesCache.current.get('eastern_india'));
          setIsOnline(true);
          setLoading(false);
          return;
        }
        try {
          setLoading(true);
          setPageError(null);
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 70000);
          const response = await fetch(`${API_BASE}/fires?mode=eastern_india`, { signal: controller.signal });
          clearTimeout(timeout);
          if (!response.ok) throw new Error(`Backend returned ${response.status}`);
          const data = await response.json();
          const list = Array.isArray(data?.fires) ? data.fires : [];
          if (cancelled) return;
          firesCache.current.set('eastern_india', list);
          setFires(list);
          setIsOnline(true);
        } catch (error) {
          if (cancelled) return;
          console.error('FIRMS error:', error);
          setIsOnline(false);
          setPageError(error?.name === 'AbortError' ? 'FIRMS request timed out.' : error.message || 'Could not load FIRMS data');
        } finally {
          if (!cancelled) setLoading(false);
        }
        return;
      }

      // India mode: fetch from real authoritative SQLite via /api/v1/hotspots
      const cacheKey = `india_${dateRange?.startDate}_${dateRange?.endDate}`;
      if (firesCache.current.has(cacheKey)) {
        setFires(firesCache.current.get(cacheKey));
        setIsOnline(true);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setPageError(null);
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 70000);
        const url = `${API_BASE}/api/v1/hotspots?start_date=${dateRange?.startDate}&end_date=${dateRange?.endDate}&limit=10000`;
        const response = await fetch(url, { signal: controller.signal });
        clearTimeout(timeout);
        if (!response.ok) throw new Error(`Backend returned ${response.status}`);
        const data = await response.json();
        const hotspots = Array.isArray(data?.hotspots) ? data.hotspots : (Array.isArray(data?.observations) ? data.observations : []);
        if (cancelled) return;

        // Normalize hotspot fields for Dashboard, MetricCards, and all child components
        const normalized = hotspots.map(h => ({
          ...h,
          brightness: Number(h.bright_ti4 || h.brightness || 0),
          bright_ti4: Number(h.bright_ti4 || h.brightness || 0),
          bright_ti5: Number(h.bright_ti5 || 0),
          frp: Number(h.frp || 0),
          confidence: h.confidence,
          latitude: Number(h.latitude),
          longitude: Number(h.longitude),
          acq_date: h.acq_date,
          acq_time: h.acq_time,
          acquisition_datetime: h.acquisition_datetime || `${h.acq_date}T${(h.acq_time || '0000').slice(0, 2)}:${(h.acq_time || '0000').slice(2, 4)}:00Z`,
          daynight: h.daynight,
          satellite: h.satellite || 'NOAA-20',
          event_id: null,
          risk_level: classifyRisk(h),
          geographic_validation: h.geographic_validation || {
            domain: h.domain || 'LAND',
            state: h.state || null,
            district: null,
            city: null
          }
        }));

        firesCache.current.set(cacheKey, normalized);
        setFires(normalized);
        setIsOnline(true);
      } catch (error) {
        if (cancelled) return;
        console.error('FIRMS error:', error);
        setIsOnline(false);
        setPageError(error?.name === 'AbortError' ? 'FIRMS request timed out.' : error.message || 'Could not load FIRMS data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadFires();
    return () => { cancelled = true; };
  }, [dataMode, dateRange.startDate, dateRange.endDate]);


  /* -------------------------------------------------------
     LOAD VERIFIED EVENTS
  ------------------------------------------------------- */

  const loadVerifiedEvents = async () => {
    try {
      setLoadingVerified(true);
      const response = await fetch(`${API_BASE}/verified-events`);
      if (response.ok) {
        const data = await response.json();
        if (Array.isArray(data?.events)) {
          setVerifiedEvents(data.events);
        }
      }
    } catch (err) {
      console.warn("Could not load verified events dataset:", err);
    } finally {
      setLoadingVerified(false);
    }
  };

  useEffect(() => {
    loadVerifiedEvents();
  }, []);


  /* -------------------------------------------------------
     SELECT INCIDENT / OVERPASS ASSETS
  ------------------------------------------------------- */

  async function selectIncident(fire) {
    if (assetControllerRef.current) {
      assetControllerRef.current.abort();
    }

    setSelectedFire(fire);
    setAssetError(false);

    const lat = num(fire?.latitude, null);
    const lon = num(fire?.longitude, null);

    if (lat === null || lon === null) {
      setAssets(null);
      setAssetError(true);
      setLoadingAssets(false);
      return;
    }

    const key = fireKey(fire);
    const cached = assetCache.current.get(key);

    if (cached) {
      setAssets(cached);
    } else {
      setAssets(null);
    }

    setLoadingAssets(true);

    const controller = new AbortController();
    assetControllerRef.current = controller;
    const stopAt = Date.now() + 45000;

    try {
      while (!controller.signal.aborted && Date.now() < stopAt) {
        const response = await fetch(
          `${API_BASE}/assets?lat=${lat}&lon=${lon}&radius=5000`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          throw new Error(`Asset API returned ${response.status}`);
        }

        const data = await response.json();

        if (data?.ok === false) {
          if (!cached) {
            setAssets(null);
            setAssetError(true);
          }
          return;
        }

        const normalized = {
          counts: {
            ...EMPTY_COUNTS,
            ...(data?.counts || {})
          },
          assets: Array.isArray(data?.assets) ? data.assets : [],
          cached: Boolean(data?.cached),
          stale: Boolean(data?.stale),
          warning: data?.warning || null
        };

        if (data?.status === "loading") {
          if (!cached) {
            setAssets({
              counts: EMPTY_COUNTS,
              assets: [],
              cached: false,
              stale: false,
              warning: "OpenStreetMap infrastructure is still loading…"
            });
          }

          await new Promise((resolve, reject) => {
            const timer = setTimeout(resolve, 1800);
            controller.signal.addEventListener(
              "abort",
              () => {
                clearTimeout(timer);
                reject(new DOMException("Aborted", "AbortError"));
              },
              { once: true }
            );
          });
          continue;
        }

        assetCache.current.set(key, normalized);
        setAssets(normalized);
        setAssetError(false);
        return;
      }

      if (!cached) {
        setAssetError(true);
      }
    } catch (error) {
      if (error?.name === "AbortError") return;
      console.error("OSM asset lookup failed:", error);
      if (!cached) {
        setAssets(null);
        setAssetError(true);
      }
    } finally {
      if (assetControllerRef.current === controller) {
        assetControllerRef.current = null;
      }
      if (!controller.signal.aborted) {
        setLoadingAssets(false);
      }
    }
  }

  function handleSelectFromDashboard(fire) {
    selectIncident(fire);
    setActiveTab("map");
  }

  function handleInspectCoordinates(lat, lon) {
    setActiveTab("map");
    setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent("agnivision-search-coordinate", {
          detail: { lat, lon }
        })
      );
    }, 150);
  }

  function closeIncident() {
    if (assetControllerRef.current) {
      assetControllerRef.current.abort();
      assetControllerRef.current = null;
    }

    setSelectedFire(null);
    setAssets(null);
    setLoadingAssets(false);
    setAssetError(false);
    setVerifiedLabel(null);
    setVerificationMessage("");
  }


  /* -------------------------------------------------------
     VERIFY EVENT
  ------------------------------------------------------- */

  async function verifySelectedEvent(label) {
    if (!selectedFire || verifyingEvent) return;

    const latitude = num(selectedFire?.latitude, null);
    const longitude = num(selectedFire?.longitude, null);

    if (latitude === null || longitude === null) {
      setVerificationMessage("Invalid event coordinates.");
      return;
    }

    const counts = assets?.counts || {};
    const nearbyAssets = Array.isArray(assets?.assets) ? assets.assets : [];

    const nearestDistance = (type) => {
      const values = nearbyAssets
        .filter((asset) => String(asset?.type || "").toLowerCase() === type)
        .map((asset) => {
          const alat = num(asset?.latitude, null);
          const alon = num(asset?.longitude, null);
          if (alat === null || alon === null) return null;
          return haversineMeters(latitude, longitude, alat, alon);
        })
        .filter((value) => Number.isFinite(value));

      return values.length ? Math.round(Math.min(...values) * 10) / 10 : null;
    };

    const features = {
      brightness: Number(selectedFire?.brightness ?? selectedFire?.bright_ti4 ?? 0),
      frp: Number(selectedFire?.frp ?? 0),
      confidence: selectedFire?.confidence ?? null,
      persistence_days: Number(selectedFire?.persistence_days ?? 1),
      day_night: selectedFire?.daynight ?? selectedFire?.day_night ?? null,
      hospitals_5km: Number(counts.hospitals ?? 0),
      schools_5km: Number(counts.schools ?? 0),
      buildings_5km: Number(counts.buildings ?? 0),
      roads_5km: Number(counts.roads ?? 0),
      power_5km: Number(counts.power ?? 0),
      industrial_5km: Number(counts.industrial ?? 0),
      nearest_hospital_m: nearestDistance("hospital"),
      nearest_school_m: nearestDistance("school"),
      nearest_building_m: nearestDistance("building"),
      nearest_road_m: nearestDistance("road"),
      nearest_power_m: nearestDistance("power"),
      nearest_industrial_m: nearestDistance("industrial")
    };

    setVerifyingEvent(true);
    setVerificationMessage("");

    try {
      const response = await fetch(`${API_BASE}/verify-event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude,
          longitude,
          acq_date: selectedFire?.acq_date ?? null,
          acq_time: selectedFire?.acq_time ?? null,
          source: "NASA FIRMS",
          features,
          label
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data?.detail?.message || data?.detail || "Verification failed");
      }

      setVerifiedLabel(label);
      setVerificationMessage(
        data?.replaced_existing
          ? "Verification updated in the learning dataset."
          : "Event added to the learning dataset."
      );
      loadVerifiedEvents();
    } catch (error) {
      console.error("Event verification failed:", error);
      setVerificationMessage(error.message || "Verification failed.");
    } finally {
      setVerifyingEvent(false);
    }
  }


  /* -------------------------------------------------------
     SEARCH
  ------------------------------------------------------- */

  function runSearch(event) {
    event.preventDefault();

    const match = searchText
      .trim()
      .match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);

    if (match) {
      const lat = Number(match[1]);
      const lon = Number(match[2]);

      if (
        Number.isFinite(lat) &&
        Number.isFinite(lon) &&
        lat >= -90 &&
        lat <= 90 &&
        lon >= -180 &&
        lon <= 180
      ) {
        setActiveTab("map");
        setTimeout(() => {
          window.dispatchEvent(
            new CustomEvent("agnivision-search-coordinate", {
              detail: { lat, lon }
            })
          );
        }, 150);
      }
    } else if (searchText.trim().length > 0) {
      const trimmed = searchText.trim();
      const evtMatch = trimmed.match(/^EVT-\d+$/i);
      if (evtMatch) {
        setTemporalEventId(evtMatch[0].toUpperCase());
        setActiveTab("temporal");
        return;
      }

      // Find matching observation
      const query = trimmed.toLowerCase();
      const matchFire = fires.find((f) => {
        const state = String(f?.geographic_validation?.state || "").toLowerCase();
        const city = String(f?.geographic_validation?.city || "").toLowerCase();
        const date = String(f?.acq_date || "").toLowerCase();
        const domain = String(f?.geographic_validation?.domain || "").toLowerCase();
        return (
          state.includes(query) ||
          city.includes(query) ||
          date.includes(query) ||
          domain.includes(query)
        );
      });

      if (matchFire) {
        handleSelectFromDashboard(matchFire);
      }
    }
  }


  /* -------------------------------------------------------
     DERIVED FILTERED FIRES FOR MAP
  ------------------------------------------------------- */

  const verifiedEventIdSet = useMemo(() => {
    const set = new Set();
    for (const v of verifiedEvents) {
      const id = v?.event_id || v?.features?.event_id;
      if (id) set.add(String(id).toUpperCase());
    }
    return set;
  }, [verifiedEvents]);

  const filteredFires = useMemo(() => {
    return fires.filter((fire) => {
      const level = riskClass(fire?.risk_level);
      if (!eventFilters[level]) return false;

      if (verification && verification !== "ALL") {
        const isConfirmed = fire?.event_id && verifiedEventIdSet.has(String(fire.event_id).toUpperCase());
        if (verification === "CONFIRMED") return isConfirmed;
        if (verification === "NEW") return !isConfirmed && num(fire?.persistence_days, 1) <= 1;
        if (verification === "UNDER REVIEW" || verification === "NEEDS VERIFICATION") {
          return !isConfirmed && num(fire?.persistence_days, 1) > 1;
        }
      }

      return true;
    });
  }, [fires, eventFilters, verification, verifiedEventIdSet]);

  const criticalCount = fires.filter(
    (f) => riskClass(f?.risk_level) === "critical"
  ).length;

  const highCount = fires.filter(
    (f) => riskClass(f?.risk_level) === "high"
  ).length;

  const persistentCount = fires.filter(
    (f) => num(f?.persistence_days) >= 2
  ).length;

  const helpers = {
    num,
    riskColor,
    riskClass,
    confidenceLabel,
    formatTime,
    assetLabel,
    assetIcon,
    assetColor
  };


  /* -------------------------------------------------------
     RENDER VIEW CONTENT
  ------------------------------------------------------- */

  return (
    <div className="gis-app" data-theme={theme}>
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        searchText={searchText}
        setSearchText={setSearchText}
        onSearch={runSearch}
        isOnline={isOnline}
        dataMode={dataMode}
        setDataMode={(mode) => {
          closeIncident();
          setDataMode(mode);
        }}
        theme={theme}
        setTheme={setTheme}
      />

      <div className="app-main-body">
        {activeTab === "dashboard" && (
          <Dashboard
            fires={fires}
            loading={loading}
            error={pageError}
            verifiedEvents={verifiedEvents}
            loadingVerified={loadingVerified}
            onSelectObservation={handleSelectFromDashboard}
            onInspectCoordinates={handleInspectCoordinates}
            selectedFire={selectedFire}
            dateRange={dateRange}
            setDateRange={setDateRange}
          />
        )}

        {activeTab === "verification" && (
          <VerificationView
            fires={fires}
            verifiedEvents={verifiedEvents}
            loadingVerified={loadingVerified}
            onSelectObservation={handleSelectFromDashboard}
            onInspectCoordinates={handleInspectCoordinates}
            onOpenEvaluation={(eventId) => {
              setTemporalEventId(eventId);
              setActiveTab("evaluation");
            }}
            onOpenTemporal={(eventId) => {
              setTemporalEventId(eventId);
              setActiveTab("temporal");
            }}
            onRefreshVerified={loadVerifiedEvents}
          />
        )}

        {activeTab === "map" && (
          <GeoMap
            fires={fires}
            filteredFires={filteredFires}
            dateRange={dateRange}
            setDateRange={setDateRange}
            selectedFire={selectedFire}
            selectIncident={selectIncident}
            closeIncident={closeIncident}
            assets={assets}
            loadingAssets={loadingAssets}
            assetError={assetError}
            baseLayer={baseLayer}
            setBaseLayer={setBaseLayer}
            layers={layers}
            setLayers={setLayers}
            eventFilters={eventFilters}
            setEventFilters={setEventFilters}
            verification={verification}
            setVerification={setVerification}
            verifiedLabel={verifiedLabel}
            verifyingEvent={verifyingEvent}
            verificationMessage={verificationMessage}
            verifySelectedEvent={verifySelectedEvent}
            criticalCount={criticalCount}
            highCount={highCount}
            persistentCount={persistentCount}
            helpers={helpers}
            dataMode={dataMode}
            setDataMode={(mode) => {
              closeIncident();
              setDataMode(mode);
            }}
            onOpenEvaluation={(eventId) => {
              if (eventId) setTemporalEventId(eventId);
              setActiveTab("evaluation");
            }}
            onOpenTemporal={(eventId) => {
              if (eventId) setTemporalEventId(eventId);
              setActiveTab("temporal");
            }}
          />
        )}

        {activeTab === "temporal" && (
          <TemporalExplorer
            initialEventId={temporalEventId || selectedFire?.event_id || (dataMode === "india" ? "EVT-000111" : "EVT-000029")}
            dataMode={dataMode}
            onSelectObservation={handleSelectFromDashboard}
            onOpenEvaluation={(eventId) => {
              setTemporalEventId(eventId);
              setActiveTab("evaluation");
            }}
          />
        )}

        {activeTab === "evaluation" && (
          <EventEvaluation
            initialEventId={temporalEventId || selectedFire?.event_id || (dataMode === "india" ? "EVT-000111" : "EVT-000029")}
            dataMode={dataMode}
            onSelectEvent={(eventId) => {
              if (eventId) setTemporalEventId(eventId);
            }}
            onOpenTemporal={(eventId) => {
              if (eventId) setTemporalEventId(eventId);
              setActiveTab("temporal");
            }}
            verifiedEvents={verifiedEvents}
            onRefreshVerified={loadVerifiedEvents}
          />
        )}

        {activeTab === "history" && (
          <HistoryView
            initialEventId={temporalEventId}
            dataMode={dataMode}
          />
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppMain />
    </ErrorBoundary>
  );
}

