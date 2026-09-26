import React from "react";

export default function Navbar({
  activeTab = "dashboard",
  setActiveTab,
  searchText = "",
  setSearchText,
  onSearch,
  isOnline = true,
  dataMode = "india",
  setDataMode,
  theme = "light",
  setTheme
}) {
  return (
    <header className="topbar">
      <div className="brand" onClick={() => setActiveTab("dashboard")}>
        <div className="brand-icon">🔥</div>
        <div>
          <div className="brand-title">AGNIVISION-GIS</div>
          <div className="brand-subtitle">SATELLITE THERMAL INTELLIGENCE</div>
        </div>
      </div>

      <nav className="nav-tabs">
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "dashboard" ? "active" : ""}`}
          onClick={() => setActiveTab("dashboard")}
        >
          Dashboard
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "verification" ? "active" : ""}`}
          onClick={() => setActiveTab("verification")}
        >
          Verification
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "map" ? "active" : ""}`}
          onClick={() => setActiveTab("map")}
        >
          Geo Map
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "temporal" ? "active" : ""}`}
          onClick={() => setActiveTab("temporal")}
        >
          Temporal Explorer
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "evaluation" ? "active" : ""}`}
          onClick={() => setActiveTab("evaluation")}
        >
          Event Evaluation
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "history" ? "active" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          History
        </button>
      </nav>

      <form className="search-box" onSubmit={onSearch}>
        <span>⌕</span>
        <input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search events, observations, facilities, coordinates..."
        />
      </form>

      <div className="coverage-selector">
        <span className="coverage-label">DATASET:</span>
        <select
          value={dataMode}
          onChange={(e) => setDataMode && setDataMode(e.target.value)}
          className="coverage-select"
          aria-label="FIRMS Data Coverage"
        >
          <option value="india">All-India Coverage (2,301)</option>
          <option value="eastern_india">Eastern India Demo Backup (918)</option>
        </select>
      </div>

      <div className="theme-toggle-pill" role="group" aria-label="Theme selector">
        <button
          type="button"
          className={`theme-pill-btn ${theme === "light" ? "active" : ""}`}
          onClick={() => setTheme && setTheme("light")}
          title="Switch to Light Theme"
          aria-pressed={theme === "light"}
        >
          ☀ Light
        </button>
        <button
          type="button"
          className={`theme-pill-btn ${theme === "dark" ? "active" : ""}`}
          onClick={() => setTheme && setTheme("dark")}
          title="Switch to Dark Theme"
          aria-pressed={theme === "dark"}
        >
          🌙 Dark
        </button>
      </div>

      <div className="system-pill">
        <span className={isOnline ? "online-dot" : "offline-dot"} />
        {isOnline ? "SYSTEM ONLINE" : "SYSTEM OFFLINE"}
      </div>
    </header>
  );
}

