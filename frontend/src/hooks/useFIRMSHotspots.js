import { useState, useEffect, useRef, useCallback } from "react";
import { fetchFIRMSHotspots, fetchFIRMSClusters } from "../api/firmsApi.js";
import {
  formatISODate,
  calculateDateRange,
  generatePlaybackDates
} from "../utils/dateUtils.js";

/**
 * Format a Date object to YYYY-MM-DD.
 */
export function formatDateYMD(d) {
  return formatISODate(d);
}

/**
 * Get date range for standard quick presets.
 * End date is always inclusive today.
 */
export function getPresetDateRange(presetKey, baseDate = new Date()) {
  return calculateDateRange(presetKey, baseDate);
}

/**
 * Generate an inclusive sequence of ISO date strings (YYYY-MM-DD) between startDate and endDate.
 */
export function generateDateSequence(startDate, endDate) {
  return generatePlaybackDates(startDate, endDate);
}

/**
 * Custom React hook for querying and managing NASA FIRMS temporal hotspots and timeline playback.
 *
 * @param {Object} options
 * @param {string} [options.initialPreset="10D"] - Initial active preset
 * @param {string} [options.bbox] - Optional bounding box filter
 * @param {string} [options.satellite] - Optional satellite filter
 * @param {string} [options.source] - Optional source filter
 * @param {number} [options.initialSpeedMs=1500] - Playback step interval in ms
 */
