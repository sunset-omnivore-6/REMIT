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
  kpiLive: document.getElementById("kpi-live"),
  kpiLiveSplit: document.getElementById("kpi-live-split"),
  kpiUpcoming: document.getElementById("kpi-upcoming"),
  kpiUpcomingSplit: document.getElementById("kpi-upcoming-split"),
  headlineAldbrough: document.getElementById("headline-aldbrough"),
  headlineAtwick: document.getElementById("headline-atwick"),
  conflictsSection: document.getElementById("conflicts-section"),
  conflictsList: document.getElementById("conflicts-list"),
};

const charts = { aldbrough: null, atwick: null };
const dialCharts = {};  // keyed "site-category" lowercase

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

  // Hero KPIs
  const kpis = agg.computeKpis(siteRows);
  els.kpiLive.textContent = kpis.live_count;
  els.kpiLiveSplit.textContent = formatSplit(kpis.live_planned, kpis.live_unplanned, "live");
  els.kpiUpcoming.textContent = kpis.upcoming_7d;
  els.kpiUpcomingSplit.textContent = formatSplit(kpis.upcoming_planned, kpis.upcoming_unplanned, "upcoming");

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

  // 30-day timeline charts
  renderCapacityChart("aldbrough", agg.computeCapacityTimeline(siteRows, "Aldbrough"));
  renderCapacityChart("atwick", agg.computeCapacityTimeline(siteRows, "Atwick"));

  // Conflicts
  renderConflicts(agg.computeConflicts(siteRows));
}

function formatSplit(planned, unplanned, fallbackLabel) {
  const parts = [];
  if (planned) parts.push(`${planned} planned`);
  if (unplanned) parts.push(`${unplanned} unplanned`);
  return parts.join(" · ") || `none ${fallbackLabel}`;
}

function renderHeadline(el, h) {
  el.className = `headline headline--${h.state}`;
  const linesHtml = h.lines.map((l) => {
    const isOffline = l.unavailable > 0;
    const valStr = isOffline ? `${formatNum(l.unavailable)} ${l.unit}` : `<span class="headline-ok">all available</span>`;
    return `
      <div class="headline-line${isOffline ? " headline-line--offline" : ""}">
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
        <div class="dial-live" id="${elId}-live"></div>
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
  const liveEl = document.getElementById(`${elId}-live`);
  if (status.live_remits.length === 0) {
    liveEl.textContent = "";
  } else {
    const ids = status.live_remits.map((r) => r.thread_id).join(", ");
    liveEl.textContent = `${status.live_remits.length} live: ${ids}`;
  }

  const data = {
    labels: ["Available", "Unavailable"],
    datasets: [{
      data: [status.available_now, Math.max(0, status.tech_max - status.available_now)],
      backgroundColor: [color, "#e5e7eb"],
      borderWidth: 0,
    }],
  };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: "72%",
    rotation: -90,
    circumference: 360,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    animation: { duration: 400 },
  };
  if (dialCharts[elId]) {
    dialCharts[elId].data = data;
    dialCharts[elId].options = options;
    dialCharts[elId].update();
  } else {
    dialCharts[elId] = new Chart(document.getElementById(canvasId).getContext("2d"),
      { type: "doughnut", data, options });
  }
}

function renderCapacityChart(siteKey, timeline) {
  const canvas = document.getElementById(`chart-${siteKey}`);
  if (!canvas || !window.Chart) return;
  const ctx = canvas.getContext("2d");

  const data = {
    labels: timeline.labels,
    datasets: [
      {
        label: "Planned",
        data: timeline.planned,
        borderColor: "#2563eb",
        backgroundColor: "rgba(37,99,235,0.15)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      },
      {
        label: "Unplanned",
        data: timeline.unplanned,
        borderColor: "#dc2626",
        backgroundColor: "rgba(220,38,38,0.15)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      },
    ],
  };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", labels: { font: { size: 11 } } },
      tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${formatNum(c.parsed.y)}` } },
    },
    scales: {
      x: {
        ticks: {
          autoSkip: true,
          maxTicksLimit: 10,
          font: { size: 10 },
          callback: function (value) {
            // value is the index; this.getLabelForValue gives YYYY-MM-DD.
            const lbl = this.getLabelForValue(value);
            if (!lbl) return "";
            const parts = lbl.split("-");
            return `${parts[2]}/${parts[1]}`;
          },
        },
      },
      y: { beginAtZero: true, ticks: { font: { size: 10 } } },
    },
  };
  if (charts[siteKey]) {
    charts[siteKey].data = data;
    charts[siteKey].options = options;
    charts[siteKey].update();
  } else {
    charts[siteKey] = new Chart(ctx, { type: "line", data, options });
  }
}

function renderConflicts(conflicts) {
  if (!conflicts || conflicts.length === 0) {
    els.conflictsSection.hidden = true;
    return;
  }
  els.conflictsSection.hidden = false;
  const nowMs = Date.now();
  els.conflictsList.innerHTML = conflicts.map((c) => {
    const livePill = c.overlap_start <= nowMs && nowMs <= c.overlap_stop
      ? '<span class="pill pill--live">LIVE NOW</span>' : "";
    const eff = c.effective_available != null
      ? ` <span class="conflict-eff">effective available: <strong>${formatNum(c.effective_available)} ${escapeHtml(c.unit)}</strong></span>`
      : "";
    return `<li>
      <div class="conflict-head">
        <strong>${escapeHtml(c.site)} · ${escapeHtml(c.category)}</strong>
        ${livePill}
        <span class="conflict-window">overlap ${formatTs(new Date(c.overlap_start).toISOString())} → ${formatTs(new Date(c.overlap_stop).toISOString())}</span>
        ${eff}
      </div>
      <div class="conflict-pair">
        <code>${escapeHtml(c.a.thread_id || "")}</code>
        (avail ${formatNum(c.a.available_capacity)} ${escapeHtml(c.unit)},
         ${formatTs(c.a.event_start)} → ${formatTs(c.a.event_stop)})
        ↔
        <code>${escapeHtml(c.b.thread_id || "")}</code>
        (avail ${formatNum(c.b.available_capacity)} ${escapeHtml(c.unit)},
         ${formatTs(c.b.event_start)} → ${formatTs(c.b.event_stop)})
      </div>
    </li>`;
  }).join("");
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

setInterval(updateClock, 1000);
updateClock();

// Initial load and a polling loop so the page picks up background refreshes.
loadData();
setInterval(loadData, 30000);
