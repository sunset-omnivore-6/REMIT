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

function computeAvailabilityTimeline(rows, site, days = TIMELINE_DAYS_DEFAULT, nowMs = Date.now()) {
  // Returns a STEP function — availability is piecewise constant and only
  // changes at REMIT start/stop boundaries. Evaluated per direction
  // (Withdrawal / Injection). Use stepped:'after' to draw.
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
  // for other concurrent REMITs at publication time. So
  //   tech_max - unavailable != availableCapacity in general,
  // and stacking via max(unavail) would miss the cumulative effect.
  //
  // Storage events deliberately excluded — different unit (TWh), not flow.
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
      .filter((r) =>
        r.start != null && r.stop != null &&
        r.stop > nowMs && r.start < endMs
      );

    const bps = new Set([nowMs, endMs]);
    for (const r of catRows) {
      if (r.start > nowMs && r.start < endMs) bps.add(r.start);
      if (r.stop > nowMs && r.stop < endMs) bps.add(r.stop);
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
      data.push({ x: nowMs, y: tech });
    }
    data.push({ x: endMs, y: data[data.length - 1].y });
    return data;
  }

  return {
    withdrawal_data: lineFor("Withdrawal", techWithdrawal),
    injection_data: lineFor("Injection", techInjection),
    withdrawal_tech: techWithdrawal,
    injection_tech: techInjection,
    start_ms: nowMs,
    end_ms: endMs,
  };
}

// --- upcoming events (next N days, text list) -------------------------------

function computeUpcomingNext(rows, site, days = 7, nowMs = Date.now()) {
  const horizonStop = nowMs + days * 86400 * 1000;
  const opRows = operationalRows(rows);
  return rowsForSite(opRows, site)
    .filter((r) => {
      const start = parseTs(r.event_start);
      return start != null && start > nowMs && start <= horizonStop;
    })
    .map((r) => {
      const cat = categorise(r.type_of_event);
      const startMs = parseTs(r.event_start);
      const stopMs = parseTs(r.event_stop);
      const effective = cat
        ? computeEffectiveAvailableDuring(opRows, site, cat, startMs, stopMs)
        : null;
      return {
        thread_id: r.thread_id,
        category: cat || r.type_of_event || "?",
        type_of_unavailability: r.type_of_unavailability,
        event_start: r.event_start,
        event_stop: r.event_stop,
        unavailable_capacity: r.unavailable_capacity,
        available_capacity: r.available_capacity,
        unit_of_measurement: r.unit_of_measurement,
        reason: r.reason,
        remarks: r.remarks,
        duration_hours: (stopMs - startMs) / 3600000,
        // Effective availability during this REMIT's window, computed the
        // SAME WAY the conflicts panel computes its "effective available"
        // — min(availableCapacity) across all REMITs active during the
        // window. This is what the user actually wants to know.
        effective_available_during: effective != null ? effective.value : null,
        effective_other_count: effective != null ? effective.other_count : 0,
        tech_max: cat && TECH_CAPACITY[site] ? TECH_CAPACITY[site][cat] : null,
      };
    })
    .sort((a, b) => Date.parse(a.event_start) - Date.parse(b.event_start));
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
  computeUpcomingNext,
  computeConflicts,
  bucketConflictsBySite,
  gradientColor,
};
