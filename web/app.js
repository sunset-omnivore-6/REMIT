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
};

const charts = { aldbrough: null, atwick: null };
const dialCharts = {};  // keyed "site-category" lowercase


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
    fgMuted:    cssVar("--fg-muted",    "#475569"),
    fgSubtle:   cssVar("--fg-subtle",   "#64748b"),
    fgFaint:    cssVar("--fg-faint",    "#94a3b8"),
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
  history: [],   // dial value samples for the sparklines
};

async function loadData() {
  const allSites = els.filterAllSites.checked;
  const url = `/api/data?filter_sites=${allSites ? "false" : "true"}`;
  // Fetch the dial history in parallel — small payload, drives the
  // sparklines and (later) deltas.
  const [resp, histResp] = await Promise.all([
    fetch(url),
    fetch("/api/history?hours=24").catch(() => null),
  ]);
  const data = await resp.json();
  state.rows = data.rows || [];
  state.status = data.status;
  state.lastAttempt = data.last_attempt;
  state.snapshotFetchedAt = data.snapshot_fetched_at;
  state.snapshotAgeSeconds = data.snapshot_age_seconds;
  if (histResp && histResp.ok) {
    try {
      const hist = await histResp.json();
      state.history = hist.samples || [];
    } catch (e) { state.history = []; }
  }
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
    // Flip: show what's AVAILABLE right now (matches the dial's headline
    // number underneath). Red text when reduced; green "all available"
    // when at nameplate tech max.
    const isReduced = l.available != null && l.tech_max != null
      ? l.available < l.tech_max
      : false;
    const valStr = isReduced
      ? `${formatNum(l.available)} ${l.unit}`
      : `<span class="headline-ok">all available</span>`;
    return `
      <div class="headline-line${isReduced ? " headline-line--offline" : ""}">
        <span class="headline-cat">${escapeHtml(l.category)}</span>
        <span class="headline-val">${valStr}</span>
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

  // First render: build the inner DOM. Subsequent renders just patch values
  // so the chart instance is reused and the canvas doesn't flicker.
  if (!el.dataset.built) {
    el.innerHTML = `
      <div class="dial-canvas-wrap"><canvas id="${canvasId}"></canvas>
        <div class="dial-center">
          <div class="dial-pct" id="${elId}-pct"></div>
          <div class="dial-cat" id="${elId}-cat"></div>
        </div>
      </div>
      <div class="dial-footer">
        <div class="dial-avail" id="${elId}-avail"></div>
        <div class="dial-tech" id="${elId}-tech"></div>
        <svg class="dial-spark" id="${elId}-spark"
             viewBox="0 0 80 20" width="80" height="20"
             preserveAspectRatio="none" aria-hidden="true"></svg>
      </div>
    `;
    el.dataset.built = "1";
  }

  document.getElementById(`${elId}-pct`).textContent = `${Math.round(pct * 100)}%`;
  document.getElementById(`${elId}-cat`).textContent = status.category;
  document.getElementById(`${elId}-avail`).innerHTML =
    `<strong>${formatNum(status.available_now)}</strong> ${status.unit} available`;
  document.getElementById(`${elId}-tech`).textContent =
    `of ${formatNum(status.tech_max)} ${status.unit} max`;

  // Sparkline of the last 24h of this dial's value. Empty silently while
  // the history buffer is still warming up (< 2 samples).
  const sparkEl = document.getElementById(`${elId}-spark`);
  if (sparkEl) renderSparkline(sparkEl, status.site, status.category, status.tech_max, color);

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

// Chart.js plugin that draws a thin dashed "NOW" line at the current time
// across the chart area, with a tiny label above. Lets the eye instantly
// separate past from future when the chart spans both.
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
    const colour = opts.color || "rgba(100,116,139,0.65)";
    ctx.save();
    ctx.strokeStyle = colour;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = colour;
    ctx.font = "600 9px InterVariable, Inter, sans-serif";
    ctx.fillText("NOW", x + 4, top + 11);
    ctx.restore();
  },
};
if (window.Chart && !Chart.registry.plugins.get("nowLine")) {
  Chart.register(nowLinePlugin);
}

function renderAvailabilityChart(siteKey, timeline) {
  const canvas = document.getElementById(`chart-${siteKey}`);
  if (!canvas || !window.Chart) return;
  const ctx = canvas.getContext("2d");

  // Materialise the step function as explicit points so Chart.js can't
  // get it wrong. For each breakpoint (x_i, y_i) — "y_i holds from x_i
  // until the next breakpoint" — emit:
  //   (x_i, y_i)         — start of segment
  //   (x_{i+1}-1ms, y_i) — end of segment, 1ms before the jump
  // Straight-line interpolation then yields a clean step function.
  function materialiseStepSeries(stepPoints) {
    if (!stepPoints || stepPoints.length === 0) return [];
    const out = [];
    for (let i = 0; i < stepPoints.length; i++) {
      const p = stepPoints[i];
      out.push({ x: p.x, y: p.y });
      if (i < stepPoints.length - 1) {
        const next = stepPoints[i + 1];
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
    interaction: { mode: "nearest", axis: "x", intersect: false },
    // Subtle entry animation on first mount only. Periodic refreshes use
    // update('none') below so this duration never plays on refresh.
    animation: { duration: 450, easing: "easeOutQuart" },
    plugins: {
      nowLine: { color: withAlpha(theme.fgSubtle, 0.7), now: timeline.now_ms || Date.now() },
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
    const causes = [
      ...t.ending.map((r) => `<code>${escapeHtml(shortenThreadId(r.thread_id))}</code> ends`),
      ...t.starting.map((r) => `<code>${escapeHtml(shortenThreadId(r.thread_id))}</code> begins`),
    ].join(" · ");
    const countdown = formatCountdown(t.at_ms - nowMs);
    const unit = escapeHtml(t.unit || "");
    return `
      <div class="upcoming-item upcoming-item--${dir}">
        <div class="upcoming-time">
          ${formatTs(new Date(t.at_ms).toISOString())}
          <span class="upcoming-dur">in ${countdown}</span>
        </div>
        <div class="upcoming-body">
          <strong class="upcoming-cat">${escapeHtml(t.category)}</strong>
          <span class="upcoming-from">${formatNum(t.from)}</span>
          <span class="upcoming-arrow">→</span>
          <strong class="upcoming-to">${formatNum(t.to)} ${unit}</strong>
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

// Render an 80x20 SVG sparkline of the last 24h of values for one
// (site, category) dial. Scaled 0..tech_max so absolute level is
// preserved (a flat line at 26 on a tech 130 dial sits low — that's
// meaningful), with a soft fill underneath. Stays empty until the
// rolling history buffer has at least two samples.
function renderSparkline(svgEl, site, category, techMax, lineColor) {
  if (!svgEl) return;
  const key = `${site}.${category}`;
  const samples = (state.history || [])
    .map((s) => ({ t: Date.parse(s.t), v: s.values && s.values[key] }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v));
  if (samples.length < 2) { svgEl.innerHTML = ""; return; }

  const W = 80, H = 20;
  const tMin = samples[0].t;
  const tMax = samples[samples.length - 1].t;
  const tRange = tMax - tMin || 1;
  const yMax = techMax || Math.max(...samples.map((p) => p.v)) || 1;

  const points = samples.map((p) => {
    const x = ((p.t - tMin) / tRange) * W;
    // Pad top by 1.5px so the line never clips the top edge.
    const y = H - 1.5 - (Math.max(0, Math.min(p.v, yMax)) / yMax) * (H - 3);
    return [x, y];
  });
  const linePath = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const fillPath = `${linePath} L ${W} ${H} L 0 ${H} Z`;
  const fill = withAlpha(lineColor, 0.14);

  svgEl.innerHTML =
    `<path d="${fillPath}" fill="${fill}" stroke="none"/>` +
    `<path d="${linePath}" fill="none" stroke="${lineColor}" ` +
    `stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>`;
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
  return `
    <div class="conflict-item conflict-item--${bucket}">
      <div class="conflict-row1">
        ${tag}
        <span class="conflict-cat">${escapeHtml(c.category)}</span>
        <span class="conflict-window">${formatTs(new Date(c.overlap_start).toISOString())} → ${formatTs(new Date(c.overlap_stop).toISOString())}</span>
      </div>
      ${eff}
      <div class="conflict-pair">
        <code>${escapeHtml(c.a.thread_id || "")}</code> (avail ${formatNum(c.a.available_capacity)})
        ↔
        <code>${escapeHtml(c.b.thread_id || "")}</code> (avail ${formatNum(c.b.available_capacity)})
      </div>
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
  return `<tr${cls}>
    <td>${escapeHtml(r.thread_id || "")}${live ? ' <span class="pill pill--live">LIVE</span>' : ""}</td>
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
