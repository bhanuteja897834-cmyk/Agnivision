import React from "react";
import { formatDisplayDate } from "../utils/dateUtils.js";

/**
 * Compact timeline scrubber and playback control for NASA FIRMS hotspots.
 * Enables day-by-day playback and granular observation scrubbing across any temporal range.
 */
export default function TimelinePlaybackControl({
  startDate,
  endDate,
  playbackDate,
  playbackDates = [],
  isPlaying,
  togglePlay,
  nextDay,
  prevDay,
  setPlaybackDate,
  loading,
  total
}) {
  const isSingleDay = playbackDates.length <= 1;
  const currentIndex = Math.max(0, playbackDates.indexOf(playbackDate));
  const isFirstDay = currentIndex === 0;
  const isLastDay = currentIndex >= playbackDates.length - 1;

  // Format date display (e.g. "28 Sep 2026")
  const formatShortDate = (dateStr) => formatDisplayDate(dateStr);

  const handleSliderChange = (e) => {
    const idx = parseInt(e.target.value, 10);
    if (idx >= 0 && idx < playbackDates.length) {
      setPlaybackDate(playbackDates[idx]);
    }
  };

  return (
    <div className="firms-timeline-control" aria-label="FIRMS Temporal Playback Control">
      {/* HEADER: TITLE & ACTIVE PLAYBACK DATE */}
      <div className="firms-timeline-header">
        <span className="firms-timeline-title">TIMELINE PLAYBACK</span>
        <span className="firms-playback-badge" title="Active Playback Date">
          {playbackDate || startDate}
        </span>
      </div>

      {/* SELECTED RANGE INDICATOR */}
      <div className="firms-timeline-range-label">
        Range: {startDate} → {endDate} ({playbackDates.length} {playbackDates.length === 1 ? "day" : "days"})
      </div>

      {/* PLAYBACK ACTION BUTTONS */}
      <div className="firms-playback-buttons" role="group" aria-label="Playback control buttons">
        <button
          type="button"
          className="firms-playback-btn prev-btn"
          onClick={prevDay}
          disabled={isFirstDay || loading || isSingleDay}
          title={isFirstDay ? "At start of timeline" : "Step to Previous Day"}
          aria-label="Previous day"
        >
          ◀
        </button>

        <button
          type="button"
          className={`firms-playback-btn play-toggle ${isPlaying ? "playing" : ""}`}
          onClick={togglePlay}
          disabled={isSingleDay}
          title={isSingleDay ? "Single day selected" : isPlaying ? "Pause Playback" : "Start Playback"}
          aria-label={isPlaying ? "Pause playback" : "Play timeline"}
        >
          {isPlaying ? "⏸ Pause" : "▶ Play"}
        </button>

        <button
          type="button"
          className="firms-playback-btn next-btn"
          onClick={nextDay}
          disabled={isLastDay || loading || isSingleDay}
          title={isLastDay ? "At end of timeline" : "Step to Next Day"}
          aria-label="Next day"
        >
          ▶
        </button>
      </div>

      {/* RANGE SCRUBBER SLIDER */}
      <div className="firms-timeline-slider-row">
        <input
          type="range"
          className="firms-timeline-slider"
          min={0}
          max={Math.max(0, playbackDates.length - 1)}
          value={currentIndex}
          onChange={handleSliderChange}
          disabled={isSingleDay}
          aria-label="Timeline scrubber"
          aria-valuemin={0}
          aria-valuemax={Math.max(0, playbackDates.length - 1)}
          aria-valuenow={currentIndex}
          aria-valuetext={playbackDate}
        />
        <div className="firms-timeline-ticks">
          <span>{formatShortDate(startDate)}</span>
          {playbackDates.length > 1 && (
            <span className="firms-timeline-mid-tick">
              Day {currentIndex + 1} / {playbackDates.length} → {formatShortDate(playbackDate || startDate)}
            </span>
          )}
          <span>{formatShortDate(endDate)}</span>
        </div>
      </div>
    </div>
  );
}
