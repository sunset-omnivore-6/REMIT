// REMIT local dashboard — vanilla JS, no build step.

const els = {
  banner: document.getElementById("status-banner"),
  bannerText: document.querySelector("#status-banner .banner-text"),
  diagToggle: document.getElementById("diag-toggle"),
  diagnostics: document.getElementById("diagnostics"),
  diagBody: document.getElementById("diag-body"),
  refreshBtn: document.getElementById("refresh-btn"),
  nowClock: document.getElementById("now-clock"),
  tbody: document.getElementById("remit-tbody"),
  empty: document.getElementById("empty-state"),
  filterSite: document.getElementById("filter-site"),
  filterStatus: document.getElementById("filter-status"),
  filterType: document.getElementById("filter-type"),
  filterUnavail: document.getElementById("filter-unavail"),
  filterSearch: document.getElementById("filter-search"),
  filterAllSites: document.getElementById("filter-all-sites"),
  filterLiveOnly: document.getElementById("filter-live-only"),
  // Dashboard widgets
  changesBanner: document.getElementById("changes-banner"),
  changesText: document.getElementById("changes-text"),
  headlineAldbrough: document.getElementById("headline-aldbrough"),
  headlineAtwick: document.getElementById("headline-atwick"),
  upcomingAldbrough: document.getElementById("upcoming-aldbrough"),
  upcomingAtwick: document.getElementById("upcoming-atwick"),
  conflictsAldbrough: document.getElementById("conflicts-aldbrough"),
  conflictsAtwick: document.getElementById("conflicts-atwick"),
  themeToggle: document.getElementById("theme-toggle"),
  modalOverlay: document.getElementById("modal-overlay"),
  modalTitle: document.getElementById("modal-title"),
  modalBody: document.getElementById("modal-body"),
  modalClose: document.getElementById("modal-close"),
};

const charts = { aldbrough: null, atwick: null };
const dialCharts = {};  // keyed "site-category" lowercase


// --- REMIT detail modal ---------------------------------------------------
// Click handlers throughout the page (headlines values, upcoming transition
// numbers, thread-id chips in conflicts/upcoming) tag elements with
// data-action attributes. A single delegated listener routes those clicks
// here. The modal pops with one or more REMIT detail cards.

function showRemitModal(remits, title) {
  const list = Array.isArray(remits) ? remits.filter(Boolean) : [];
  els.modalTitle.textContent = title || (list.length === 1 ? "REMIT details" : `${list.length} REMITs`);
  els.modalBody.innerHTML = list.length === 0
    ? `<div class="remit-detail-empty">No matching REMIT found.</div>`
    : list.map(renderRemitDetailHtml).join("");
  els.modalOverlay.setAttribute("data-open", "true");
  els.modalClose.focus();
}

function closeRemitModal() {
  els.modalOverlay.setAttribute("data-open", "false");
}

function renderRemitDetailHtml(r) {
  if (!r) return "";
  const startMs = Date.parse(r.event_start || "");
  const stopMs = Date.parse(r.event_stop || "");
  const dur = (Number.isFinite(startMs) && Number.isFinite(stopMs))
    ? formatDuration((stopMs - startMs) / 3600000) : "";
  const cat = r.type_of_event || "—";
  const status = r.event_status || "";
  const ut = r.type_of_unavailability || "";
  const techMax = r.technical_capacity != null ? formatNum(r.technical_capacity) + " " + (r.unit_of_measurement || "") : "—";
  const avail = r.available_capacity != null
    ? `<span class="meta-strong">${formatNum(r.available_capacity)}</span> ${escapeHtml(r.unit_of_measurement || "")}`
    : "—";
  const unavail = r.unavailable_capacity != null
    ? `<span class="meta-strong">${formatNum(r.unavailable_capacity)}</span> ${escapeHtml(r.unit_of_measurement || "")} <span class="muted">(this REMIT's marginal contribution)</span>`
    : "—";
  const pillsHtml = [
    status ? statusPill(status) : "",
    ut ? unavailPill(ut) : "",
  ].join(" ");
  return `
    <div class="remit-detail">
      <div class="remit-detail-head">
        <code class="remit-detail-id">${escapeHtml(r.thread_id || "")}</code>
        ${pillsHtml}
        <span class="muted">rev ${escapeHtml(String(r.revision_number ?? "?"))}</span>
      </div>
      <dl class="remit-detail-grid">
        <dt>Site</dt><dd>${escapeHtml(r.asset || "—")}</dd>
        <dt>Event type</dt><dd>${escapeHtml(cat)}</dd>
        <dt>Window</dt><dd>${formatTs(r.event_start)} → ${formatTs(r.event_stop)} ${dur ? `<span class="muted">(${dur})</span>` : ""}</dd>
        <dt>Available</dt><dd>${avail}</dd>
        <dt>Unavailable</dt><dd>${unavail}</dd>
        <dt>Technical max</dt><dd>${techMax}</dd>
        <dt>Published</dt><dd>${formatTs(r.publication_dt)}</dd>
      </dl>
      ${(r.reason || r.remarks) ? `
        <dl class="remit-detail-text">
          ${r.reason  ? `<dt>Reason</dt><dd>${escapeHtml(r.reason)}</dd>` : ""}
          ${r.remarks ? `<dt>Remarks</dt><dd>${escapeHtml(r.remarks)}</dd>` : ""}
        </dl>` : ""}
    </div>`;
}

function findRemitByThreadId(threadId) {
  if (!threadId) return null;
  return state.rows.find((r) => r.thread_id === threadId) || null;
}

