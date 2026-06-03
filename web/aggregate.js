// Aggregation helpers: pure functions over the normalised rows array.

const SITES = ["Aldbrough", "Atwick"];
const CATEGORIES = ["Withdrawal", "Injection", "Storage"];
const RECENT_HOURS_DEFAULT = 24;
const TIMELINE_DAYS_DEFAULT = 30;

// Hard-coded nameplate tech max — these are AUTHORITATIVE. Individual REMIT
// rows carry varying technicalCapacity values; the nameplate is the truth.
// Source: app.py TECH_CAPACITY_FALLBACK (lines 79–85).
const TECH_CAPACITY = {
  Aldbrough: { Withdrawal: 287.78, Injection: 293.33, Storage: 3.3 },
  Atwick:    { Withdrawal: 130.0,  Injection: 30.0,   Storage: 3.47 },
};
const TECH_UNITS = {
  Withdrawal: "GWh/d",
  Injection: "GWh/d",
  Storage: "TWh",
};

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

function categorise(typeOfEvent) {
  // typeOfEvent is "Withdrawal unavailability" / "Injection unavailability" /
  // "Storage unavailability". First word is the category.
  if (!typeOfEvent) return null;
  const first = typeOfEvent.trim().split(/\s+/)[0];
  if (CATEGORIES.includes(first)) return first;
  return null;
}

function rowsForSite(rows, site) {
  const s = site.toLowerCase();
  return rows.filter((r) => (r.asset || "").toLowerCase() === s);
}

function rowsForSiteCategory(rows, site, category) {
  return rowsForSite(rows, site).filter((r) => categorise(r.type_of_event) === category);
}

// Dismissed REMITs are issued then cancelled — operators publish them as a
// notice but they don't represent real capacity changes. The old app
// (app.py:2602-2604) filters them out before any capacity math; we do the
// same so the chart / dials / headlines all agree with reality. Conflicts
// apply a stricter "Active only" filter elsewhere per user spec.
function isNotDismissed(r) {
  const s = (r.event_status || "").toLowerCase();
  return !s.includes("dismiss");
}

function operationalRows(rows) {
  return rows.filter(isNotDismissed);
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

// --- top-level KPIs ---------------------------------------------------------

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
  // Split upcoming by planned/unplanned for the sub-line.
  const upcomingByType = { planned: 0, unplanned: 0 };
  for (const r of upcoming7d) {
    const t = (r.type_of_unavailability || "").toLowerCase();
    if (t === "planned") upcomingByType.planned += 1;
    else if (t === "unplanned") upcomingByType.unplanned += 1;
  }
  return {
    live_count: live.length,
    live_planned: liveByType.planned,
    live_unplanned: liveByType.unplanned,
    upcoming_7d: upcoming7d.length,
    upcoming_planned: upcomingByType.planned,
    upcoming_unplanned: upcomingByType.unplanned,
  };
}

// --- per-site, per-category status -----------------------------------------

function computeSiteCategoryStatus(rows, site, category, nowMs = Date.now()) {
  // For one (site, category) pair. Dismissed REMITs excluded — see
  // operationalRows() doc for rationale.
  const own = rowsForSiteCategory(operationalRows(rows), site, category);
  const live = own.filter((r) => isLive(r, nowMs));
  const tech = TECH_CAPACITY[site][category];
  const unit = TECH_UNITS[category];

  let available;
  let unavailable;
  if (live.length === 0) {
    available = tech;
    unavailable = 0;
  } else {
    const avails = live
      .map((r) => (r.available_capacity != null ? Number(r.available_capacity) : null))
      .filter((v) => v != null && !Number.isNaN(v));
    if (avails.length === 0) {
      // Fall back to summing unavailable_capacity (also the user's spec for
      // the headline). Lowest-available rule only applies when SSE actually
      // reports availableCapacity, which it usually does.
      const unavailSum = live.reduce((acc, r) => acc + (Number(r.unavailable_capacity) || 0), 0);
      unavailable = unavailSum;
      available = Math.max(0, tech - unavailSum);
    } else {
      available = Math.min(...avails);
      unavailable = Math.max(0, tech - available);
    }
  }

  const pct = tech > 0 ? Math.max(0, Math.min(1, available / tech)) : 0;
  return {
    site,
    category,
    tech_max: tech,
    unit,
    live_remits: live,
    unavailable_now: unavailable,
    available_now: available,
    pct_available: pct,
  };
}

