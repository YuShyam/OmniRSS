/**
 * OmniRSS 日期與時區工具模組 (Date & Timezone Utilities).
 *
 * Provides robust ISO-8601 UTC parsing for SQLite naive timestamps,
 * ensuring accurate local time conversions and smart relative formatting.
 */

import { t } from "./i18n.js";
import { store } from "./state.js";

export function parseUtcDate(dateInput) {
  if (!dateInput || dateInput === "null" || dateInput === "undefined") return new Date();
  if (dateInput instanceof Date) return dateInput;

  let str = String(dateInput).trim();
  if (str === "null" || str === "undefined" || !str) return new Date();

  // 若已有明確時區標示 (+08:00, Z 等)，直接解析
  if (str.includes("Z") || str.includes("+") || (str.lastIndexOf("-") > 7 && str.includes("T"))) {
    const d = new Date(str);
    return isNaN(d.getTime()) ? new Date(dateInput) : d;
  }

  // 若為 SQLite 標準格式 "YYYY-MM-DD HH:MM:SS"（naive UTC），補齊 "T" 與 "Z"
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(str)) {
    str = str.replace(" ", "T") + "Z";
  } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(str)) {
    str = str + "Z";
  }

  const d = new Date(str);
  return isNaN(d.getTime()) ? new Date(dateInput) : d;
}

export function formatSmartDate(dateInput, formatMode = "smart") {
  if (!dateInput || dateInput === "null" || dateInput === "undefined") return "";
  try {
    const d = parseUtcDate(dateInput);
    if (isNaN(d.getTime())) return "";
    const now = new Date();

    if (formatMode === "iso") {
      return d.toISOString().replace("T", " ").substring(0, 19);
    }
    if (formatMode === "relative") {
      const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
      if (diffSec < 0 || diffSec < 60) return t("date.just_now");
      if (diffSec < 3600) return t("date.minutes_ago", { n: Math.floor(diffSec / 60) });
      if (diffSec < 86400) return t("date.hours_ago", { n: Math.floor(diffSec / 3600) });
      if (diffSec < 2592000) return t("date.days_ago", { n: Math.floor(diffSec / 86400) });
    }

    const tzPreference = store.get("timezone") || "auto";
    const options = { hour12: false };
    if (tzPreference !== "auto" && tzPreference) {
      options.timeZone = tzPreference;
    }

    const timePart = d.toLocaleTimeString([], { ...options, hour: "2-digit", minute: "2-digit" });
    const isToday = d.toDateString() === now.toDateString();
    if (isToday && tzPreference === "auto") {
      return timePart;
    }

    const parts = new Intl.DateTimeFormat("en-US", {
      ...options,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(d);

    const map = {};
    for (const p of parts) map[p.type] = p.value;

    const isCurrentYear = d.getFullYear() === now.getFullYear();
    if (isCurrentYear) {
      return `${map.month}/${map.day} ${timePart}`;
    }
    return `${map.year}/${map.month}/${map.day} ${timePart}`;
  } catch (_) {
    return "";
  }
}