function findLiveRemitsForCategory(site, category) {
  const nowMs = Date.now();
  const siteLower = site.toLowerCase();
  return state.rows.filter((r) => {
    if ((r.event_status || "").toLowerCase() === "dismissed") return false;
    if ((r.asset || "").toLowerCase() !== siteLower) return false;
    const cat = (r.type_of_event || "").split(/\s+/)[0];
    if (cat !== category) return false;
    const start = Date.parse(r.event_start);
    const stop = Date.parse(r.event_stop);
    return Number.isFinite(start) && Number.isFinite(stop) && start <= nowMs && nowMs <= stop;
  });
}

// Delegated click handler — routes any [data-action] click to the modal.
document.addEventListener("click", (e) => {
  const tgt = e.target.closest("[data-action]");
  if (!tgt) return;
  const action = tgt.dataset.action;
  if (action === "show-remit") {
    const r = findRemitByThreadId(tgt.dataset.threadId);
    showRemitModal(r ? [r] : [], r ? shortenThreadId(r.thread_id) : "REMIT not found");
  } else if (action === "show-live-category") {
    const site = tgt.dataset.site || "";
    const category = tgt.dataset.category || "";
    const remits = findLiveRemitsForCategory(site, category);
    showRemitModal(remits, `${site} · ${category} live now (${remits.length})`);
  } else if (action === "show-transition") {
    const tids = (tgt.dataset.threadIds || "").split(",").filter(Boolean);
    const remits = tids.map(findRemitByThreadId).filter(Boolean);
    showRemitModal(remits, tgt.dataset.title || "Transition");
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeRemitModal();
});
// Close on backdrop click (not on clicks inside .modal)
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") closeRemitModal();
});
document.getElementById("modal-close").addEventListener("click", closeRemitModal);


// --- theme ----------------------------------------------------------------
// The data-theme attribute is set BEFORE first paint by the inline script in
// the page <head>, so there's no flash. This handler just persists the user
// choice and re-renders the charts so they pick up the new colour tokens.

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function withAlpha(hex, alpha) {
  if (!hex) return `rgba(0,0,0,${alpha})`;
  let h = hex.trim();
  if (h.startsWith("#")) h = h.slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  if ([r, g, b].some((n) => Number.isNaN(n))) return `rgba(0,0,0,${alpha})`;
  return `rgba(${r},${g},${b},${alpha})`;
}

function getChartTheme() {
  return {
    surface1:   cssVar("--surface-1",   "#ffffff"),
    surface2:   cssVar("--surface-2",   "#f8fafc"),
    surface3:   cssVar("--surface-3",   "#f1f5f9"),
    fgDefault:  cssVar("--fg-default",  "#0f172a"),
    fgStrong:   cssVar("--fg-strong",   "#1e293b"),
    fgMuted:    cssVar("--fg-muted",    "#475569"),
    fgSubtle:   cssVar("--fg-subtle",   "#64748b"),
    fgFaint:    cssVar("--fg-faint",    "#94a3b8"),
    fgOnAccent: cssVar("--fg-on-accent","#ffffff"),
    border:     cssVar("--border-default", "#e2e8f0"),
    borderSubtle: cssVar("--border-subtle", "#f1f5f9"),
    withdrawal: cssVar("--data-withdrawal", "#dc2626"),
    injection:  cssVar("--data-injection",  "#2563eb"),
    tooltipBg:  cssVar("--surface-inverse", "#0f172a"),
    tooltipFg:  cssVar("--surface-inverse-fg", "#e2e8f0"),
  };
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("remit-theme", next); } catch (e) {}
  // Charts cache the colour values at construction time, so a theme flip
  // requires a re-render to pick up the new tokens.
  if (state.rows.length > 0) renderDashboard();
}

let state = {
  rows: [],
  status: "no-data",
  lastAttempt: null,
  snapshotFetchedAt: null,
  snapshotAgeSeconds: null,
};

async function loadData() {
  const allSites = els.filterAllSites.checked;
  const url = `/api/data?filter_sites=${allSites ? "false" : "true"}`;
  const resp = await fetch(url);
  const data = await resp.json();
  state.rows = data.rows || [];
  state.status = data.status;
  state.lastAttempt = data.last_attempt;
  state.snapshotFetchedAt = data.snapshot_fetched_at;
  state.snapshotAgeSeconds = data.snapshot_age_seconds;
  renderBanner();
  populateFilterOptions();
  renderDashboard();
  renderTable();
}

