/**
 * Centralized Date Arithmetic and Formatting Utility for AGNIVISION.
 * Ensures all components derive date ranges dynamically from the runtime current date,
 * strictly handling month boundaries, leap years, and year crossings.
 */

export function parseISODate(dateStr) {
  if (!dateStr) return null;
  const cleanStr = String(dateStr).split("T")[0].trim();
  const parts = cleanStr.split("-").map(Number);
  if (parts.length !== 3 || parts.some(isNaN)) return null;
  const [y, m, d] = parts;
  return new Date(y, m - 1, d);
}

export function formatISODate(d) {
  if (!d) return "";
  if (typeof d === "string") {
    const clean = d.split("T")[0].trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(clean)) return clean;
    const parsed = parseISODate(d);
    if (!parsed) return "";
    d = parsed;
  }
  if (!(d instanceof Date) || isNaN(d.getTime())) return "";
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function getToday(refDate = null) {
  if (refDate) {
    if (typeof refDate === "string") {
      const parsed = parseISODate(refDate);
      if (parsed) return parsed;
    } else if (refDate instanceof Date && !isNaN(refDate.getTime())) {
      return new Date(refDate.getFullYear(), refDate.getMonth(), refDate.getDate());
    }
  }
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function subtractDays(baseDate, days) {
  const d = typeof baseDate === "string" 
    ? parseISODate(baseDate) 
    : new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
  if (!d || isNaN(d.getTime())) return new Date();
  d.setDate(d.getDate() - Number(days || 0));
  return d;
}

export function addDays(baseDate, days) {
  const d = typeof baseDate === "string" 
    ? parseISODate(baseDate) 
    : new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
  if (!d || isNaN(d.getTime())) return new Date();
  d.setDate(d.getDate() + Number(days || 0));
  return d;
}

export function calculateDateRange(presetKey, refDate = null) {
  const end = getToday(refDate);
  let daysAgo = 0;

  switch (presetKey) {
    case "TODAY":
      daysAgo = 0; // 1 calendar day inclusive
      break;
    case "3D":
      daysAgo = 2; // 3 calendar days inclusive
      break;
    case "7D":
      daysAgo = 6; // 7 calendar days inclusive
      break;
    case "10D":
      daysAgo = 9; // 10 calendar days inclusive
      break;
    case "30D":
      daysAgo = 29; // 30 calendar days inclusive
      break;
    default:
      daysAgo = 9;
  }

  const start = subtractDays(end, daysAgo);

  return {
    preset: presetKey || "10D",
    startDate: formatISODate(start),
    endDate: formatISODate(end)
  };
}

export function generatePlaybackDates(startDateStr, endDateStr) {
  if (!startDateStr || !endDateStr) return [];
  if (startDateStr > endDateStr) return [startDateStr];

  const start = parseISODate(startDateStr);
  const end = parseISODate(endDateStr);
  if (!start || !end) return [];

  const dates = [];
  const curr = new Date(start.getFullYear(), start.getMonth(), start.getDate());

  while (curr <= end) {
    dates.push(formatISODate(curr));
    curr.setDate(curr.getDate() + 1);
  }
  return dates;
}

export function formatDisplayDate(dateStrOrObj, formatStyle = "en-GB") {
  if (!dateStrOrObj) return "";
  let d;
  if (typeof dateStrOrObj === "string") {
    d = parseISODate(dateStrOrObj);
  } else if (dateStrOrObj instanceof Date) {
    d = dateStrOrObj;
  }
  if (!d || isNaN(d.getTime())) return String(dateStrOrObj);

  const monthsShort = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const year = d.getFullYear();
  const month = monthsShort[d.getMonth()];
  const day = d.getDate();

  if (formatStyle === "US" || formatStyle === "medium") {
    return `${month} ${day}, ${year}`;
  }
  // Default en-GB: "28 Sep 2026"
  return `${day} ${month} ${year}`;
}

export function formatDisplayUtc(isoStr) {
  if (!isoStr) return "Pending";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = months[d.getUTCMonth()];
    const day = String(d.getUTCDate()).padStart(2, "0");
    const year = d.getUTCFullYear();
    const h = String(d.getUTCHours()).padStart(2, "0");
    const min = String(d.getUTCMinutes()).padStart(2, "0");
    return `${m} ${day}, ${year} · ${h}:${min} UTC`;
  } catch {
    return isoStr;
  }
}
