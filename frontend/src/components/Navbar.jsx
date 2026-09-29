import React, { useEffect, useState } from "react";

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
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setMenuOpen(false);
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  const navigateTo = (tab) => {
    setActiveTab(tab);
    setMenuOpen(false);
  };

  return (
    <header className="topbar">
      <button
        type="button"
        className="brand"
        onClick={() => navigateTo("dashboard")}
        aria-label="Go to dashboard"
      >
        <div className="brand-icon">🔥</div>
        <div>
          <div className="brand-title">AGNIVISION-GIS</div>
          <div className="brand-subtitle">SATELLITE THERMAL INTELLIGENCE</div>
        </div>
      </button>

      <button
        type="button"
        className="mobile-menu-toggle"
        onClick={() => setMenuOpen((open) => !open)}
        aria-expanded={menuOpen}
        aria-controls="primary-navigation"
        aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
      >
        <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span>
        <span className="mobile-menu-label">Menu</span>
      </button>

      <div className={`topbar-content ${menuOpen ? "menu-open" : ""}`}>
      <nav className="nav-tabs" id="primary-navigation" aria-label="Primary navigation">
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "dashboard" ? "active" : ""}`}
          onClick={() => navigateTo("dashboard")}
        >
          Dashboard
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "verification" ? "active" : ""}`}
          onClick={() => navigateTo("verification")}
        >
          Verification
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "map" ? "active" : ""}`}
          onClick={() => navigateTo("map")}
        >
          Geo Map
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "temporal" ? "active" : ""}`}
          onClick={() => navigateTo("temporal")}
        >
          Temporal Explorer
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "evaluation" ? "active" : ""}`}
          onClick={() => navigateTo("evaluation")}
        >
          Event Evaluation
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === "history" ? "active" : ""}`}
          onClick={() => navigateTo("history")}
        >
          History
        </button>
      </nav>

      <form className="search-box" onSubmit={onSearch} role="search">
        <span aria-hidden="true">⌕</span>
        <input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search events, observations, facilities, coordinates..."
          aria-label="Search events, observations, facilities, coordinates"
          autoComplete="off"
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
          <option value="india">All-India Coverage</option>
          <option value="eastern_india">Eastern India Demo</option>
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
      </div>
    </header>
  );
}

