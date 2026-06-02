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
  // For one (site, category) pair, return:
  //   tech_max, unit, live_remits[], unavailable_now, available_now, pct_available
  //
  // Overlap rule (user spec): when multiple REMITs in the same category are
  // simultaneously live, the LOWEST availableCapacity across them is treated
  // as the effective availability. With no live REMITs, available = tech_max.
  const own = rowsForSiteCategory(rows, site, category);
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
      unavailable: s.unavailable_now,
      live_count: s.live_remits.length,
    };
  });
  const anyLive = lines.some((l) => l.live_count > 0);
  return {
    site,
    state: anyLive
      ? (rowsForSite(rows, site)
          .filter((r) => isLive(r, nowMs))
          .some((r) => (r.type_of_unavailability || "").toLowerCase() === "unplanned")
        ? "unplanned" : "planned")
      : "idle",
    lines,
    any_live: anyLive,
  };
}

// --- capacity timeline (per direction, conservative rule) ------------------

function computeAvailabilityTimeline(rows, site, days = TIMELINE_DAYS_DEFAULT, nowMs = Date.now()) {
  // For each day in the horizon, compute the AVAILABLE capacity for the two
  // flow directions (Withdrawal, Injection). When multiple REMITs overlap on
  // the same day, the conservative rule applies: take the MAXIMUM
  // unavailable_capacity reported across them — never the sum, never the
  // average. That way unavailable is bounded by the largest single REMIT
  // and available stays >= 0.
  //
  // Storage events are deliberately excluded — the chart is about flow,
  // and storage is a different unit (TWh vs GWh/d).
  const oneDay = 86400 * 1000;
  const startOfToday = new Date(nowMs);
  startOfToday.setHours(0, 0, 0, 0);
  const labels = [];
  const withdrawal_available = [];
  const injection_available = [];
  const techWithdrawal = TECH_CAPACITY[site].Withdrawal;
  const techInjection = TECH_CAPACITY[site].Injection;

  const withdrawalRows = rowsForSiteCategory(rows, site, "Withdrawal");
  const injectionRows = rowsForSiteCategory(rows, site, "Injection");

  function effectiveAvailable(catRows, tech, dayStart, dayEnd) {
    let maxUnavail = 0;
    let hadAny = false;
    for (const r of catRows) {
      const s = parseTs(r.event_start);
      const e = parseTs(r.event_stop);
      if (s == null || e == null) continue;
      if (e < dayStart || s > dayEnd) continue;
      hadAny = true;
      const u = Number(r.unavailable_capacity) || 0;
      if (u > maxUnavail) maxUnavail = u;
    }
    if (!hadAny) return tech;
    return Math.max(0, tech - maxUnavail);
  }

  for (let i = 0; i < days; i++) {
    const dayStart = startOfToday.getTime() + i * oneDay;
    const dayEnd = dayStart + oneDay - 1;
    labels.push(new Date(dayStart).toISOString().slice(0, 10));
    withdrawal_available.push(effectiveAvailable(withdrawalRows, techWithdrawal, dayStart, dayEnd));
    injection_available.push(effectiveAvailable(injectionRows, techInjection, dayStart, dayEnd));
  }
  return {
    labels,
    withdrawal_available,
    injection_available,
    withdrawal_tech: techWithdrawal,
    injection_tech: techInjection,
  };
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
  // Surface overlapping REMIT pairs that meet ALL of:
  //   - both rows have event_status == "Active" (not Inactive/Dismissed)
  //   - both rows are in the same site AND same category (Withdrawal/Injection/
  //     Storage) — different categories don't physically conflict
  //   - their event windows overlap
  //   - the overlap window has NOT ended yet (skip purely historical clashes)
  //
  // For each surfaced pair, also compute the effective available capacity
  // during the overlap, using the user's rule: take the minimum
  // availableCapacity reported across the conflicting REMITs.
  const out = [];
  for (const site of SITES) {
    for (const category of CATEGORIES) {
      const own = rowsForSiteCategory(rows, site, category).filter(
        (r) => (r.event_status || "").toLowerCase() === "active"
      );
      for (let i = 0; i < own.length; i++) {
        for (let j = i + 1; j < own.length; j++) {
          const a = own[i], b = own[j];
          if (a.thread_id && a.thread_id === b.thread_id) continue;
          const aStart = parseTs(a.event_start), aStop = parseTs(a.event_stop);
          const bStart = parseTs(b.event_start), bStop = parseTs(b.event_stop);
          if ([aStart, aStop, bStart, bStop].some((v) => v == null)) continue;
          const overlapStart = Math.max(aStart, bStart);
          const overlapStop = Math.min(aStop, bStop);
          if (overlapStart >= overlapStop) continue; // no real overlap
          if (overlapStop < nowMs) continue;          // purely in the past
          // Effective available during overlap = min reported availableCapacity.
          const avA = a.available_capacity != null ? Number(a.available_capacity) : null;
          const avB = b.available_capacity != null ? Number(b.available_capacity) : null;
          const reported = [avA, avB].filter((v) => v != null && !Number.isNaN(v));
          const effectiveAvailable = reported.length > 0 ? Math.min(...reported) : null;
          out.push({
            site,
            category,
            a, b,
            overlap_start: overlapStart,
            overlap_stop: overlapStop,
            effective_available: effectiveAvailable,
            unit: TECH_UNITS[category],
          });
        }
      }
    }
  }
  // Sort: currently-overlapping first, then by overlap start.
  out.sort((x, y) => {
    const xLive = x.overlap_start <= nowMs && nowMs <= x.overlap_stop ? 0 : 1;
    const yLive = y.overlap_start <= nowMs && nowMs <= y.overlap_stop ? 0 : 1;
    if (xLive !== yLive) return xLive - yLive;
    return x.overlap_start - y.overlap_start;
  });
  return out;
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
  computeConflicts,
  bucketConflictsBySite,
  gradientColor,
};
