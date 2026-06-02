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
};

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
  renderTable();
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