function renderDashboard() {
  // The dashboard widgets always reflect the unfiltered Aldbrough+Atwick view,
  // even if the table is filtered to "all sites" — these tiles are about the
  // two storage sites specifically.
  const agg = window.REMITAggregates;
  // When user has "show all sites" ticked, state.rows includes non-SSE rows.
  // Filter down to just our two sites for dashboard aggregations.
  const siteRows = state.rows.filter((r) => {
    const a = (r.asset || "").toLowerCase();
    const t = (r.thread_id || "").toLowerCase();
    return a === "aldbrough" || a === "atwick" || t.startsWith("ald_") || t.startsWith("atw_");
  });

  // Recent changes banner
  const changes = agg.computeRecentChanges(siteRows, 24);
  if (changes.total > 0) {
    els.changesBanner.hidden = false;
    const parts = [];
    if (changes.new > 0) parts.push(`${changes.new} new`);
    if (changes.revised > 0) parts.push(`${changes.revised} revised`);
    els.changesText.textContent = `${parts.join(" · ")} REMIT${changes.total === 1 ? "" : "s"} in the last ${changes.hours}h`;
  } else {
    els.changesBanner.hidden = true;
  }

  // Per-site headlines (3 category lines each, never summed)
  renderHeadline(els.headlineAldbrough, agg.computeSiteHeadline(siteRows, "Aldbrough"));
  renderHeadline(els.headlineAtwick, agg.computeSiteHeadline(siteRows, "Atwick"));

  // Capacity dials: 3 per site
  for (const site of agg.SITES) {
    for (const cat of agg.CATEGORIES) {
      const status = agg.computeSiteCategoryStatus(siteRows, site, cat);
      renderDial(`dial-${site.toLowerCase()}-${cat.toLowerCase()}`, status);
    }
  }

  // 30-day availability timeline (per-direction step lines)
  const aldTimeline = agg.computeAvailabilityTimeline(siteRows, "Aldbrough");
  const atwTimeline = agg.computeAvailabilityTimeline(siteRows, "Atwick");
  renderAvailabilityChart("aldbrough", aldTimeline);
  renderAvailabilityChart("atwick", atwTimeline);
  // Make the actual plotted data inspectable from devtools — useful when
  // anyone wonders whether a visual oddity is a math problem or a render
  // problem. Press F12 → Console and read `REMITTimeline`.
  window.REMITTimeline = { Aldbrough: aldTimeline, Atwick: atwTimeline };

  // Upcoming transitions: every capacity change in the next 7 days, including
  // currently-live REMITs that are clearing. Format: from -> to per category.
  renderUpcomingForSite(els.upcomingAldbrough, "Aldbrough", agg.computeUpcomingTransitions(siteRows, "Aldbrough", 7));
  renderUpcomingForSite(els.upcomingAtwick, "Atwick", agg.computeUpcomingTransitions(siteRows, "Atwick", 7));

  // Conflicts split per site
  const conflicts = agg.computeConflicts(siteRows);
  const buckets = agg.bucketConflictsBySite(conflicts);
  renderConflictsForSite(els.conflictsAldbrough, "Aldbrough", buckets["Aldbrough"]);
  renderConflictsForSite(els.conflictsAtwick, "Atwick", buckets["Atwick"]);
}

function renderHeadline(el, h) {
  el.className = `headline headline--${h.state}`;
  const linesHtml = h.lines.map((l) => {
    const isReduced = l.available != null && l.tech_max != null
      ? l.available < l.tech_max
      : false;
    // Clickable only when there's actually something live to show.
    const clickable = l.live_count > 0;
    const valInner = isReduced
      ? `${formatNum(l.available)} ${l.unit}`
      : `<span class="headline-ok">all available</span>`;
    const valAttrs = clickable
      ? ` data-action="show-live-category" data-site="${escapeHtml(h.site)}" data-category="${escapeHtml(l.category)}" tabindex="0" role="button"`
      : "";
    return `
      <div class="headline-line${isReduced ? " headline-line--offline" : ""}">
        <span class="headline-cat">${escapeHtml(l.category)}</span>
        <span class="headline-val"${valAttrs}>${valInner}</span>
        ${l.live_count > 0 ? `<span class="headline-count">${l.live_count} live</span>` : ""}
      </div>
    `;
  }).join("");
  el.innerHTML = `
    <div class="headline-site">${escapeHtml(h.site)}</div>
    ${linesHtml}
  `;
}

function renderDial(elId, status) {
  const agg = window.REMITAggregates;
  const el = document.getElementById(elId);
  if (!el) return;
  const pct = status.pct_available;
  const color = agg.gradientColor(pct);
  const canvasId = `${elId}-canvas`;

  // First render: build the inner DOM with persistent spans for each
  // animated numeric so we can update textContent on the SAME element
  // each tick without rebuilding innerHTML (which would interrupt the
  // count-up animation).
  if (!el.dataset.built) {
    el.innerHTML = `
      <div class="dial-canvas-wrap"><canvas id="${canvasId}"></canvas>
        <div class="dial-center">
          <div class="dial-pct" id="${elId}-pct">0%</div>
          <div class="dial-cat" id="${elId}-cat"></div>
        </div>
      </div>
      <div class="dial-footer">
        <div class="dial-avail">
          <strong id="${elId}-avail-num">0</strong>
          <span id="${elId}-avail-unit"></span> available
        </div>
        <div class="dial-tech" id="${elId}-tech"></div>
      </div>
    `;
    el.dataset.built = "1";
  }

  document.getElementById(`${elId}-cat`).textContent = status.category;
  document.getElementById(`${elId}-avail-unit`).textContent = status.unit;
  document.getElementById(`${elId}-tech`).textContent =
    `of ${formatNum(status.tech_max)} ${status.unit} max`;

  // Count-up animations on the two prominent numbers: the big percentage
  // in the centre of the dial and the available-capacity figure below.
  // First render snaps (no prior value to animate from); subsequent
  // renders tween 300ms easeOutQuart from the last value to the new one.
  animateValueByKey(`${elId}-pct`, pct * 100, (v) => `${Math.round(v)}%`);
  animateValueByKey(`${elId}-avail-num`, status.available_now, (v) => formatNum(v));

  // Empty-segment colour from CSS so dials follow the theme. In light mode
  // this is a pale slate; in dark mode a darker slate that recedes into the
  // card without becoming invisible.
  const emptyColor = cssVar("--surface-3", "#e5e7eb");
  const data = {
    labels: ["Available", "Unavailable"],
    datasets: [{
      data: [status.available_now, Math.max(0, status.tech_max - status.available_now)],
      backgroundColor: [color, emptyColor],
      borderWidth: 0,
    }],
  };
  // On first mount: wheel-fill animation. The arc sweeps clockwise from
  // 0% to the target percentage using easeOutQuart (decelerating curve —
  // confident, premium-feeling). Each dial is staggered by its position
  // in the row so the six dials read as a coordinated cascade rather
  // than six simultaneous flickers.
  // On subsequent renders (theme toggle, periodic data refresh) we use
  // update('none') so dials don't re-animate every time — they just
  // snap to their new value.
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: "72%",
    rotation: -90,
    circumference: 360,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    animation: {
      duration: 900,
      easing: "easeOutQuart",
      delay: (DIAL_STAGGER[elId] || 0) * 70,
      animateRotate: true,
      animateScale: false,
    },
  };
  if (dialCharts[elId]) {
    dialCharts[elId].data = data;
    dialCharts[elId].update("none");
  } else {
    dialCharts[elId] = new Chart(
      document.getElementById(canvasId).getContext("2d"),
      { type: "doughnut", data, options }
    );
  }
}

