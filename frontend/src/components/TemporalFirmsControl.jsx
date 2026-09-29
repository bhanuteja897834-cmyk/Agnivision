import React, { useState, useEffect, useCallback, useRef } from "react";
import TimelinePlaybackControl from "./TimelinePlaybackControl";
import { fetchFIRMSSyncStatus, triggerFIRMSSync } from "../api/firmsApi.js";
import { formatDisplayDate } from "../utils/dateUtils.js";

/**
 * Compact date-range filtering control and temporal playback scrubber for NASA FIRMS Hotspots.
 * Designed to integrate natively into AGNIVISION's GIS map sidebar.
 */
export default function TemporalFirmsControl({
  startDate,
  endDate,
  playbackDate,
  playbackDates = [],
  isPlaying = false,
  togglePlay,
  nextDay,
  prevDay,
  setPlaybackDate,
  total,
  loading,
  error,
  activePreset,
  selectPreset,
  applyCustomRange,
  retry,
  validationError
}) {
  const [localStart, setLocalStart] = useState(startDate);
  const [localEnd, setLocalEnd] = useState(endDate);
  const [customFormError, setCustomFormError] = useState(null);

  // Sync status state (Stage 2C -> Phase 4 Near-Real-Time Monitoring)
  const [syncStatus, setSyncStatus] = useState(null);
  const [syncingNow, setSyncingNow] = useState(false);
  const [syncFeedback, setSyncFeedback] = useState(null);

  const lastCompletedAtRef = useRef(null);
  const isFirstLoadRef = useRef(true);

  const loadSyncStatus = useCallback(async () => {
    try {
      const data = await fetchFIRMSSyncStatus();
      setSyncStatus(data);
      if (data?.last_sync_completed_at) {
        if (
          !isFirstLoadRef.current &&
          lastCompletedAtRef.current &&
          data.last_sync_completed_at !== lastCompletedAtRef.current
        ) {
          // Automatic frontend refresh on background sync completion (Phase 6)
          if (data.last_sync_inserted > 0) {
            setSyncFeedback(`+${data.last_sync_inserted} new`);
          }
          if (retry) {
            retry();
          }
        }
        lastCompletedAtRef.current = data.last_sync_completed_at;
        isFirstLoadRef.current = false;
      }
    } catch {
      // Ignore background status errors
    }
  }, [retry]);

  useEffect(() => {
    loadSyncStatus();
    const interval = setInterval(loadSyncStatus, 15000);
    return () => clearInterval(interval);
  }, [loadSyncStatus]);

  const handleSyncNow = async () => {
    setSyncingNow(true);
    setSyncFeedback(null);
    try {
      const res = await triggerFIRMSSync({ days: 3 });
      const inserted = res.inserted || 0;
      setSyncFeedback(inserted > 0 ? `+${inserted} new` : "Up to date");
      await loadSyncStatus();
      if (retry) retry();
    } catch (err) {
      setSyncFeedback(err.message || "Failed");
    } finally {
      setSyncingNow(false);
    }
  };

  const formatTimeUTC = (isoStr) => {
    if (!isoStr) return "Ready";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) {
        return isoStr.slice(11, 16) + " UTC";
      }
      const hh = String(d.getUTCHours()).padStart(2, "0");
      const mm = String(d.getUTCMinutes()).padStart(2, "0");
      return `${hh}:${mm} UTC`;
    } catch {
      return isoStr.slice(11, 16) + " UTC";
    }
  };

  const getNextSyncCountdown = () => {
    if (!syncStatus?.next_sync_at) return "15m cycle";
    try {
      const nextTime = new Date(syncStatus.next_sync_at).getTime();
      const diffMs = nextTime - Date.now();
      if (diffMs <= 0) return "Due";
      const diffMin = Math.ceil(diffMs / 60000);
      return `~${diffMin}m (${formatTimeUTC(syncStatus.next_sync_at)})`;
    } catch {
      return formatTimeUTC(syncStatus.next_sync_at);
    }
  };

  const getSyncBadge = () => {
    if (syncStatus?.enabled === false) {
      return {
        label: "⚪ FIRMS NRT — DISABLED",
        color: "#64748b",
        bg: "rgba(100, 116, 139, 0.12)"
      };
    }
    if (syncingNow || syncStatus?.is_syncing) {
      return {
        label: "🟡 FIRMS NRT — UPDATING",
        color: "#d97706",
        bg: "rgba(217, 119, 6, 0.14)"
      };
    }
    if (syncStatus?.last_sync_status === "failed") {
      return {
        label: "🔴 FIRMS NRT — ERROR",
        color: "#dc2626",
        bg: "rgba(220, 38, 38, 0.12)"
      };
    }
    if (syncStatus?.is_stale) {
      return {
        label: "🔴 FIRMS NRT — STALE",
        color: "#dc2626",
        bg: "rgba(220, 38, 38, 0.12)"
      };
    }
    return {
      label: "🟢 FIRMS NRT — LIVE",
      color: "#16a34a",
      bg: "rgba(34, 197, 94, 0.12)"
    };
  };

  const presets = [
    { key: "TODAY", label: "TODAY" },
    { key: "3D", label: "3 DAYS" },
    { key: "7D", label: "7 DAYS" },
    { key: "10D", label: "10 DAYS" },
    { key: "30D", label: "30 DAYS" },
    { key: "CUSTOM", label: "CUSTOM" }
  ];

  const handlePresetClick = (key) => {
    setCustomFormError(null);
    selectPreset(key);
    if (key === "CUSTOM") {
      setLocalStart(startDate);
      setLocalEnd(endDate);
    }
  };

  const handleCustomSubmit = (e) => {
    e.preventDefault();
    if (!localStart || !localEnd) {
      setCustomFormError("Both start and end dates are required.");
      return;
    }
    if (localStart > localEnd) {
      setCustomFormError("Start date must be earlier than or equal to end date.");
      return;
    }
    setCustomFormError(null);
    applyCustomRange(localStart, localEnd);
  };

  // Format date display (e.g. 28 Sep 2026)
  const formatFriendlyDate = (dateStr) => formatDisplayDate(dateStr);

  return (
    <section className="control-panel temporal-firms-panel" aria-label="FIRMS Temporal Hotspot Controls">
      <div className="panel-heading">
        <span>FIRMS HOTSPOTS</span>
        <span
          className="panel-status"
          style={{
            background: loading ? "rgba(234, 88, 12, 0.15)" : "rgba(34, 197, 94, 0.15)",
            color: loading ? "#ea580c" : "#16a34a",
            fontWeight: 700
          }}
        >
          {loading ? "FETCHING..." : "LIVE"}
        </span>
      </div>

      {/* QUICK PRESETS */}
      <div className="firms-presets-row" role="group" aria-label="Date range quick presets">
        {presets.map(({ key, label }) => {
          const isActive = activePreset === key;
          return (
            <button
              key={key}
              type="button"
              className={`firms-preset-btn ${isActive ? "active" : ""}`}
              onClick={() => handlePresetClick(key)}
              aria-pressed={isActive}
              title={`Select ${label}`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* CUSTOM DATE FORM */}
      {activePreset === "CUSTOM" && (
        <form className="firms-custom-form" onSubmit={handleCustomSubmit}>
          <div className="firms-date-inputs">
            <div className="firms-date-field">
              <label htmlFor="firms-start-date">START DATE</label>
              <input
                id="firms-start-date"
                type="date"
                value={localStart}
                onChange={(e) => {
                  setLocalStart(e.target.value);
                  setCustomFormError(null);
                }}
                required
              />
            </div>
            <div className="firms-date-field">
              <label htmlFor="firms-end-date">END DATE</label>
              <input
                id="firms-end-date"
                type="date"
                value={localEnd}
                onChange={(e) => {
                  setLocalEnd(e.target.value);
                  setCustomFormError(null);
                }}
                required
              />
            </div>
          </div>

          {(customFormError || validationError) && (
            <div className="firms-validation-msg" role="alert">
              ⚠️ {customFormError || validationError}
            </div>
          )}

          <button type="submit" className="firms-apply-btn" disabled={loading}>
            {loading ? "Loading…" : "APPLY RANGE"}
          </button>
        </form>
      )}

      {/* TIMELINE PLAYBACK / SCRUBBER CONTROL (STAGE 2B) */}
      <TimelinePlaybackControl
        startDate={startDate}
        endDate={endDate}
        playbackDate={playbackDate}
        playbackDates={playbackDates}
        isPlaying={isPlaying}
        togglePlay={togglePlay}
        nextDay={nextDay}
        prevDay={prevDay}
        setPlaybackDate={setPlaybackDate}
        loading={loading}
        total={total}
      />

      {/* STATUS & SUMMARY */}
      <div className="firms-summary-box">
        {loading ? (
          <div className="firms-loading-indicator">
            <span className="firms-spinner" aria-hidden="true" />
            <span>Loading hotspots for {playbackDate || startDate}…</span>
          </div>
        ) : error ? (
          <div className="firms-error-state" role="alert">
            <div className="firms-error-msg">⚠️ {error}</div>
            <button type="button" className="firms-retry-btn" onClick={retry}>
              Retry
            </button>
          </div>
        ) : total === 0 ? (
          <div className="firms-empty-state">
            <strong>NO FIRMS HOTSPOTS</strong>
            <p>No thermal observations were returned for the selected date.</p>
          </div>
        ) : (
          <div className="firms-count-display">
            <div className="firms-count-row">
              <strong className="firms-count-number">{total.toLocaleString()}</strong>
              <span className="firms-count-label">observations</span>
            </div>
            <div className="firms-date-badge">
              📅 {playbackDate || startDate} (Playback)
            </div>
            {startDate !== endDate && (
              <div className="firms-range-subbadge">
                Window: {formatFriendlyDate(startDate)} → {formatFriendlyDate(endDate)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* NASA FIRMS NEAR-REAL-TIME MONITORING (PHASE 4) */}
      {(() => {
        const badge = getSyncBadge();
        return (
          <div
            className="firms-sync-bar"
            aria-label="NASA FIRMS near-real-time monitoring"
            title="NASA FIRMS near-real-time monitoring"
          >
            <div className="firms-sync-header">
              <span className="firms-sync-title" title="NASA FIRMS near-real-time monitoring">
                NASA FIRMS NRT
              </span>
              <span
                className="firms-sync-badge"
                style={{
                  color: badge.color,
                  background: badge.bg,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px"
                }}
              >
                {badge.label}
              </span>
            </div>
            <div className="firms-sync-info-row">
              <span>
                Last: <strong>{formatTimeUTC(syncStatus?.last_successful_sync_completed_at || syncStatus?.last_sync_completed_at)}</strong>
              </span>
              <span>
                Next: <strong>{getNextSyncCountdown()}</strong>
              </span>
            </div>
            <div className="firms-sync-action-row">
              <button
                type="button"
                className="firms-sync-now-btn"
                onClick={handleSyncNow}
                disabled={syncingNow || syncStatus?.is_syncing}
                title="Trigger manual on-demand FIRMS synchronization"
              >
                {syncingNow ? "Syncing…" : "Sync Now"}
              </button>
              {(syncFeedback || (syncStatus?.last_sync_inserted > 0 && `+${syncStatus.last_sync_inserted} new`)) && (
                <span
                  className="firms-sync-feedback"
                  style={{
                    color: "#16a34a",
                    background: "rgba(34, 197, 94, 0.12)",
                    padding: "1px 5px",
                    borderRadius: "3px"
                  }}
                >
                  {syncFeedback || `+${syncStatus.last_sync_inserted} new`}
                </span>
              )}
              <span style={{ marginLeft: "auto", fontSize: "7.5px", color: "#94a3b8" }}>
                15m cycle
              </span>
            </div>
          </div>
        );
      })()}
    </section>
  );
}