function computeSiteHeadline(rows, site, nowMs = Date.now()) {
  // Headline shows per-category unavailable for the site. Never sums across
  // categories (TWh and GWh/d don't add).
  const lines = CATEGORIES.map((cat) => {
    const s = computeSiteCategoryStatus(rows, site, cat, nowMs);
    return {
      category: cat,
      unit: s.unit,
      available: s.available_now,
      tech_max: s.tech_max,
      live_count: s.live_remits.length,
    };
  });
  const anyLive = lines.some((l) => l.live_count > 0);
  return {
    site,
    state: anyLive
      ? (rowsForSite(operationalRows(rows), site)
          .filter((r) => isLive(r, nowMs))
          .some((r) => (r.type_of_unavailability || "").toLowerCase() === "unplanned")
        ? "unplanned" : "planned")
      : "idle",
    lines,
    any_live: anyLive,
  };
}

// --- capacity timeline (per direction, step function over breakpoints) -----

const TIMELINE_LOOKBACK_DAYS_DEFAULT = 7;

function computeAvailabilityTimeline(
  rows,
  site,
  days = TIMELINE_DAYS_DEFAULT,
  nowMs = Date.now(),
  lookbackDays = TIMELINE_LOOKBACK_DAYS_DEFAULT,
) {
  // Returns a STEP function — availability is piecewise constant and only
  // changes at REMIT start/stop boundaries. Evaluated per direction
  // (Withdrawal / Injection). Window: [now - lookback, now + horizon].
  //
  // OVERLAP RULE: effective availability at instant t =
  //   MIN(availableCapacity) across all REMITs active at t in this category.
  // Fallback (only if no availableCapacity reported by any of them):
  //   tech_max - SUM(unavailableCapacity).
  // Mirrors app.py:_capacity_at() exactly.
  //
  // Why MIN(available) and not MAX(unavail): individual REMITs report
  // unavailable_capacity as the MARGINAL impact of that REMIT. The
  // availableCapacity field is the absolute system state already accounting
  // for other concurrent REMITs at publication time, so taking max(unavail)
  // misses the cumulative effect.
  //
  // Storage events deliberately excluded — different unit (TWh), not flow.
  const startMs = nowMs - lookbackDays * 86400 * 1000;
  const endMs = nowMs + days * 86400 * 1000;
  const techWithdrawal = TECH_CAPACITY[site].Withdrawal;
  const techInjection = TECH_CAPACITY[site].Injection;

  const opRows = operationalRows(rows);

  function lineFor(category, tech) {
    const catRows = rowsForSiteCategory(opRows, site, category)
      .map((r) => ({
        start: parseTs(r.event_start),
        stop: parseTs(r.event_stop),
        avail: r.available_capacity != null && r.available_capacity !== ""
          ? Number(r.available_capacity)
          : null,
        unavail: r.unavailable_capacity != null && r.unavailable_capacity !== ""
          ? Number(r.unavailable_capacity)
          : null,
      }))
      // Keep any row whose window touches [startMs, endMs]. The lookback
      // pulls in Inactive rows whose stop has passed but is still within
      // the lookback window — that's how we get history into the chart.
      .filter((r) =>
        r.start != null && r.stop != null &&
        r.stop > startMs && r.start < endMs
      );

    const bps = new Set([startMs, endMs]);
    for (const r of catRows) {
      if (r.start > startMs && r.start < endMs) bps.add(r.start);
      if (r.stop > startMs && r.stop < endMs) bps.add(r.stop);
    }
    const sorted = [...bps].sort((a, b) => a - b);

    const data = [];
    for (let i = 0; i < sorted.length - 1; i++) {
      const t1 = sorted[i];
      const t2 = sorted[i + 1];
      const mid = (t1 + t2) / 2;

      const active = catRows.filter((r) => r.start <= mid && mid < r.stop);
      let value;
      if (active.length === 0) {
        value = tech;
      } else {
        const reportedAvails = active.map((r) => r.avail).filter((v) => v != null && !Number.isNaN(v));
        if (reportedAvails.length > 0) {
          value = Math.min(...reportedAvails);
        } else {
          const unavailSum = active.reduce((acc, r) => acc + (r.unavail || 0), 0);
          value = Math.max(0, tech - unavailSum);
        }
      }
      data.push({ x: t1, y: value });
    }
    if (data.length === 0) {
      data.push({ x: startMs, y: tech });
    }
    data.push({ x: endMs, y: data[data.length - 1].y });
    return data;
  }

  return {
    withdrawal_data: lineFor("Withdrawal", techWithdrawal),
    injection_data: lineFor("Injection", techInjection),
    withdrawal_tech: techWithdrawal,
    injection_tech: techInjection,
    start_ms: startMs,
    end_ms: endMs,
    now_ms: nowMs,
  };
}