// Stagger index per dial so the entry animations cascade left→right
// top→bottom. 70ms apart, six dials total — full sequence settles in
// ~1.3s, brisk enough to read as "loaded" rather than "loading".
const DIAL_STAGGER = {
  "dial-aldbrough-withdrawal": 0,
  "dial-aldbrough-injection":  1,
  "dial-aldbrough-storage":    2,
  "dial-atwick-withdrawal":    3,
  "dial-atwick-injection":     4,
  "dial-atwick-storage":       5,
};

// Chart.js plugin: vertical dashed "NOW" line with a filled label badge
// at the top. Brighter than a regular axis tick so it pops on dark mode.
const nowLinePlugin = {
  id: "nowLine",
  afterDatasetsDraw(chart, args, opts) {
    if (!opts || opts.enabled === false) return;
    const xScale = chart.scales.x;
    if (!xScale) return;
    const x = xScale.getPixelForValue(opts.now || Date.now());
    const { top, bottom, left, right } = chart.chartArea;
    if (x < left || x > right) return;
    const ctx = chart.ctx;
    const lineColor  = opts.color   || "rgba(71,85,105,0.85)";
    const badgeBg    = opts.badgeBg || lineColor;
    const badgeFg    = opts.badgeFg || "#ffffff";
    ctx.save();
    // Line
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.25;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(x, top + 14);   // start below the badge
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    // Badge
    ctx.font = "700 9.5px InterVariable, Inter, sans-serif";
    const label = "NOW";
    const tw = ctx.measureText(label).width;
    const padX = 5, padY = 2;
    const bw = tw + padX * 2;
    const bh = 14;
    const bx = x - bw / 2;
    ctx.fillStyle = badgeBg;
    // rounded rectangle
    const r = 3;
    ctx.beginPath();
    ctx.moveTo(bx + r, top);
    ctx.lineTo(bx + bw - r, top);
    ctx.quadraticCurveTo(bx + bw, top, bx + bw, top + r);
    ctx.lineTo(bx + bw, top + bh - r);
    ctx.quadraticCurveTo(bx + bw, top + bh, bx + bw - r, top + bh);
    ctx.lineTo(bx + r, top + bh);
    ctx.quadraticCurveTo(bx, top + bh, bx, top + bh - r);
    ctx.lineTo(bx, top + r);
    ctx.quadraticCurveTo(bx, top, bx + r, top);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = badgeFg;
    ctx.textBaseline = "middle";
    ctx.fillText(label, bx + padX, top + bh / 2 + 0.5);
    ctx.restore();
  },
};
if (window.Chart && !Chart.registry.plugins.get("nowLine")) {
  Chart.register(nowLinePlugin);
}

// Custom Chart.js interaction mode: returns the data point with the
// largest x <= cursor_x for each dataset (i.e. the step-function value
// HELD at the cursor's x position). With the default 'nearest' mode the
// tooltip snaps to whichever data point is pixel-closest, which on a
// step function means it locks onto the next change point rather than
// showing the value being held — confusing the user.
if (window.Chart && Chart.Interaction && !Chart.Interaction.modes.cursorStep) {
  Chart.Interaction.modes.cursorStep = function (chart, e, _options, useFinalPosition) {
    const items = [];
    const xScale = chart.scales.x;
    if (!xScale) return items;
    const pos = useFinalPosition ? { x: e.x, y: e.y } : e;
    const cursorX = xScale.getValueForPixel(pos.x);
    for (let dsi = 0; dsi < chart.data.datasets.length; dsi++) {
      const ds = chart.data.datasets[dsi];
      if (!ds || !ds.data || ds.data.length === 0) continue;
      // Skip the dashed tech-max reference rows
      if ((ds.label || "").endsWith("_tech_max")) continue;
      // Binary search for last point with x <= cursorX (data is x-sorted)
      let lo = 0, hi = ds.data.length - 1, lastIdx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (ds.data[mid].x <= cursorX) { lastIdx = mid; lo = mid + 1; }
        else hi = mid - 1;
      }
      if (lastIdx < 0) continue;
      const meta = chart.getDatasetMeta(dsi);
      const elem = meta.data[lastIdx];
      if (elem) items.push({ element: elem, datasetIndex: dsi, index: lastIdx });
    }
    return items;
  };
}

