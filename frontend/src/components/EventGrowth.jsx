import React, { useState, useMemo, useRef, useEffect } from "react";

function formatShortDate(dateStr) {
  if (!dateStr) return "";
  if (dateStr.startsWith("Week of ")) {
    const raw = dateStr.replace("Week of ", "");
    return `Wk ${formatShortDate(raw)}`;
  }
  const parts = dateStr.split("-");
  if (parts.length === 3) {
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ];
    const mIdx = parseInt(parts[1], 10) - 1;
    const day = parseInt(parts[2], 10);
    if (mIdx >= 0 && mIdx < 12) {
      return `${months[mIdx]} ${day}`;
    }
  }
  return dateStr;
}

export default function EventGrowth({ fires = [] }) {
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(540);
  const [hoveredBar, setHoveredBar] = useState(null);

  // Extract min and max dates from actual fires
  const allDates = useMemo(() => {
    const dates = Array.from(
      new Set(
        fires
          .map((f) => f?.acq_date)
          .filter((d) => d && typeof d === "string")
      )
    ).sort();
    return dates;
  }, [fires]);

  // Determine observation window boundaries directly from active observation range
  const { windowStart, windowEnd } = useMemo(() => {
    if (allDates.length === 0) return { windowStart: "", windowEnd: "" };
    return {
      windowStart: allDates[0],
      windowEnd: allDates[allDates.length - 1]
    };
  }, [allDates]);

  const minDate = windowStart || allDates[0] || "";
  const maxDate = windowEnd || allDates[allDates.length - 1] || "";

  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [interval, setInterval] = useState("daily"); // "daily" | "weekly"

  const effectiveFrom = fromDate || minDate;
  const effectiveTo = toDate || maxDate;

  // Responsive container width measuring
  useEffect(() => {
    if (!containerRef.current) return;
    const updateWidth = () => {
      if (containerRef.current) {
        const w = containerRef.current.clientWidth;
        if (w > 50) setContainerWidth(w);
      }
    };
    updateWidth();

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect && entry.contentRect.width > 50) {
          setContainerWidth(entry.contentRect.width);
        }
      }
    });

    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // Aggregate observations into time buckets strictly from FIRMS acq_date
  // In daily mode, every calendar date in the active query window is represented
  const chartData = useMemo(() => {
    if (!fires || fires.length === 0) return [];

    const dateCounts = {};

    for (const f of fires) {
      const d = f?.acq_date;
      if (!d) continue;
      if (effectiveFrom && d < effectiveFrom) continue;
      if (effectiveTo && d > effectiveTo) continue;

      dateCounts[d] = (dateCounts[d] || 0) + 1;
    }

    // Build contiguous calendar dates within effective window
    const calendarDates = [];
    if (effectiveFrom && effectiveTo) {
      let cur = new Date(effectiveFrom + "T00:00:00Z");
      const end = new Date(effectiveTo + "T00:00:00Z");
      while (cur <= end) {
        const yyyy = cur.getUTCFullYear();
        const mm = String(cur.getUTCMonth() + 1).padStart(2, "0");
        const dd = String(cur.getUTCDate()).padStart(2, "0");
        calendarDates.push(`${yyyy}-${mm}-${dd}`);
        cur.setUTCDate(cur.getUTCDate() + 1);
      }
    } else {
      calendarDates.push(...Object.keys(dateCounts).sort());
    }

    if (interval === "weekly") {
      // Group contiguous dates into 7-day windows
      const weeks = [];
      let currentWeekStart = calendarDates[0];
      let currentCount = 0;
      let daysInWeek = 0;

      for (const d of calendarDates) {
        currentCount += dateCounts[d] || 0;
        daysInWeek++;
        if (daysInWeek >= 7) {
          weeks.push({
            label: `Week of ${currentWeekStart}`,
            count: currentCount
          });
          currentWeekStart = d;
          currentCount = 0;
          daysInWeek = 0;
        }
      }
      if (daysInWeek > 0 && currentWeekStart) {
        weeks.push({
          label: `Week of ${currentWeekStart}`,
          count: currentCount
        });
      }
      return weeks;
    }

    // Daily Mode: every calendar day rendered, missing dates show 0
    return calendarDates.map((d) => ({
      label: d,
      count: dateCounts[d] || 0
    }));
  }, [fires, effectiveFrom, effectiveTo, interval]);

  const totalInRange = chartData.reduce((sum, item) => sum + item.count, 0);
  const peakItem = chartData.reduce(
    (max, item) => (item.count > (max?.count || 0) ? item : max),
    null
  );
  const avgVal =
    chartData.length > 0 ? (totalInRange / chartData.length).toFixed(1) : "0";

  // SVG Chart Geometry
  const chartHeight = 260;
  const paddingLeft = 48;
  const paddingRight = 16;
  const paddingTop = 24;
  const paddingBottom = 46;

  const plotWidth = Math.max(100, containerWidth - paddingLeft - paddingRight);
  const plotHeight = chartHeight - paddingTop - paddingBottom;

  const maxVal = Math.max(...chartData.map((d) => d.count), 1);

  // Compute clean round Y-axis ticks
  const { ticks, yMax } = useMemo(() => {
    const rawStep = maxVal / 4;
    let step = 1;
    if (rawStep > 50) step = Math.ceil(rawStep / 25) * 25;
    else if (rawStep > 20) step = Math.ceil(rawStep / 10) * 10;
    else if (rawStep > 10) step = Math.ceil(rawStep / 5) * 5;
    else if (rawStep > 2) step = Math.ceil(rawStep / 2) * 2;
    else step = Math.ceil(rawStep);
    if (step < 1) step = 1;

    const topTick = step * 4;
    return {
      step,
      yMax: topTick,
      ticks: [0, step, step * 2, step * 3, topTick]
    };
  }, [maxVal]);

  const tooltipRef = useRef(null);
  const [tooltipDim, setTooltipDim] = useState({ width: 140, height: 56 });

  useEffect(() => {
    if (tooltipRef.current) {
      const rect = tooltipRef.current.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setTooltipDim({ width: rect.width, height: rect.height });
      }
    }
  }, [hoveredBar]);

  // Calculate intelligent bounded tooltip position
  const tooltipPos = useMemo(() => {
    if (!hoveredBar) return null;

    const tWidth = tooltipDim.width || 140;
    const tHeight = tooltipDim.height || 56;
    const wrapperHeight = chartHeight + 16; // 276px (.growth-chart-wrapper has padding: 8px 0)

    const { centerX, barWidth, barY } = hoveredBar;

    // Check if tooltip fits safely above the bar inside chart container
    const fitsAbove = barY - tHeight - 8 >= 8;

    let targetX;
    let targetY;

    if (fitsAbove) {
      // Normal bar: position centered directly above bar
      targetX = centerX - tWidth / 2;
      targetY = barY - tHeight - 8;
    } else {
      // Tall bar (e.g. 99 obs): would escape the top. Position to the side of the bar.
      const fitsRight = centerX + barWidth / 2 + tWidth + 12 <= containerWidth - 8;
      if (fitsRight) {
        targetX = centerX + barWidth / 2 + 10;
      } else {
        targetX = centerX - barWidth / 2 - tWidth - 10;
      }
      targetY = Math.max(8, Math.min(barY, wrapperHeight - tHeight - 8));
    }

    // Strict boundary clamping guarantees tooltip NEVER escapes chart wrapper
    const safeX = Math.max(8, Math.min(targetX, containerWidth - tWidth - 8));
    const safeY = Math.max(8, Math.min(targetY, wrapperHeight - tHeight - 8));

    return { x: safeX, y: safeY };
  }, [hoveredBar, tooltipDim, containerWidth, chartHeight]);

  return (
    <div className="dashboard-panel event-growth-panel">
      {/* 1. HEADER ROW */}
      <div className="growth-header-row">
        <div className="growth-header-title">
          <h3>Event Growth</h3>
          <p className="panel-subtitle">
            Temporal distribution of thermal detections across the active NASA FIRMS query window
          </p>
        </div>

        {/* TOP-RIGHT CONTROLS */}
        <div className="growth-header-controls">
          <div className="growth-date-pickers">
            <label className="date-field">
              <span className="date-field-label">From:</span>
              <input
                type="date"
                value={effectiveFrom}
                min={minDate}
                max={maxDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="growth-date-input"
              />
            </label>

            <label className="date-field">
              <span className="date-field-label">To:</span>
              <input
                type="date"
                value={effectiveTo}
                min={minDate}
                max={maxDate}
                onChange={(e) => setToDate(e.target.value)}
                className="growth-date-input"
              />
            </label>

            {(fromDate || toDate) && (
              <button
                type="button"
                className="growth-reset-btn"
                onClick={() => {
                  setFromDate("");
                  setToDate("");
                }}
                title="Reset date range to full FIRMS window"
              >
                Reset
              </button>
            )}
          </div>

          <div className="interval-toggle-group">
            <button
              type="button"
              className={`interval-btn ${interval === "daily" ? "active" : ""}`}
              onClick={() => setInterval("daily")}
            >
              Daily
            </button>
            <button
              type="button"
              className={`interval-btn ${interval === "weekly" ? "active" : ""}`}
              onClick={() => setInterval("weekly")}
            >
              Weekly
            </button>
          </div>
        </div>
      </div>

      {/* 2. SUMMARY STRIP */}
      <div className="growth-summary-strip">
        <div className="summary-stat-box">
          <span className="stat-label">WINDOW OBSERVATIONS</span>
          <strong className="stat-value">{totalInRange}</strong>
        </div>
        <div className="summary-stat-box">
          <span className="stat-label">PEAK PERIOD</span>
          <strong className="stat-value">
            {peakItem ? `${formatShortDate(peakItem.label)} (${peakItem.count})` : "—"}
          </strong>
        </div>
        <div className="summary-stat-box">
          <span className="stat-label">PERIOD AVERAGE</span>
          <strong className="stat-value">{avgVal} / period</strong>
        </div>
      </div>

      {/* 3. PROPER BAR CHART */}
      {chartData.length === 0 ? (
        <div className="growth-empty-state">
          <span>📅</span>
          <p>No observations in selected range</p>
        </div>
      ) : (
        <div className="growth-chart-wrapper" ref={containerRef}>
          <svg
            width={containerWidth}
            height={chartHeight}
            className="growth-svg-chart"
            aria-label="Event Growth Bar Chart"
          >
            <defs>
              <linearGradient id="growthBarGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" />
                <stop offset="100%" stopColor="#1d4ed8" />
              </linearGradient>
              <linearGradient id="growthPeakBarGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2563eb" />
                <stop offset="100%" stopColor="#0f172a" />
              </linearGradient>
            </defs>

            {/* HORIZONTAL GRID LINES & Y-AXIS LABELS */}
            {ticks.map((t) => {
              const y = paddingTop + plotHeight - (t / yMax) * plotHeight;
              return (
                <g key={`y-tick-${t}`}>
                  <line
                    x1={paddingLeft}
                    y1={y}
                    x2={paddingLeft + plotWidth}
                    y2={y}
                    stroke="#e2e8f0"
                    strokeDasharray={t === 0 ? "0" : "3 3"}
                    strokeWidth={t === 0 ? "1.5" : "1"}
                  />
                  <text
                    x={paddingLeft - 8}
                    y={y + 3.5}
                    textAnchor="end"
                    fontSize="10"
                    fontWeight="600"
                    fill="#64748b"
                    fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
                  >
                    {t}
                  </text>
                </g>
              );
            })}

            {/* Y-AXIS LEFT LINE */}
            <line
              x1={paddingLeft}
              y1={paddingTop}
              x2={paddingLeft}
              y2={paddingTop + plotHeight}
              stroke="#cbd5e1"
              strokeWidth="1.5"
            />

            {/* VERTICAL BARS */}
            {chartData.map((item, idx) => {
              const slotWidth = plotWidth / chartData.length;
              const barWidth = Math.min(38, Math.max(12, slotWidth * 0.52));
              const centerX = paddingLeft + (idx + 0.5) * slotWidth;
              const barX = centerX - barWidth / 2;
              const hasCount = item.count > 0;
              const barH = hasCount ? Math.max(4, (item.count / yMax) * plotHeight) : 2;
              const barY = paddingTop + plotHeight - barH;
              const isPeak = hasCount && item.count === peakItem?.count;
              const isHovered = hoveredBar?.label === item.label;

              return (
                <g
                  key={`bar-group-${item.label}`}
                  className="bar-interactive-group"
                  onMouseEnter={() => {
                    setHoveredBar({
                      ...item,
                      centerX,
                      barWidth,
                      barY: barY + 8
                    });
                  }}
                  onMouseMove={() => {
                    setHoveredBar((prev) =>
                      prev
                        ? {
                            ...prev,
                            centerX,
                            barWidth,
                            barY: barY + 8
                          }
                        : null
                    );
                  }}
                  onMouseLeave={() => setHoveredBar(null)}
                  style={{ cursor: "pointer" }}
                >
                  {/* HIT SLOT / BACKGROUND HIGHLIGHT ON HOVER */}
                  <rect
                    x={centerX - slotWidth / 2}
                    y={paddingTop}
                    width={slotWidth}
                    height={plotHeight}
                    fill={isHovered ? "rgba(239, 246, 255, 0.6)" : "transparent"}
                    rx={4}
                  />

                  {/* VALUE LABEL ABOVE BAR */}
                  <text
                    x={centerX}
                    y={hasCount ? barY - 6 : barY - 4}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight={hasCount ? "700" : "600"}
                    fill={isPeak ? "#1d4ed8" : hasCount ? "#334155" : "#94a3b8"}
                  >
                    {item.count}
                  </text>

                  {/* BAR RECTANGLE */}
                  <rect
                    x={barX}
                    y={barY}
                    width={barWidth}
                    height={barH}
                    rx={hasCount ? 3 : 1}
                    ry={hasCount ? 3 : 1}
                    fill={
                      !hasCount
                        ? "#cbd5e1"
                        : isPeak
                        ? "url(#growthPeakBarGrad)"
                        : "url(#growthBarGrad)"
                    }
                    stroke={isHovered ? "#1d4ed8" : isPeak ? "#0284c7" : "none"}
                    strokeWidth={isHovered ? 2 : isPeak ? 1 : 0}
                    style={{ transition: "all 0.2s ease" }}
                  />

                  {/* X-AXIS TICK MARK */}
                  <line
                    x1={centerX}
                    y1={paddingTop + plotHeight}
                    x2={centerX}
                    y2={paddingTop + plotHeight + 4}
                    stroke="#94a3b8"
                    strokeWidth="1"
                  />

                  {/* X-AXIS LABEL */}
                  <text
                    x={centerX}
                    y={paddingTop + plotHeight + 17}
                    textAnchor="middle"
                    fontSize="10.5"
                    fontWeight="600"
                    fill="#475569"
                  >
                    {formatShortDate(item.label)}
                  </text>
                </g>
              );
            })}

            {/* X-AXIS BOTTOM TITLE */}
            <text
              x={paddingLeft + plotWidth / 2}
              y={chartHeight - 6}
              textAnchor="middle"
              fontSize="9.5"
              fontWeight="700"
              letterSpacing="0.8"
              fill="#94a3b8"
            >
              NUMBER OF EVENTS
            </text>
          </svg>

          {/* FLOATING HOVER TOOLTIP */}
          {hoveredBar && tooltipPos && (
            <div
              ref={tooltipRef}
              className="chart-hover-tooltip"
              style={{
                left: `${tooltipPos.x}px`,
                top: `${tooltipPos.y}px`
              }}
            >
              <div className="tooltip-date-header">{hoveredBar.label}</div>
              <div className="tooltip-obs-count">
                <strong>{hoveredBar.count}</strong> observations
              </div>
              <div className="tooltip-pct-share">
                {totalInRange > 0
                  ? `${((hoveredBar.count / totalInRange) * 100).toFixed(1)}% of query window`
                  : ""}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 4. DATA INTEGRITY NOTICE */}
      <div className="growth-integrity-notice">
        <span className="notice-icon">ℹ</span>
        <span>
          <strong>Data integrity:</strong> Values represent discrete NASA FIRMS VIIRS satellite observation counts for each acquisition period within the current 10-day NRT query window. No synthetic observations, fabricated historical trends, or persistent event clusters are created.
        </span>
      </div>
    </div>
  );
}