// --- upcoming events (next N days, text list) -------------------------------

// Sparkline data for one (site, category) — hourly samples of the
// effective availability over the last N hours, derived directly from
// the current snapshot. Doesn't depend on the rolling history buffer,
// so the sparkline is meaningful from the first page load. Uses the
// SAME min(availableCapacity) rule as the dial + chart + conflicts, so
// every view of "what's available right now" agrees.
function computeSparklineData(rows, site, category, hoursBack = 24, nowMs = Date.now()) {
  const techRoot = TECH_CAPACITY[site];
  if (!techRoot) return [];
  const tech = techRoot[category];
  if (tech == null) return [];

  const startMs = nowMs - hoursBack * 3600 * 1000;
  const intervalMs = 60 * 60 * 1000; // 1-hour samples

  const opRows = operationalRows(rows);
  const catRows = rowsForSiteCategory(opRows, site, category)
    .map((r) => ({
      start: parseTs(r.event_start),
      stop: parseTs(r.event_stop),
      avail: r.available_capacity != null && r.available_capacity !== ""
        ? Number(r.available_capacity) : null,
      unavail: Number(r.unavailable_capacity) || 0,
    }))
    .filter((r) =>
      r.start != null && r.stop != null &&
      r.stop > startMs && r.start <= nowMs
    );

  const samples = [];
  for (let t = startMs; t <= nowMs; t += intervalMs) {
    const active = catRows.filter((r) => r.start <= t && t < r.stop);
    let value;
    if (active.length === 0) {
      value = tech;
    } else {
      const reportedAvails = active.map((r) => r.avail).filter((v) => v != null && !Number.isNaN(v));
      if (reportedAvails.length > 0) {
        value = Math.min(...reportedAvails);
      } else {
        const unavailSum = active.reduce((acc, r) => acc + (r.unavail || 0), 0);
        value = Math.max(0, tech - unavailSum);
      }
    }
    samples.push({ t, v: value });
  }
  return samples;
}

function computeUpcomingNext(rows, site, days = 7, nowMs = Date.now()) {
  // Kept for backwards compatibility / future reuse — see
  // computeUpcomingTransitions for the active view the UI renders.
  const horizonStop = nowMs + days * 86400 * 1000;
  const opRows = operationalRows(rows);
  return rowsForSite(opRows, site)
    .filter((r) => {
      const start = parseTs(r.event_start);
      return start != null && start > nowMs && start <= horizonStop;
    })
    .sort((a, b) => Date.parse(a.event_start) - Date.parse(b.event_start));
}

// Upcoming TRANSITIONS — every moment in the next N days where the
// effective availability of a category changes, including current REMITs
// that are clearing (ending). Returns an array of
//   { at_ms, category, from, to, delta, unit, tech_max, starting[], ending[] }
// sorted by time. Concise enough to read as a punch-list:
//   "03/06 04:00 — Withdrawal 26 → 44 GWh/d  (ATW_1239 ends · ATW_1257 begins)"
function computeUpcomingTransitions(rows, site, days = 7, nowMs = Date.now()) {
  const horizonEnd = nowMs + days * 86400 * 1000;
  const opRows = operationalRows(rows);
  const transitions = [];

  for (const category of CATEGORIES) {
    const catRows = rowsForSiteCategory(opRows, site, category)
      .map((r) => ({
        raw: r,
        start: parseTs(r.event_start),
        stop: parseTs(r.event_stop),
        avail: r.available_capacity != null && r.available_capacity !== ""
          ? Number(r.available_capacity) : null,
        unavail: Number(r.unavailable_capacity) || 0,
      }))
      .filter((r) =>
        r.start != null && r.stop != null &&
        r.stop > nowMs && r.start < horizonEnd
      );

    const tech = TECH_CAPACITY[site][category];
    const unit = TECH_UNITS[category];

    // Breakpoints in this category's transition window.
    const bps = new Set();
    for (const r of catRows) {
      if (r.start > nowMs && r.start <= horizonEnd) bps.add(r.start);
      if (r.stop > nowMs && r.stop <= horizonEnd) bps.add(r.stop);
    }
    const sortedBps = [...bps].sort((a, b) => a - b);

    function availAt(t) {
      const active = catRows.filter((r) => r.start <= t && t < r.stop);
      if (active.length === 0) return tech;
      const reportedAvails = active
        .map((r) => r.avail)
        .filter((v) => v != null && !Number.isNaN(v));
      if (reportedAvails.length > 0) return Math.min(...reportedAvails);
      const unavailSum = active.reduce((acc, r) => acc + (r.unavail || 0), 0);
      return Math.max(0, tech - unavailSum);
    }

    for (const t of sortedBps) {
      const before = availAt(t - 1);
      const after = availAt(t);
      if (Math.abs(before - after) < 0.001) continue; // no net change at this instant
      transitions.push({
        at_ms: t,
        category,
        from: before,
        to: after,
        delta: after - before,
        unit,
        tech_max: tech,
        starting: catRows.filter((r) => r.start === t).map((r) => r.raw),
        ending: catRows.filter((r) => r.stop === t).map((r) => r.raw),
      });
    }
  }

  transitions.sort((a, b) => a.at_ms - b.at_ms);
  return transitions;
}