function renderAvailabilityChart(siteKey, timeline) {
  const canvas = document.getElementById(`chart-${siteKey}`);
  if (!canvas || !window.Chart) return;
  const ctx = canvas.getContext("2d");

  // Materialise the step function as explicit points so Chart.js can't
  // misrender it. For each breakpoint (x_i, y_i) — "y_i holds from x_i
  // until the next breakpoint" — emit:
  //   (x_i, y_i)             — start of segment
  //   hourly points (x, y_i) — held value, one per hour within the
  //                            segment, gives hover a precise place to
  //                            land at every cursor x; default 'nearest'
  //                            mode picks one of these and tooltip shows
  //                            the correct held value
  //   (x_{i+1}-1ms, y_i)     — end of segment, 1ms before the jump
  // Straight-line interpolation then yields a clean step function.
  const HOUR_MS = 60 * 60 * 1000;
  function materialiseStepSeries(stepPoints) {
    if (!stepPoints || stepPoints.length === 0) return [];
    const out = [];
    for (let i = 0; i < stepPoints.length; i++) {
      const p = stepPoints[i];
      out.push({ x: p.x, y: p.y });
      if (i < stepPoints.length - 1) {
        const next = stepPoints[i + 1];
        // Fill intermediate hourly points carrying the segment's held
        // value, so wherever the cursor lands within the segment the
        // nearest data point still has y=p.y (not the next change).
        let t = p.x + HOUR_MS;
        while (t < next.x - HOUR_MS) {
          out.push({ x: t, y: p.y });
          t += HOUR_MS;
        }
        if (next.x > p.x + 1) {
          out.push({ x: next.x - 1, y: p.y });
        }
      }
    }
    return out;
  }

  const withdrawalSeries = materialiseStepSeries(timeline.withdrawal_data);
  const injectionSeries = materialiseStepSeries(timeline.injection_data);

  window.REMITChartSeries = window.REMITChartSeries || {};
  window.REMITChartSeries[siteKey] = { W: withdrawalSeries, I: injectionSeries, raw: timeline };

  // Simplified renderer: solid colour step lines, no fill, no gradient.
  // All colours come from CSS custom properties via getChartTheme() so a
  // theme flip re-themes the chart on the next render.
  const theme = getChartTheme();
  const data = {
    datasets: [
      {
        label: "Withdrawal available",
        data: withdrawalSeries,
        borderColor: theme.withdrawal,
        backgroundColor: "transparent",
        fill: false,
        tension: 0,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: theme.withdrawal,
        pointHoverBorderColor: theme.surface1,
        pointHoverBorderWidth: 2,
        borderWidth: 2.5,
        parsing: false,
      },
      {
        label: "Injection available",
        data: injectionSeries,
        borderColor: theme.injection,
        backgroundColor: "transparent",
        fill: false,
        tension: 0,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: theme.injection,
        pointHoverBorderColor: theme.surface1,
        pointHoverBorderWidth: 2,
        borderWidth: 2.5,
        parsing: false,
      },
      {
        label: "withdrawal_tech_max",
        data: [
          { x: timeline.start_ms, y: timeline.withdrawal_tech },
          { x: timeline.end_ms,   y: timeline.withdrawal_tech },
        ],
        borderColor: withAlpha(theme.withdrawal, 0.35),
        backgroundColor: "transparent",
        borderDash: [4, 4],
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
        tension: 0,
        parsing: false,
      },
      {
        label: "injection_tech_max",
        data: [
          { x: timeline.start_ms, y: timeline.injection_tech },
          { x: timeline.end_ms,   y: timeline.injection_tech },
        ],
        borderColor: withAlpha(theme.injection, 0.35),
        backgroundColor: "transparent",
        borderDash: [4, 4],
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
        tension: 0,
        parsing: false,
      },
    ],
  };

  const yMax = Math.max(timeline.withdrawal_tech, timeline.injection_tech) * 1.08;
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    // 'nearest' mode picks the data point with the smallest pixel
    // distance from the cursor. The materialised series above places
    // hourly points within every step segment, all carrying that
    // segment's value, so wherever the cursor lands the nearest point
    // already has the correct held value — no custom mode needed.
    interaction: { mode: "nearest", axis: "x", intersect: false },
    // Subtle entry animation on first mount only. Periodic refreshes use
    // update('none') below so this duration never plays on refresh.
    animation: { duration: 450, easing: "easeOutQuart" },
    plugins: {
      nowLine: {
        color:   withAlpha(theme.fgMuted, 0.9),
        badgeBg: theme.fgMuted,
        badgeFg: theme.surface1,
        now:     timeline.now_ms || Date.now(),
      },
      legend: {
        position: "top",
        align: "end",
        labels: {
          font: { size: 11, weight: "500" },
          color: theme.fgMuted,
          boxWidth: 10,
          boxHeight: 10,
          usePointStyle: true,
          filter: (item) => !item.text.endsWith("_tech_max"),
        },
      },
      tooltip: {
        backgroundColor: withAlpha(theme.tooltipBg, 0.94),
        titleColor: theme.tooltipFg,
        bodyColor: theme.tooltipFg,
        titleFont: { size: 12, weight: "600" },
        bodyFont: { size: 12 },
        padding: 10,
        cornerRadius: 6,
        displayColors: true,
        boxWidth: 8,
        boxHeight: 8,
        usePointStyle: true,
        filter: (ctx) => !ctx.dataset.label.endsWith("_tech_max"),
        callbacks: {
          title: (items) => {
            if (!items.length) return "";
            const t = items[0].parsed.x;
            const dt = new Date(t);
            return dt.toLocaleDateString(undefined, {
              weekday: "short", day: "numeric", month: "short",
              hour: "2-digit", minute: "2-digit",
            });
          },
          label: (c) => ` ${c.dataset.label.split(" available")[0]}: ${formatNum(c.parsed.y)} GWh/d`,
        },
      },
    },
    scales: {
      x: {
        type: "time",
        min: timeline.start_ms,
        max: timeline.end_ms,
        time: {
          unit: "day",
          displayFormats: { day: "d MMM", hour: "d MMM HH:mm" },
          tooltipFormat: "EEE d MMM HH:mm",
        },
        grid: { color: withAlpha(theme.fgFaint, 0.10) },
        border: { color: theme.border },
        ticks: {
          autoSkip: true,
          maxTicksLimit: 8,
          font: { size: 10 },
          color: theme.fgSubtle,
          source: "auto",
        },
      },
      y: {
        beginAtZero: true,
        suggestedMax: yMax,
        grid: { color: withAlpha(theme.fgFaint, 0.12) },
        border: { color: theme.border },
        ticks: {
          font: { size: 10 },
          color: theme.fgSubtle,
          callback: (v) => formatNum(v),
        },
        title: { display: true, text: "GWh/d", color: theme.fgFaint, font: { size: 10, weight: "600" } },
      },
    },
  };

  // First mount animates briefly; subsequent renders (theme toggle,
  // periodic 30s data refresh) update in place via update('none') so the
  // chart doesn't repeatedly re-animate on screen — that catches the eye
  // every refresh cycle and reads as the page being unstable.
  if (charts[siteKey]) {
    charts[siteKey].data = data;
    charts[siteKey].options = options;
    charts[siteKey].update("none");
  } else {
    charts[siteKey] = new Chart(ctx, { type: "line", data, options });
  }

  // Hide the skeleton overlay now that the canvas has real content.
  const skel = document.getElementById(`chart-skel-${siteKey}`);
  if (skel) skel.style.display = "none";
}

