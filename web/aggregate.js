// Aggregation helpers: pure functions over the normalised rows array.
// Kept in its own file so it's easy to swap to server-side later if needed.

const SITES = ["Aldbrough", "Atwick"];
const RECENT_HOURS_DEFAULT = 24;
const TIMELINE_DAYS_DEFAULT = 30;

function parseTs(s) {
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

function isLive(r, nowMs) {
  const start = parseTs(r.event_start);
  const stop = parseTs(r.event_stop);
  if (start == null || stop == null) return false;
  return start <= nowMs && nowMs <= stop;
}

function overlaps(a, b) {
  const aStart = parseTs(a.event_start);
  const aStop  = parseTs(a.event_stop);
  const bStart = parseTs(b.event_start);
  const bStop  = parseTs(b.event_stop);
  if ([aStart, aStop, bStart, bStop].some((v) => v == null)) return false;
  return aStart < bStop && bStart < aStop;
}

function rowsForSite(rows, site) {
  const s = site.toLowerCase();
  return rows.filter((r) => (r.asset || "").toLowerCase() === s);
}

// --- recent changes ---------------------------------------------------------

function computeRecentChanges(rows, hours = RECENT_HOURS_DEFAULT) {
  const cutoff = Date.now() - hours * 3600 * 1000;
  let newCount = 0;
  let revisedCount = 0;
  for (const r of rows) {
    const pub = parseTs(r.publication_dt);
    if (pub == null || pub < cutoff) continue;
    if ((r.revision_number ?? 1) > 1) revisedCount += 1;
    else newCount += 1;
  }
  return { hours, new: newCount, revised: revisedCount, total: newCount + revisedCount };
}

// --- KPIs -------------------------------------------------------------------

function computeKpis(rows, nowMs = Date.now()) {
  const live = rows.filter((r) => isLive(r, nowMs));
  const liveByType = { planned: 0, unplanned: 0, other: 0 };
  for (const r of live) {
    const t = (r.type_of_unavailability || "").toLowerCase();
    if (t === "planned") liveByType.planned += 1;
    else if (t === "unplanned") liveByType.unplanned += 1;
    else liveByType.other += 1;
  }
  const upcoming7d = rows.filter((r) => {
    const start = parseTs(r.event_start);
    if (start == null) return false;
    const diffH = (start - nowMs) / 3600000;
    return diffH > 0 && diffH <= 24 * 7;
  });
  return {
    live_count: live.length,
    live_planned: liveByType.planned,
    live_unplanned: liveByType.unplanned,
    upcoming_7d: upcoming7d.length,
  };
}

// --- per-site headlines -----------------------------------------------------

function computeSiteHeadline(rows, site, nowMs = Date.now()) {
  const ownRows = rowsForSite(rows, site);
  const live = ownRows.filter((r) => isLive(r, nowMs));
  if (live.length === 0) {
    // Find next upcoming.
    const upcoming = ownRows
      .filter((r) => {
        const s = parseTs(r.event_start);
        return s != null && s > nowMs;
      })
      .sort((a, b) => parseTs(a.event_start) - parseTs(b.event_start));
    const next = upcoming[0];
    return {
      site,
      state: "idle",
      headline: "No live unavailability",
      detail: next
        ? `Next: ${next.type_of_event} from ${formatShort(next.event_start)} (${formatNum(next.unavailable_capacity)} ${next.unit_of_measurement || ""})`
        : "No upcoming events scheduled",
      live_rows: [],
    };
  }
  // Aggregate live: sum unavailable, take most-recent reason
  let totalUnavail = 0;
  let uom = "";
  const reasons = new Set();
  const types = new Set();
  for (const r of live) {
    if (r.unavailable_capacity != null) totalUnavail += Number(r.unavailable_capacity) || 0;
    if (r.unit_of_measurement) uom = r.unit_of_measurement;
    if (r.reason) reasons.add(r.reason);
    if (r.type_of_event) types.add(r.type_of_event);
  }
  return {
    site,
    state: live.some((r) => (r.type_of_unavailability || "").toLowerCase() === "unplanned") ? "unplanned" : "planned",
    headline: `${formatNum(totalUnavail)} ${uom} offline — ${[...types].join(", ")}`,
    detail: `${live.length} live REMIT${live.length === 1 ? "" : "s"}${reasons.size ? " · " + [...reasons].join(", ") : ""}`,
    live_rows: live,
  };
}

// --- capacity timeline ------------------------------------------------------

function computeCapacityTimeline(rows, site, days = TIMELINE_DAYS_DEFAULT, nowMs = Date.now()) {
  // Bucket by day. For each day, sum the unavailable_capacity of every REMIT
  // (regardless of status) whose [start, stop] window covers that day.
  const oneDay = 86400 * 1000;
  const startOfToday = new Date(nowMs);
  startOfToday.setHours(0, 0, 0, 0);
  const labels = [];
  const total = [];
  const planned = [];
  const unplanned = [];
  const ownRows = rowsForSite(rows, site);

  for (let i = 0; i < days; i++) {
    const dayStart = startOfToday.getTime() + i * oneDay;
    const dayEnd = dayStart + oneDay - 1;
    labels.push(new Date(dayStart).toISOString().slice(0, 10));
    let tSum = 0, pSum = 0, uSum = 0;
    for (const r of ownRows) {
      const s = parseTs(r.event_start);
      const e = parseTs(r.event_stop);
      if (s == null || e == null) continue;
      if (e < dayStart || s > dayEnd) continue;
      const cap = Number(r.unavailable_capacity) || 0;
      tSum += cap;
      const ut = (r.type_of_unavailability || "").toLowerCase();
      if (ut === "planned") pSum += cap;
      else if (ut === "unplanned") uSum += cap;
    }
    total.push(tSum);
    planned.push(pSum);
    unplanned.push(uSum);
  }
  return { labels, total, planned, unplanned };
}

// --- conflicts --------------------------------------------------------------

function computeConflicts(rows) {
  // Pairs of REMITs at the same site with overlapping event windows.
  const out = [];
  for (const site of SITES) {
    const own = rowsForSite(rows, site);
    for (let i = 0; i < own.length; i++) {
      for (let j = i + 1; j < own.length; j++) {
        const a = own[i], b = own[j];
        if (!overlaps(a, b)) continue;
        // Skip pairs that share a thread_id (same outage revisions).
        if (a.thread_id && a.thread_id === b.thread_id) continue;
        out.push({ site, a, b });
      }
    }
  }
  return out;
}

// --- formatting helpers used by aggregations themselves ---------------------

function formatNum(v) {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatShort(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

window.REMITAggregates = {
  SITES,
  isLive,
  computeRecentChanges,
  computeKpis,
  computeSiteHeadline,
  computeCapacityTimeline,
  computeConflicts,
};