// Effective availability during a window — min(availableCapacity) across all
// non-Dismissed REMITs in (site, category) that overlap the window. Returns
// { value, other_count } where other_count is how many OTHER REMITs are
// contributing alongside the one whose window this is.
function computeEffectiveAvailableDuring(opRows, site, category, windowStartMs, windowStopMs) {
  if (windowStartMs == null || windowStopMs == null) return null;
  const own = rowsForSiteCategory(opRows, site, category);
  let minAvail = null;
  let otherCount = -1; // subtract 1 to exclude the REMIT itself from "others"
  let anyUnknownAvail = false;
  let sumUnavail = 0;
  for (const r of own) {
    const s = parseTs(r.event_start);
    const e = parseTs(r.event_stop);
    if (s == null || e == null) continue;
    if (e <= windowStartMs || s >= windowStopMs) continue;
    otherCount += 1;
    const a = r.available_capacity != null && r.available_capacity !== ""
      ? Number(r.available_capacity) : null;
    if (a != null && !Number.isNaN(a)) {
      if (minAvail == null || a < minAvail) minAvail = a;
    } else {
      anyUnknownAvail = true;
    }
    sumUnavail += Number(r.unavailable_capacity) || 0;
  }
  if (minAvail != null) {
    return { value: minAvail, other_count: Math.max(0, otherCount) };
  }
  if (anyUnknownAvail || sumUnavail > 0) {
    const tech = TECH_CAPACITY[site]?.[category];
    if (tech != null) {
      return { value: Math.max(0, tech - sumUnavail), other_count: Math.max(0, otherCount) };
    }
  }
  return null;
}

// --- conflicts --------------------------------------------------------------

function bucketConflictsBySite(conflicts, nowMs = Date.now(), horizonDays = TIMELINE_DAYS_DEFAULT) {
  // Group conflicts by site, then by time bucket: live | upcoming | beyond.
  const horizonStop = nowMs + horizonDays * 86400 * 1000;
  const out = {};
  for (const site of SITES) {
    out[site] = { live: [], upcoming: [], beyond: [] };
  }
  for (const c of conflicts) {
    const bucket = c.overlap_start <= nowMs && nowMs <= c.overlap_stop
      ? "live"
      : c.overlap_start <= horizonStop
        ? "upcoming"
        : "beyond";
    if (out[c.site]) out[c.site][bucket].push(c);
  }
  return out;
}