function renderUpcomingForSite(rootEl, site, transitions) {
  if (!rootEl) return;
  if (transitions.length === 0) {
    rootEl.innerHTML = `
      <div class="upcoming-card upcoming-card--empty">
        <div class="upcoming-site-row">
          <span class="upcoming-site">${escapeHtml(site)}</span>
        </div>
        <div class="upcoming-empty">No capacity changes in next 7 days</div>
      </div>`;
    return;
  }
  const nowMs = Date.now();
  const items = transitions.map((t) => {
    const dir = t.delta > 0 ? "up" : "down";
    const allTids = [...t.ending.map((r) => r.thread_id), ...t.starting.map((r) => r.thread_id)].filter(Boolean);
    const title = `${site} · ${t.category} ${formatNum(t.from)} → ${formatNum(t.to)} ${t.unit}`;
    const causes = [
      ...t.ending.map((r) => `<code data-action="show-remit" data-thread-id="${escapeHtml(r.thread_id || "")}" tabindex="0" role="button">${escapeHtml(shortenThreadId(r.thread_id))}</code> ends`),
      ...t.starting.map((r) => `<code data-action="show-remit" data-thread-id="${escapeHtml(r.thread_id || "")}" tabindex="0" role="button">${escapeHtml(shortenThreadId(r.thread_id))}</code> begins`),
    ].join(" · ");
    const countdown = formatCountdown(t.at_ms - nowMs);
    const unit = escapeHtml(t.unit || "");
    const transAttrs = allTids.length > 0
      ? ` data-action="show-transition" data-thread-ids="${escapeHtml(allTids.join(","))}" data-title="${escapeHtml(title)}" tabindex="0" role="button"`
      : "";
    return `
      <div class="upcoming-item upcoming-item--${dir}">
        <div class="upcoming-time">
          ${formatTs(new Date(t.at_ms).toISOString())}
          <span class="upcoming-dur">in ${countdown}</span>
        </div>
        <div class="upcoming-body">
          <strong class="upcoming-cat">${escapeHtml(t.category)}</strong>
          <span class="upcoming-from"${transAttrs}>${formatNum(t.from)}</span>
          <span class="upcoming-arrow">→</span>
          <strong class="upcoming-to"${transAttrs}>${formatNum(t.to)} ${unit}</strong>
        </div>
        <div class="upcoming-remarks">${causes}</div>
      </div>`;
  }).join("");
  rootEl.innerHTML = `
    <div class="upcoming-card">
      <div class="upcoming-site-row">
        <span class="upcoming-site">${escapeHtml(site)}</span>
        <span class="upcoming-count">${transitions.length} change${transitions.length === 1 ? "" : "s"}</span>
      </div>
      ${items}
    </div>`;
}

function shortenThreadId(tid) {
  if (!tid) return "";
  // ATW_000000000000000001239 → ATW_1239 — leading zeros are pure noise.
  return String(tid).replace(/_0+(?=\d)/, "_");
}

function formatCountdown(deltaMs) {
  if (deltaMs < 60000) return "<1m";
  const totalMin = Math.floor(deltaMs / 60000);
  if (totalMin < 60) return `${totalMin}m`;
  const totalHr = Math.floor(totalMin / 60);
  const remMin = totalMin % 60;
  if (totalHr < 24) return remMin > 0 ? `${totalHr}h ${remMin}m` : `${totalHr}h`;
  const totalDay = Math.floor(totalHr / 24);
  const remHr = totalHr % 24;
  return remHr > 0 ? `${totalDay}d ${remHr}h` : `${totalDay}d`;
}

function renderConflictsForSite(rootEl, site, buckets) {
  const total = buckets.live.length + buckets.upcoming.length + buckets.beyond.length;
  if (total === 0) {
    rootEl.innerHTML = `
      <div class="conflicts-card conflicts-card--clean">
        <div class="conflicts-card-head">
          <span class="conflicts-site">${escapeHtml(site)}</span>
          <span class="conflicts-allclear">✓ No overlapping REMITs</span>
        </div>
      </div>`;
    return;
  }

  const inlineHtml = [...buckets.live, ...buckets.upcoming]
    .map((c) => conflictItemHtml(c, "live" === c.bucket ? "live" : "upcoming"))
    .join("") || `<div class="conflicts-empty">No conflicts within next 30 days</div>`;

  // Add bucket marker so the template above knows which class to use.
  // Simpler: re-map with explicit bucket arg.
  const inlineHtml2 = [
    ...buckets.live.map((c) => conflictItemHtml(c, "live")),
    ...buckets.upcoming.map((c) => conflictItemHtml(c, "upcoming")),
  ].join("") || `<div class="conflicts-empty">No conflicts within next 30 days</div>`;

  const beyondHtml = buckets.beyond.length === 0
    ? ""
    : `
      <details class="conflicts-beyond">
        <summary>${buckets.beyond.length} further conflict${buckets.beyond.length === 1 ? "" : "s"} beyond 30 days</summary>
        ${buckets.beyond.map((c) => conflictItemHtml(c, "beyond")).join("")}
      </details>`;

  const counts = [];
  if (buckets.live.length)     counts.push(`<span class="conflicts-count conflicts-count--live">${buckets.live.length} live</span>`);
  if (buckets.upcoming.length) counts.push(`<span class="conflicts-count conflicts-count--upcoming">${buckets.upcoming.length} next 30d</span>`);
  if (buckets.beyond.length)   counts.push(`<span class="conflicts-count conflicts-count--beyond">${buckets.beyond.length} beyond</span>`);

  rootEl.innerHTML = `
    <div class="conflicts-card">
      <div class="conflicts-card-head">
        <span class="conflicts-site">${escapeHtml(site)}</span>
        <span class="conflicts-counts">${counts.join("")}</span>
      </div>
      <div class="conflicts-list">${inlineHtml2}</div>
      ${beyondHtml}
    </div>`;
}