export function useFIRMSHotspots({
  initialPreset = "10D",
  externalDateRange = null,
  bbox = null,
  satellite = null,
  source = null,
  initialSpeedMs = 1500
} = {}) {
  const initialRange = externalDateRange?.startDate && externalDateRange?.endDate
    ? { startDate: externalDateRange.startDate, endDate: externalDateRange.endDate }
    : getPresetDateRange(initialPreset);

  const [activePreset, setActivePreset] = useState(externalDateRange?.preset || initialPreset);
  const [startDate, setStartDate] = useState(initialRange.startDate);
  const [endDate, setEndDate] = useState(initialRange.endDate);

  const [customStart, setCustomStart] = useState(initialRange.startDate);
  const [customEnd, setCustomEnd] = useState(initialRange.endDate);
  const [validationError, setValidationError] = useState(null);

  // Sync with external date range (e.g. from App / Dashboard state)
  useEffect(() => {
    if (!externalDateRange) return;
    const { preset, startDate: extStart, endDate: extEnd } = externalDateRange;
    if (
      extStart &&
      extEnd &&
      (extStart !== startDate || extEnd !== endDate || (preset && preset !== activePreset))
    ) {
      setActivePreset(preset || "CUSTOM");
      setStartDate(extStart);
      setEndDate(extEnd);
      setCustomStart(extStart);
      setCustomEnd(extEnd);
      setPlaybackDate(extStart);
      setIsPlaying(false);
    }
  }, [externalDateRange?.startDate, externalDateRange?.endDate, externalDateRange?.preset]);

  // Playback timeline state (Stage 2B)
  const [playbackDate, setPlaybackDate] = useState(initialRange.startDate);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeedMs, setPlaybackSpeedMs] = useState(initialSpeedMs);

  const [hotspots, setHotspots] = useState([]);
  const [clusters, setClusters] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [refetchIndex, setRefetchIndex] = useState(0);
  const abortControllerRef = useRef(null);

  // Computed sequence of dates in the active range
  const playbackDates = generateDateSequence(startDate, endDate);

  // Reconcile playback date whenever startDate or endDate changes
  useEffect(() => {
    setIsPlaying(false);
    if (!playbackDates.includes(playbackDate)) {
      setPlaybackDate(startDate);
    }
  }, [startDate, endDate]);

  // Apply a quick preset
  const selectPreset = useCallback((presetKey) => {
    setValidationError(null);
    setActivePreset(presetKey);
    setIsPlaying(false);

    if (presetKey === "CUSTOM") {
      return;
    }

    const range = getPresetDateRange(presetKey);
    setStartDate(range.startDate);
    setEndDate(range.endDate);
    setCustomStart(range.startDate);
    setCustomEnd(range.endDate);
    setPlaybackDate(range.startDate);
  }, []);

  // Apply a custom date range with validation
  const applyCustomRange = useCallback((newStart, newEnd) => {
    const s = String(newStart || "").trim();
    const e = String(newEnd || "").trim();

    if (!s || !e) {
      setValidationError("Both start and end dates are required.");
      return false;
    }

    if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || !/^\d{4}-\d{2}-\d{2}$/.test(e)) {
      setValidationError("Dates must use YYYY-MM-DD format.");
      return false;
    }

    if (s > e) {
      setValidationError("Start date must be earlier than or equal to end date.");
      return false;
    }

    setValidationError(null);
    setActivePreset("CUSTOM");
    setIsPlaying(false);
    setStartDate(s);
    setEndDate(e);
    setPlaybackDate(s);
    return true;
  }, []);

  // Playback controls
  const play = useCallback(() => {
    if (playbackDates.length <= 1) return;
    const currIdx = playbackDates.indexOf(playbackDate);
    if (currIdx >= playbackDates.length - 1) {
      // If at end, restart from beginning
      setPlaybackDate(playbackDates[0]);
    }
    setIsPlaying(true);
  }, [playbackDate, playbackDates]);

  const pause = useCallback(() => {
    setIsPlaying(false);
  }, []);

  const togglePlay = useCallback(() => {
    if (isPlaying) {
      pause();
    } else {
      play();
    }
  }, [isPlaying, pause, play]);

  const nextDay = useCallback(() => {
    pause();
    const currIdx = playbackDates.indexOf(playbackDate);
    if (currIdx < playbackDates.length - 1) {
      setPlaybackDate(playbackDates[currIdx + 1]);
    }
  }, [playbackDate, playbackDates, pause]);

  const prevDay = useCallback(() => {
    pause();
    const currIdx = playbackDates.indexOf(playbackDate);
    if (currIdx > 0) {
      setPlaybackDate(playbackDates[currIdx - 1]);
    }
  }, [playbackDate, playbackDates, pause]);

  const selectPlaybackDate = useCallback(
    (targetDate) => {
      pause();
      if (playbackDates.includes(targetDate)) {
        setPlaybackDate(targetDate);
      }
    },
    [playbackDates, pause]
  );

  // Playback advancement timer
  useEffect(() => {
    if (!isPlaying) return;
    if (loading) return; // Wait for current day's fetch to finish

    const currIdx = playbackDates.indexOf(playbackDate);
    if (currIdx >= playbackDates.length - 1 || currIdx === -1) {
      // Reached the final date -> stop playback automatically
      setIsPlaying(false);
      return;
    }

    const timer = setTimeout(() => {
      setPlaybackDate(playbackDates[currIdx + 1]);
    }, playbackSpeedMs);

    return () => clearTimeout(timer);
  }, [isPlaying, loading, playbackDate, playbackDates, playbackSpeedMs]);

  // Retry action
  const retry = useCallback(() => {
    setRefetchIndex((i) => i + 1);
  }, []);

  // Fetch FIRMS hotspots for the ACTIVE PLAYBACK DATE
  // GET /api/v1/hotspots?start_date=selected_day&end_date=selected_day
  useEffect(() => {
    const queryDate = playbackDate || startDate;
    if (!queryDate) {
      return;
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let isCancelled = false;
    setLoading(true);
    setError(null);

    async function loadData() {
      try {
        const [hotspotRes, clusterRes] = await Promise.allSettled([
          fetchFIRMSHotspots({
            startDate: queryDate,
            endDate: queryDate,
            bbox,
            satellite,
            source,
            limit: 5000,
            signal: controller.signal
          }),
          fetchFIRMSClusters({
            startDate: queryDate,
            endDate: queryDate,
            spatialRadiusKm: 3.0,
            minObservations: 1,
            bbox,
            satellite,
            source,
            signal: controller.signal
          })
        ]);

        if (controller.signal.aborted || isCancelled) return;

        if (hotspotRes.status === "fulfilled") {
          setHotspots(hotspotRes.value.hotspots || []);
          setTotal(hotspotRes.value.total || 0);
          setError(null);
        } else {
          const err = hotspotRes.reason;
          if (err?.name !== "AbortError") {
            console.error("useFIRMSHotspots error:", err);
            setError(err?.message || "Unable to load FIRMS hotspot data.");
            setHotspots([]);
            setTotal(0);
          }
        }

        if (clusterRes.status === "fulfilled") {
          setClusters(clusterRes.value.clusters || []);
        } else {
          const cErr = clusterRes.reason;
          if (cErr?.name !== "AbortError") {
            console.warn("useFIRMSClusters error:", cErr);
            setClusters([]);
          }
        }
      } catch (err) {
        if (err.name === "AbortError") {
          return;
        }
        if (!isCancelled) {
          console.error("useFIRMSHotspots unexpected error:", err);
          setError(err.message || "Unable to load FIRMS data.");
          setHotspots([]);
          setClusters([]);
          setTotal(0);
        }
      } finally {
        if (!isCancelled && !controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadData();

    return () => {
      isCancelled = true;
      controller.abort();
    };
  }, [playbackDate, startDate, bbox, satellite, source, refetchIndex]);

  return {
    hotspots,
    clusters,
    total,
    loading,
    error,
    startDate,
    endDate,
    playbackDate,
    playbackDates,
    isPlaying,
    playbackSpeedMs,
    setPlaybackSpeedMs,
    play,
    pause,
    togglePlay,
    nextDay,
    prevDay,
    setPlaybackDate: selectPlaybackDate,
    activePreset,
    customStart,
    setCustomStart,
    customEnd,
    setCustomEnd,
    validationError,
    selectPreset,
    applyCustomRange,
    retry
  };
}