function computeConflicts(rows, nowMs = Date.now()) {
  // Surface overlapping REMITs as CLUSTERS (connected components in the
  // pairwise-overlap graph), not as raw pairs. Three REMITs that all
  // overlap each other produce ONE cluster card with three members,
  // rather than three near-duplicate pair cards.
  //
  // Filters per cluster member:
  //   - status == "Active"  (not Inactive/Dismissed)
  //   - same site + same category (different categories don't conflict)
  //
  // Cluster kept iff:
  //   - has 2+ members
  //   - at least some part of the cluster is in the future or live now
  //     (drop purely-historical clusters)
  //
  // Per cluster we compute:
  //   - overlap_start: the latest member start (when all simultaneous)
  //   - overlap_stop:  the earliest member stop  (when first ends)
  //     if these don't form a positive window (chain-shaped overlap),
  //     fall back to the full cluster span (earliest start, latest stop)
  //   - effective_available: min(availableCapacity) across all members
  const out = [];
  for (const site of SITES) {
    for (const category of CATEGORIES) {
      const own = rowsForSiteCategory(rows, site, category).filter(
        (r) => (r.event_status || "").toLowerCase() === "active"
      );
      const n = own.length;
      // Build adjacency list of overlapping pairs.
      const adj = new Array(n).fill(null).map(() => []);
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          if (_pairOverlaps(own[i], own[j])) {
            adj[i].push(j);
            adj[j].push(i);
          }
        }
      }
      // Connected components via BFS.
      const seen = new Array(n).fill(false);
      for (let s = 0; s < n; s++) {
        if (seen[s] || adj[s].length === 0) continue;
        const memberIdxs = [];
        const queue = [s];
        while (queue.length) {
          const v = queue.shift();
          if (seen[v]) continue;
          seen[v] = true;
          memberIdxs.push(v);
          for (const w of adj[v]) if (!seen[w]) queue.push(w);
        }
        if (memberIdxs.length < 2) continue;
        const members = memberIdxs.map((i) => own[i]);
        const starts = members.map((r) => parseTs(r.event_start));
        const stops  = members.map((r) => parseTs(r.event_stop));

        const allSimultStart = Math.max(...starts);
        const allSimultStop  = Math.min(...stops);
        const spanStart      = Math.min(...starts);
        const spanStop       = Math.max(...stops);
        const fullyOverlapping = allSimultStart < allSimultStop;

        const overlapStart = fullyOverlapping ? allSimultStart : spanStart;
        const overlapStop  = fullyOverlapping ? allSimultStop  : spanStop;
        if (overlapStop < nowMs) continue; // entirely in the past

        const reported = members
          .map((r) => (r.available_capacity != null ? Number(r.available_capacity) : null))
          .filter((v) => v != null && !Number.isNaN(v));
        const effectiveAvailable = reported.length > 0 ? Math.min(...reported) : null;

        // Members sorted by start time for stable display.
        members.sort(
          (x, y) => (parseTs(x.event_start) || 0) - (parseTs(y.event_start) || 0)
        );

        out.push({
          site,
          category,
          members,
          member_count: members.length,
          overlap_start: overlapStart,
          overlap_stop: overlapStop,
          fully_overlapping: fullyOverlapping,
          effective_available: effectiveAvailable,
          unit: TECH_UNITS[category],
        });
      }
    }
  }
  out.sort((x, y) => {
    const xLive = x.overlap_start <= nowMs && nowMs <= x.overlap_stop ? 0 : 1;
    const yLive = y.overlap_start <= nowMs && nowMs <= y.overlap_stop ? 0 : 1;
    if (xLive !== yLive) return xLive - yLive;
    return x.overlap_start - y.overlap_start;
  });
  return out;
}

function _pairOverlaps(a, b) {
  if (a.thread_id && a.thread_id === b.thread_id) return false;
  const aStart = parseTs(a.event_start), aStop = parseTs(a.event_stop);
  const bStart = parseTs(b.event_start), bStop = parseTs(b.event_stop);
  if ([aStart, aStop, bStart, bStop].some((v) => v == null)) return false;
  return Math.max(aStart, bStart) < Math.min(aStop, bStop);
}

// --- gradient colour for the dial fill -------------------------------------
// 0% available -> red, 50% -> amber, 100% -> green. Linear interpolation
// between three stops; returns "#rrggbb".

function _lerp(a, b, t) { return Math.round(a + (b - a) * t); }
function _toHex(n) { return n.toString(16).padStart(2, "0"); }

function gradientColor(pct) {
  pct = Math.max(0, Math.min(1, pct));
  const red    = [220, 38, 38];   // #dc2626
  const amber  = [234, 179, 8];   // #eab308
  const green  = [22, 163, 74];   // #16a34a
  let r, g, b;
  if (pct < 0.5) {
    const t = pct / 0.5;
    r = _lerp(red[0], amber[0], t);
    g = _lerp(red[1], amber[1], t);
    b = _lerp(red[2], amber[2], t);
  } else {
    const t = (pct - 0.5) / 0.5;
    r = _lerp(amber[0], green[0], t);
    g = _lerp(amber[1], green[1], t);
    b = _lerp(amber[2], green[2], t);
  }
  return `#${_toHex(r)}${_toHex(g)}${_toHex(b)}`;
}

window.REMITAggregates = {
  SITES,
  CATEGORIES,
  TECH_CAPACITY,
  TECH_UNITS,
  isLive,
  categorise,
  computeRecentChanges,
  computeKpis,
  computeSiteCategoryStatus,
  computeSiteHeadline,
  computeAvailabilityTimeline,
  computeSparklineData,
  computeUpcomingNext,
  computeUpcomingTransitions,
  computeConflicts,
  bucketConflictsBySite,
  gradientColor,
};