function conflictItemHtml(c, bucket) {
  const tag = bucket === "live"
    ? '<span class="conflict-tag conflict-tag--live">LIVE NOW</span>'
    : bucket === "upcoming"
      ? '<span class="conflict-tag conflict-tag--upcoming">UPCOMING</span>'
      : '<span class="conflict-tag conflict-tag--beyond">BEYOND 30d</span>';
  const eff = c.effective_available != null
    ? `<div class="conflict-eff">Effective available during overlap: <strong>${formatNum(c.effective_available)} ${escapeHtml(c.unit)}</strong></div>`
    : "";
  // "All simultaneous" window vs. chain-shaped fallback gets a small
  // muted hint so the user knows what the window represents.
  const windowNote = c.fully_overlapping
    ? ""
    : ` <span class="conflict-windowhint">(staggered)</span>`;
  const membersHtml = (c.members || []).map((m) => `
    <div class="conflict-member">
      <code data-action="show-remit" data-thread-id="${escapeHtml(m.thread_id || "")}" tabindex="0" role="button">${escapeHtml(shortenThreadId(m.thread_id || ""))}</code>
      <span class="conflict-member-window">${formatTs(m.event_start)} → ${formatTs(m.event_stop)}</span>
      <span class="conflict-member-avail">avail ${formatNum(m.available_capacity)}</span>
    </div>`).join("");
  return `
    <div class="conflict-item conflict-item--${bucket}">
      <div class="conflict-row1">
        ${tag}
        <span class="conflict-cat">${escapeHtml(c.category)} · ${c.member_count} active</span>
        <span class="conflict-window">${formatTs(new Date(c.overlap_start).toISOString())} → ${formatTs(new Date(c.overlap_stop).toISOString())}${windowNote}</span>
      </div>
      ${eff}
      <div class="conflict-members">${membersHtml}</div>
    </div>`;
}

function renderBanner() {
  const { status, snapshotFetchedAt, snapshotAgeSeconds, lastAttempt } = state;
  els.banner.className = `banner banner--${status}`;
  let msg;
  switch (status) {
    case "fresh":
      msg = `Data is fresh — last successful pull ${formatAge(snapshotAgeSeconds)} ago (${formatTs(snapshotFetchedAt)}).`;
      break;
    case "stale":
      msg = `Showing stale data — last successful pull ${formatAge(snapshotAgeSeconds)} ago. Live fetch is failing.`;
      break;
    case "failed":
      msg = `Live fetch failing for over an hour. Snapshot from ${formatTs(snapshotFetchedAt)} (${formatAge(snapshotAgeSeconds)} old).`;
      break;
    case "no-data":
      msg = `No data yet — initial fetch hasn't succeeded. ${lastAttempt?.last_attempt_error ? "Error: " + lastAttempt.last_attempt_error : ""}`;
      break;
    default:
      msg = `Status: ${status}`;
  }
  els.bannerText.textContent = msg;

  const hasDiag = lastAttempt && (lastAttempt.last_attempt_attempts || []).length > 0;
  els.diagToggle.hidden = !hasDiag;
}

function populateFilterOptions() {
  // Repopulate dropdowns from the current dataset, preserving selection.
  const unique = (key) => [...new Set(state.rows.map((r) => r[key]).filter(Boolean))].sort();
  fillSelect(els.filterStatus, unique("event_status"));
  fillSelect(els.filterType, unique("type_of_event"));
  fillSelect(els.filterUnavail, unique("type_of_unavailability"));
}

function fillSelect(sel, values) {
  const current = sel.value;
  // Keep the leading "All" option (value="")
  sel.innerHTML = '<option value="">All</option>' +
    values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
  if (values.includes(current)) sel.value = current;
}

function isLive(r, nowMs) {
  if (!r.event_start || !r.event_stop) return false;
  const start = Date.parse(r.event_start);
  const stop = Date.parse(r.event_stop);
  if (Number.isNaN(start) || Number.isNaN(stop)) return false;
  return start <= nowMs && nowMs <= stop;
}

function renderTable() {
  const nowMs = Date.now();
  const filters = {
    site: els.filterSite.value,
    status: els.filterStatus.value,
    type: els.filterType.value,
    unavail: els.filterUnavail.value,
    search: els.filterSearch.value.trim().toLowerCase(),
    liveOnly: els.filterLiveOnly.checked,
  };
  const filtered = state.rows.filter((r) => {
    if (filters.site && !(r.asset || "").toLowerCase().includes(filters.site.toLowerCase())) return false;
    if (filters.status && r.event_status !== filters.status) return false;
    if (filters.type && r.type_of_event !== filters.type) return false;
    if (filters.unavail && r.type_of_unavailability !== filters.unavail) return false;
    if (filters.search && !(r.thread_id || "").toLowerCase().includes(filters.search)) return false;
    if (filters.liveOnly && !isLive(r, nowMs)) return false;
    return true;
  });

  // Sort: live events first, then by publication date desc.
  filtered.sort((a, b) => {
    const al = isLive(a, nowMs) ? 0 : 1;
    const bl = isLive(b, nowMs) ? 0 : 1;
    if (al !== bl) return al - bl;
    return (b.publication_dt || "").localeCompare(a.publication_dt || "");
  });

  els.tbody.innerHTML = filtered.map((r) => rowHtml(r, nowMs)).join("");
  els.empty.hidden = filtered.length > 0;
}

function rowHtml(r, nowMs) {
  const live = isLive(r, nowMs);
  const cls = live ? ' class="row--live"' : "";
  const tid = r.thread_id || "";
  return `<tr${cls}>
    <td><span data-action="show-remit" data-thread-id="${escapeHtml(tid)}" tabindex="0" role="button" class="table-tid">${escapeHtml(tid)}</span>${live ? ' <span class="pill pill--live">LIVE</span>' : ""}</td>
    <td class="num">${escapeHtml(String(r.revision_number ?? ""))}</td>
    <td>${escapeHtml(r.asset || "")}</td>
    <td>${statusPill(r.event_status)}</td>
    <td>${unavailPill(r.type_of_unavailability)}</td>
    <td>${escapeHtml(r.type_of_event || "")}</td>
    <td>${formatTs(r.publication_dt)}</td>
    <td>${formatTs(r.event_start)}</td>
    <td>${formatTs(r.event_stop)}</td>
    <td>${escapeHtml(r.unit_of_measurement || "")}</td>
    <td class="num">${formatNum(r.unavailable_capacity)}</td>
    <td class="num">${formatNum(r.technical_capacity)}</td>
    <td>${escapeHtml(r.reason || "")}</td>
    <td>${escapeHtml(r.remarks || "")}</td>
  </tr>`;
}

function statusPill(s) {
  if (!s) return "";
  const cls = s.toLowerCase() === "active" ? "pill--active" : "pill--inactive";
  return `<span class="pill ${cls}">${escapeHtml(s)}</span>`;
}

function unavailPill(s) {
  if (!s) return "";
  const v = s.toLowerCase();
  const cls = v === "planned" ? "pill--planned" : v === "unplanned" ? "pill--unplanned" : "";
  return cls ? `<span class="pill ${cls}">${escapeHtml(s)}</span>` : escapeHtml(s);
}

function formatTs(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return escapeHtml(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatAge(seconds) {
  if (seconds == null) return "unknown";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d`;
}

// --- number transitions ---------------------------------------------------
// Count-up tween from the previous value of a keyed numeric to the new one.
// First call for a key snaps (no prior value); subsequent calls animate over
// `duration` ms using easeOutQuart. Respects prefers-reduced-motion.
// Keyed by id-string so callers can reference the same element across
// renders even if its DOM node has been replaced by an innerHTML rebuild.

const _animState = {};  // key -> { handle, lastTarget }

function animateValueByKey(key, newVal, formatter, duration = 300) {
  const el = document.getElementById(key);
  if (!el) return;
  if (typeof newVal !== "number" || !Number.isFinite(newVal)) {
    el.textContent = formatter(newVal);
    return;
  }
  const prev = _animState[key];
  const from = prev ? prev.lastTarget : null;
  _animState[key] = { handle: prev?.handle, lastTarget: newVal };

  // No prior, no change, or reduced motion → snap.
  if (
    from === null || from === undefined || !Number.isFinite(from) ||
    from === newVal ||
    (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  ) {
    if (prev?.handle) cancelAnimationFrame(prev.handle);
    el.textContent = formatter(newVal);
    _animState[key].handle = null;
    return;
  }
  if (prev?.handle) cancelAnimationFrame(prev.handle);

  const start = performance.now();
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 4);
    const v = from + (newVal - from) * eased;
    el.textContent = formatter(v);
    if (t < 1) {
      _animState[key].handle = requestAnimationFrame(step);
    } else {
      _animState[key].handle = null;
    }
  }
  _animState[key].handle = requestAnimationFrame(step);
}

function formatNum(v) {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return escapeHtml(String(v));
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function updateClock() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  els.nowClock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// Wiring
els.refreshBtn.addEventListener("click", async () => {
  els.refreshBtn.disabled = true;
  els.refreshBtn.textContent = "Refreshing…";
  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadData();
  } finally {
    els.refreshBtn.disabled = false;
    els.refreshBtn.textContent = "Refresh now";
  }
});

els.diagToggle.addEventListener("click", () => {
  const hidden = els.diagnostics.hidden;
  els.diagnostics.hidden = !hidden;
  els.diagToggle.textContent = hidden ? "Hide diagnostics" : "Show diagnostics";
  if (hidden) {
    els.diagBody.textContent = JSON.stringify(state.lastAttempt, null, 2);
  }
});

[els.filterSite, els.filterStatus, els.filterType, els.filterUnavail].forEach((el) =>
  el.addEventListener("change", renderTable)
);
els.filterSearch.addEventListener("input", renderTable);
els.filterAllSites.addEventListener("change", loadData);
els.filterLiveOnly.addEventListener("change", renderTable);

if (els.themeToggle) {
  els.themeToggle.addEventListener("click", toggleTheme);
}

setInterval(updateClock, 1000);
updateClock();

// Initial load and a polling loop so the page picks up background refreshes.
loadData();
setInterval(loadData, 30000);
