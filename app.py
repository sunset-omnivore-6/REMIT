from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# curl_cffi speaks Chrome's actual TLS handshake (JA3/JA4) so we look like
# Chromium at the socket level, not just the HTTP layer. This is the durable
# fix for SSE's WAF — header-matching alone is fragile because the WAF can
# (and now does) inspect the TLS fingerprint, which plain `requests` cannot
# disguise. We fall back to `requests` if curl_cffi is not installed.
try:
    from curl_cffi import requests as _impersonate_requests
    _HAS_IMPERSONATE = True
except ImportError:
    _impersonate_requests = None
    _HAS_IMPERSONATE = False
_IMPERSONATE_TARGET = "chrome131"

# NOTE: A Playwright (headless-Chromium) fetch path used to live here. It was
# removed because it cannot work on Streamlit Community Cloud — `pip install
# playwright` does not install the Chromium binary, so the launch always failed
# and, since it was the *preferred* path, the app crashed (st.stop) on every
# cold start / wake. The curl_cffi TLS-impersonation path below is sufficient:
# it returns HTTP 200 from cloud datacenter IPs (verified), and transient WAF
# 403s are now handled by retry rather than a hard failure.

API_URL = "https://thermaloutages.sse.com/api/v1/outages/gasuof"
LANDING_URL = "https://thermaloutages.sse.com/gas-uof"
SITES = ["Aldbrough", "Atwick"]
CATEGORIES = ["Withdrawal", "Injection", "Storage"]
PAGE_SIZE = 100
FAR_FUTURE = pd.Timestamp("2099-01-01", tz="UTC")

# SSE's Azure Front Door WAF intermittently 403s an otherwise-valid request
# (the same request shape returns 200 on retry — verified from a cloud IP).
# This — not any IP/header issue — is the real cause of the historical "breaks
# every couple of days / won't come back after sleep" symptom. We retry through
# these transient statuses instead of failing the whole load.
RETRYABLE_STATUSES = frozenset({403, 408, 429, 500, 502, 503, 504})
MAX_FETCH_RETRIES = 4               # total attempts (1 try + 3 retries)
RETRY_BACKOFF_SECONDS = (1, 3, 6)   # waited before retries 2, 3, 4
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
    ),
    # Mirror the live browser request exactly. In particular: no Origin header
    # (browsers omit it on same-origin GETs — sending it is a Python tell that
    # SSE's WAF flags) and Accept: */* rather than the axios default.
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://thermaloutages.sse.com/gas-uof",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Sec-CH-UA": (
        '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"'
    ),
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Priority": "u=1, i",
}

# Nameplate technical capacities. These are AUTHORITATIVE: individual REMIT
# records carry varying/stale technicalCapacity figures, so where a
# (site, category) appears here this value is used in preference to anything
# in the data. Combinations not listed fall back to the data-derived figure.
TECH_CAPACITY_FALLBACK: dict[tuple[str, str], float] = {
    ("Aldbrough", "Withdrawal"): 287.78,  # GWh/d
    ("Aldbrough", "Injection"): 293.33,   # GWh/d
    ("Aldbrough", "Storage"): 3.3,        # TWh
    ("Atwick", "Withdrawal"): 130.0,      # GWh/d
    ("Atwick", "Injection"): 30.0,        # GWh/d
    ("Atwick", "Storage"): 3.47,          # TWh
}

DEFAULT_UNIT: dict[str, str] = {
    "Withdrawal": "GWh/d",
    "Injection": "GWh/d",
    "Storage": "TWh",
}

# Palette. Greys are deliberately darkened from the typical Tailwind values
# so body text clears WCAG AA contrast on the light surface.
COLOR = {
    "ok": "#16a34a",
    "warn": "#d97706",
    "bad": "#dc2626",
    "info": "#2563eb",
    "muted": "#64748b",
    "Withdrawal": "#dc2626",
    "Injection": "#2563eb",
    "Storage": "#7c3aed",
    "Planned": "#2563eb",
    "Unplanned": "#dc2626",
}

# Display-only site rename: data keeps "Atwick" everywhere (matching, thread
# prefixes, tech-capacity lookup); the UI shows "Hornsea". Apply at render
# points only — never to data filtering.
SITE_DISPLAY = {"Aldbrough": "Aldbrough", "Atwick": "Hornsea"}

# Planned / Unplanned is shown as a neutral grey pill (no red/blue), so colour
# is reserved for site+category identity and capacity direction.
NEUTRAL_PILL = "#6b7280"


def site_label(site: str) -> str:
    return SITE_DISPLAY.get(site, site)


def type_pill(site: str, category: str) -> str:
    """Coloured box for '<Site> <Category>' — withdrawal red, injection blue,
    storage purple, white text. The single clear signal of what an outage is."""
    color = COLOR.get(category, COLOR["muted"])
    return (
        f"<span class='remit-typepill' style='background:{color}'>"
        f"{site_label(site)} {category}</span>"
    )


def cat_pill(category: str) -> str:
    """Category-only coloured box (same style as type_pill, no site)."""
    color = COLOR.get(category, COLOR["muted"])
    return (
        f"<span class='remit-typepill' style='background:{color}'>"
        f"{category}</span>"
    )


st.set_page_config(
    page_title="REMIT — Aldbrough & Hornsea",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_css() -> None:
    """Single source of styling for all custom HTML in the app."""
    st.markdown(
        """
        <style>
        /* Match the desktop dashboard's typography (Inter) and page surface. */
        @import url('https://rsms.me/inter/inter.css');
        :root {
          --remit-ok: #16a34a;
          --remit-warn: #d97706;
          --remit-bad: #dc2626;
          --remit-info: #2563eb;
          --remit-muted: #64748b;
          --remit-ink: #0f172a;
          --remit-ink-soft: #475569;
          --remit-surface: #f8fafc;
          --remit-page: #f6f8fb;
          --remit-border: #e2e8f0;
          --remit-radius: 10px;
          --remit-shadow: 0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.04);
        }
        html, body, [class*="css"], .stApp, button, input, textarea, select {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
            Roboto, Helvetica, Arial, sans-serif !important;
          font-feature-settings: 'cv11', 'ss01';
        }
        /* Desktop page surface tint. */
        .stApp { background: var(--remit-page); }
        .block-container { padding-top: 2.2rem; max-width: 1280px; }
        /* Capacity dials (per-site headline) */
        .remit-sitecard__title {
          font-size: 1.05rem; font-weight: 700; color: var(--remit-ink);
          letter-spacing: -0.01em; margin: 0.1rem 0 0.35rem;
        }
        .remit-dial__cat {
          font-size: 0.82rem; font-weight: 600; color: var(--remit-ink-soft);
          text-align: center; white-space: nowrap;
        }
        .remit-dial__sub {
          font-size: 0.82rem; font-weight: 600; color: var(--remit-ink);
          text-align: center; margin-top: -0.4rem;
        }
        .remit-dial__count {
          font-size: 0.72rem; color: var(--remit-muted); text-align: center;
        }
        /* Card */
        .remit-card {
          background: #ffffff;
          border: 1px solid var(--remit-border);
          border-left: 4px solid var(--remit-muted);
          border-radius: var(--remit-radius);
          padding: 0.6rem 0.85rem;
          margin: 0.5rem 0;
        }
        .remit-card__head {
          display: flex; justify-content: space-between;
          align-items: center; gap: 0.4rem;
        }
        .remit-card__meta { font-size: 0.78rem; color: var(--remit-ink-soft); }
        .remit-card__body {
          margin-top: 0.4rem; font-size: 0.92rem; color: var(--remit-ink);
        }
        .remit-card__sub {
          font-size: 0.85rem; color: var(--remit-ink-soft); margin-top: 0.25rem;
        }
        .remit-card__sub--em { font-style: italic; }
        /* Pill */
        .remit-pill {
          display: inline-block; padding: 0.12rem 0.55rem;
          border-radius: 999px; font-size: 0.72rem; font-weight: 600;
          color: #fff; white-space: nowrap;
        }
        /* Type pill — '<Site> <Category>' coloured box (DEV-bar style). */
        .remit-typepill {
          display: inline-block; padding: 0.15rem 0.6rem;
          border-radius: 6px; font-size: 0.85rem; font-weight: 700;
          color: #fff; white-space: nowrap; letter-spacing: 0.01em;
        }
        /* Progress */
        .remit-progress {
          background: var(--remit-border); border-radius: 6px;
          height: 8px; width: 100%; overflow: hidden; margin-top: 0.25rem;
        }
        .remit-progress__fill { height: 100%; border-radius: 6px; }
        /* KPI card — the only elevated element on the page */
        .remit-kpi {
          background: #ffffff;
          border: 1px solid var(--remit-border);
          border-radius: var(--remit-radius);
          box-shadow: var(--remit-shadow);
          padding: 0.85rem 1rem;
          margin: 0.6rem 0;
        }
        .remit-kpi__head {
          display: flex; justify-content: space-between; align-items: baseline;
          gap: 0.4rem; margin-bottom: 0.35rem;
        }
        .remit-kpi__cat {
          font-weight: 600; color: var(--remit-ink); font-size: 0.95rem;
        }
        .remit-kpi__count {
          font-size: 0.78rem; color: var(--remit-ink-soft);
        }
        .remit-kpi__value {
          font-size: 1.9rem; font-weight: 700; line-height: 1.15;
        }
        .remit-kpi__sub {
          font-size: 0.84rem; color: var(--remit-ink-soft); margin-top: 0.1rem;
        }
        /* Banner */
        .remit-banner {
          border-radius: var(--remit-radius); padding: 0.7rem 1rem;
          margin-bottom: 0.6rem; border-left: 5px solid var(--remit-info);
          background: #eff6ff;
        }
        .remit-banner--alert {
          border-left-color: var(--remit-bad); background: #fef2f2;
        }
        .remit-banner--warn {
          border-left-color: var(--remit-warn); background: #fffbeb;
        }
        .remit-banner--ok {
          border-left-color: var(--remit-ok); background: #f0fdf4;
        }
        .remit-banner__title { font-weight: 700; color: var(--remit-ink); }
        /* App header */
        .remit-masthead {
          background: #eff6ff;
          border: 1px solid var(--remit-border);
          border-left: 5px solid var(--remit-info);
          border-radius: var(--remit-radius);
          padding: 0.9rem 1.1rem;
          margin-bottom: 0.9rem;
        }
        /* DEV-environment marker — present only on the dev branch; removed when
           promoting dev -> prod so production never shows it. */
        .remit-devbar {
          background: #d97706; color: #ffffff; font-weight: 800;
          letter-spacing: 0.18em; text-align: center; border-radius: 6px;
          padding: 0.35rem 0.5rem; margin-bottom: 0.7rem; font-size: 0.95rem;
        }
        /* Collapsible banner — the styled banner IS the clickable <summary>;
           expanding reveals the change cards. Shared by Upcoming + Recent. */
        details.remit-collapse { margin-bottom: 0.6rem; }
        details.remit-collapse > summary {
          display: block; list-style: none; cursor: pointer; outline: none;
        }
        details.remit-collapse > summary::-webkit-details-marker { display: none; }
        details.remit-collapse > summary .remit-banner { margin-bottom: 0; }
        details.remit-collapse[open] > summary .remit-banner { margin-bottom: 0.5rem; }
        .remit-chev {
          display: inline-block; transition: transform 0.2s ease;
          color: var(--remit-ink-soft); font-size: 0.8em;
        }
        details.remit-collapse[open] > summary .remit-chev { transform: rotate(90deg); }
        /* Click-to-expand / click-to-compress hint (closed shows expand). */
        .remit-hint { color: #94a3b8; font-weight: 400; font-size: 0.85em; }
        .remit-hint--compress { display: none; }
        details.remit-collapse[open] > summary .remit-hint--expand { display: none; }
        details.remit-collapse[open] > summary .remit-hint--compress { display: inline; }
        .remit-header__title {
          font-size: 1.7rem; font-weight: 800; color: var(--remit-ink);
          margin: 0; line-height: 1.2;
        }
        .remit-header__sub {
          color: var(--remit-ink-soft); font-size: 0.92rem;
          margin: 0.15rem 0 0;
        }
        /* Editorial section header */
        .remit-section {
          display: flex; justify-content: space-between; align-items: baseline;
          gap: 0.6rem; margin: 0.55rem 0 0.35rem 0;
        }
        .remit-section__label {
          font-size: 1.05rem; font-weight: 700; color: var(--remit-ink);
          letter-spacing: 0.01em;
          border-left: 3px solid var(--remit-info); padding-left: 0.5rem;
        }
        .remit-section__meta {
          font-size: 0.82rem; color: var(--remit-ink-soft);
        }
        /* Generic rows / lines */
        .remit-row {
          display: flex; justify-content: space-between;
          align-items: baseline; gap: 0.4rem;
        }
        .remit-line {
          font-size: 0.88rem; color: var(--remit-ink); margin: 0.15rem 0;
        }
        .remit-line__meta { color: var(--remit-ink-soft); }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()

# Wall-display mode: rerun the script every 5 min so the 5-min cache TTL on
# fetch_remit expires on the same cycle and live data comes through.
REFRESH_INTERVAL_MS = 5 * 60 * 1000
st_autorefresh(interval=REFRESH_INTERVAL_MS, key="remit_auto_refresh")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _remit_session():
    """A primed session for the SSE API. Uses curl_cffi to impersonate
    Chrome's TLS handshake when available (the only defence against WAFs
    that fingerprint at JA3/JA4 rather than headers), and falls back to
    `requests` otherwise. The landing-page GET seeds any cookies the edge
    sets so subsequent API calls carry them."""
    if _HAS_IMPERSONATE:
        s = _impersonate_requests.Session(impersonate=_IMPERSONATE_TARGET)
    else:
        s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(LANDING_URL, timeout=30)
    except Exception:
        # Priming is best-effort; the API call below will surface a real error.
        pass
    return s


def _api_params(page: int, revisions: str) -> dict:
    return {
        "pageNumber": page,
        "pageSize": PAGE_SIZE,
        "sortDirection": "DESC",
        "sortBy": "PublicationDateTime",
        "revisionsReturned": revisions,
        "outageDateMatch": "CONTAINED",
    }


def _accumulate_payload(payload, rows: list[dict]) -> tuple[int, int | None]:
    """Common pagination handling: append items to rows, return (n_items,
    totalCount-or-None)."""
    if isinstance(payload, dict):
        items = (
            payload.get("items")
            or payload.get("data")
            or payload.get("results")
            or []
        )
        total = payload.get("totalCount") or payload.get("total")
    else:
        items = payload
        total = None
    if items:
        rows.extend(items)
    return len(items), total


def _get_page_with_retry(session, params: dict):
    """GET one API page, retrying through SSE's intermittent WAF rejections.

    Returns (payload, session) — session is returned because a retry may
    re-prime it (fresh WAF cookies). Raises RuntimeError with a rich
    diagnostic only after every attempt is exhausted.
    """
    last_resp = None
    for attempt in range(MAX_FETCH_RETRIES):
        try:
            resp = session.get(API_URL, params=params, timeout=30)
        except Exception as exc:
            # Transport-level failure (DNS / connect / timeout) — common on the
            # very first request right after a cold start / wake. Retry.
            if attempt == MAX_FETCH_RETRIES - 1:
                raise RuntimeError(
                    f"SSE request failed: {type(exc).__name__}: {exc}"
                ) from exc
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
            _remit_session.clear()
            session = _remit_session()
            continue

        last_resp = resp
        if resp.status_code == 200:
            return resp.json(), session

        # Transient WAF status with attempts remaining: back off, re-prime, retry.
        if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_FETCH_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
            _remit_session.clear()       # drop possibly-stale WAF cookies
            session = _remit_session()   # re-prime via the landing page
            continue

        break  # non-retryable status, or retries exhausted

    resp = last_resp
    transport = (
        f"curl_cffi/{_IMPERSONATE_TARGET}" if _HAS_IMPERSONATE
        else "requests (no TLS impersonation)"
    )
    deny = resp.headers.get("x-deny-reason", "(none)")
    server = resp.headers.get("server", "(unknown)")
    try:
        body_snippet = " ".join(resp.text[:300].split())
    except Exception:
        body_snippet = "(body unreadable)"
    raise RuntimeError(
        f"SSE returned {resp.status_code} after {MAX_FETCH_RETRIES} attempts. "
        f"Transport: {transport}. x-deny-reason: {deny}. Server: {server}. "
        f"Body[:300]: {body_snippet}"
    )


def _fetch_remit_via_session(revisions: str) -> pd.DataFrame:
    """Fetch every page via curl_cffi (Chrome TLS impersonation) or plain
    requests, retrying through SSE's intermittent WAF 403s."""
    session = _remit_session()
    rows: list[dict] = []
    page = 1
    while True:
        params = _api_params(page, revisions)
        payload, session = _get_page_with_retry(session, params)
        n_items, total = _accumulate_payload(payload, rows)
        if not n_items:
            break
        if total is not None and len(rows) >= total:
            break
        if n_items < PAGE_SIZE:
            break
        page += 1
        if page > 200:
            break

    return pd.json_normalize(rows)


@st.cache_data(ttl=300, show_spinner="Fetching REMIT data…")
def fetch_remit(revisions: str = "Latest") -> pd.DataFrame:
    """Fetch + paginate the SSE REMIT API, cached for 5 minutes to match the
    auto-refresh cycle. Raises on failure; the caller keeps the last good
    snapshot and shows a banner instead of crashing."""
    return _fetch_remit_via_session(revisions)


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Map logical fields → actual column name in df, tolerating naming variants."""
    norm_map = {_norm(c): c for c in df.columns}

    def find(*candidates: str) -> str | None:
        # exact match first
        for cand in candidates:
            if _norm(cand) in norm_map:
                return norm_map[_norm(cand)]
        # substring fallback
        for cand in candidates:
            cn = _norm(cand)
            for k, v in norm_map.items():
                if cn and cn in k:
                    return v
        return None

    return {
        "asset": find("assetName", "asset", "unitName", "facilityName",
                      "facility", "affectedAssetName", "storageFacility"),
        "unitEic": find("unitEicCode", "unitEic", "eicCode", "assetEic"),
        "eventStart": find(
            "eventStartDateTime", "eventStartTime", "eventStart",
            "outageStart", "startTime", "startDateTime", "startDate",
            "unavailabilityStart", "fromDate", "fromDateTime",
            "from", "begin", "beginDateTime",
        ),
        "eventEnd": find(
            "eventStopDateTime", "eventStopTime", "eventStop",
            "eventEndDateTime", "eventEndTime", "eventEnd",
            "outageEnd", "outageStop", "endTime", "endDateTime", "endDate",
            "stopTime", "stopDateTime", "stopDate",
            "unavailabilityEnd", "toDate", "toDateTime",
            "expectedEnd", "expectedEndDate", "to",
        ),
        "publication": find("publicationDateTime", "publicationDate",
                            "publishedDate", "publishDateTime", "published"),
        "status": find("eventStatus", "status", "state"),
        "typeOfEvent": find("typeOfEvent", "eventType", "unavailabilityCategory"),
        "typeOfUnavailability": find("typeOfUnavailability",
                                     "unavailabilityType", "natureOfUnavailability",
                                     "planningStatus", "planned"),
        "techCapacity": find("technicalCapacity"),
        "availCapacity": find("availableCapacity"),
        "unavailCapacity": find("unavailableCapacity"),
        "unit": find("unitOfMeasurement", "unitOfMeasure", "uom"),
        "reason": find("reasonForTheUnavailability", "reasonForUnavailability",
                       "reason", "cause"),
        "remarks": find("remarks", "comments", "notes", "description"),
        "threadId": find("threadId", "thread"),
        "revisionNumber": find("revisionNumber", "revision", "version"),
        "messageId": find("messageId", "id"),
    }


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _category_from_event(val: object) -> str | None:
    s = str(val).lower()
    if "withdraw" in s:
        return "Withdrawal"
    if "inject" in s:
        return "Injection"
    if "storage" in s:
        return "Storage"
    return None


def _site_from_asset(val: object) -> str | None:
    s = str(val).lower()
    if "atwick" in s:
        return "Atwick"
    if "aldbrough" in s or "aldborough" in s:
        return "Aldbrough"
    return None


def normalise(df: pd.DataFrame, cmap: dict[str, str | None]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    # Asset → Site
    asset_col = cmap["asset"]
    if asset_col is None:
        # Fall back to scanning every column for the site name
        out["__site__"] = None
        for c in out.columns:
            sites = out[c].astype(str).map(_site_from_asset)
            out["__site__"] = out["__site__"].fillna(sites)
    else:
        out["__site__"] = out[asset_col].map(_site_from_asset)

    # Category
    ev_col = cmap["typeOfEvent"]
    if ev_col is not None:
        out["__category__"] = out[ev_col].map(_category_from_event)
    else:
        out["__category__"] = None

    # Dates — always store as a datetime-typed Series so comparisons work
    # even when the source column wasn't detected.
    nat_series = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
    for logical in ("eventStart", "eventEnd", "publication"):
        col = cmap[logical]
        if col is not None:
            out[f"__{logical}__"] = pd.to_datetime(out[col], errors="coerce", utc=True)
        else:
            out[f"__{logical}__"] = nat_series.copy()

    # Numeric capacities
    for logical in ("techCapacity", "availCapacity", "unavailCapacity"):
        col = cmap[logical]
        out[f"__{logical}__"] = (
            pd.to_numeric(out[col], errors="coerce") if col is not None else pd.NA
        )

    # Status
    status_col = cmap["status"]
    out["__status__"] = out[status_col].astype(str) if status_col else "Active"

    # Planned / Unplanned
    plan_col = cmap["typeOfUnavailability"]
    if plan_col is not None:
        s = out[plan_col].astype(str).str.lower()
        out["__planned__"] = s.map(
            lambda x: "Unplanned" if "unplan" in x else ("Planned" if "plan" in x else "Unknown")
        )
    else:
        out["__planned__"] = "Unknown"

    return out


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def pill(text: str, color: str) -> str:
    return f"<span class='remit-pill' style='background:{color}'>{text}</span>"


def progress_bar(pct: float, color: str) -> str:
    pct = max(0.0, min(100.0, pct))
    return (
        f"<div class='remit-progress'>"
        f"<div class='remit-progress__fill' "
        f"style='width:{pct:.1f}%;background:{color}'></div></div>"
    )


def section_header(text: str, meta: str | None = None) -> None:
    meta_html = (
        f"<div class='remit-section__meta'>{meta}</div>" if meta else ""
    )
    st.markdown(
        f"<div class='remit-section'>"
        f"<div class='remit-section__label'>{text}</div>"
        f"{meta_html}</div>",
        unsafe_allow_html=True,
    )


def headline_color(pct_avail: float, has_unplanned: bool, category: str) -> str:
    if category == "Storage":
        if pct_avail < 10:
            return COLOR["bad"]
        if pct_avail < 60:
            return COLOR["warn"]
        return COLOR["ok"]
    if has_unplanned and pct_avail < 100:
        return COLOR["bad"]
    if pct_avail < 50:
        return COLOR["bad"]
    if pct_avail < 90:
        return COLOR["warn"]
    return COLOR["ok"]


def fmt_dt(dt) -> str:
    if pd.isna(dt):
        return "—"
    return dt.strftime("%d %b %Y, %H:%M")


# ---------------------------------------------------------------------------
# Compute slices
# ---------------------------------------------------------------------------

def active_now(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["__eventStart__"] <= now) & (
        df["__eventEnd__"].isna() | (df["__eventEnd__"] >= now)
    )
    return df[mask]


def upcoming(df: pd.DataFrame, now: pd.Timestamp, horizon_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    horizon = now + pd.Timedelta(days=horizon_days)
    mask = (df["__eventStart__"] > now) & (df["__eventStart__"] <= horizon)
    return df[mask].sort_values("__eventStart__")


def site_category_headline(
    df_active: pd.DataFrame,
    df_all_site: pd.DataFrame,
    site: str,
    category: str,
) -> tuple[float, float, float, bool, int]:
    """Return (tech, available, unavailable, has_unplanned, n_events).

    Technical capacity is sourced in order of preference:
      1. hard-coded nameplate value (TECH_CAPACITY_FALLBACK) — authoritative
      2. max from currently-active events for this (site, cat)
      3. max from any (latest-revision) event for this (site, cat)
    """
    sub = df_active[
        (df_active["__site__"] == site) & (df_active["__category__"] == category)
    ]
    tech = TECH_CAPACITY_FALLBACK.get((site, category), float("nan"))
    if pd.isna(tech):
        tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
    if pd.isna(tech):
        all_sub = df_all_site[df_all_site["__category__"] == category]
        tech = all_sub["__techCapacity__"].dropna().max() if not all_sub.empty else float("nan")

    if sub.empty:
        return (float(tech), float("nan"), 0.0, False, 0)

    available = sub["__availCapacity__"].dropna().min()
    unavailable = sub["__unavailCapacity__"].dropna().sum()
    has_unplanned = (sub["__planned__"] == "Unplanned").any()
    return (
        float(tech) if pd.notna(tech) else float("nan"),
        float(available) if pd.notna(available) else float("nan"),
        float(unavailable),
        bool(has_unplanned),
        len(sub),
    )


def tech_capacity_lookup(
    df: pd.DataFrame, categories: list[str]
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for site in SITES:
        for cat in categories:
            # Nameplate values are authoritative when known.
            if (site, cat) in TECH_CAPACITY_FALLBACK:
                out[(site, cat)] = TECH_CAPACITY_FALLBACK[(site, cat)]
                continue
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
            if pd.notna(tech) and tech > 0:
                out[(site, cat)] = float(tech)
    return out


# ---------------------------------------------------------------------------
# Capacity-change detection (next N days)
# ---------------------------------------------------------------------------

def _capacity_at(
    df: pd.DataFrame, site: str, cat: str, t: pd.Timestamp, tech: float
) -> float:
    """Effective available capacity at instant `t`, taking the conservative
    minimum across overlapping events."""
    active = df[
        (df["__site__"] == site)
        & (df["__category__"] == cat)
        & (df["__eventStart__"] <= t)
        & (df["__eventEnd__"].isna() | (df["__eventEnd__"] > t))
    ]
    if active.empty:
        return tech
    avails = active["__availCapacity__"].dropna()
    if not avails.empty:
        return float(avails.min())
    unavail_sum = active["__unavailCapacity__"].fillna(0).sum()
    return max(0.0, float(tech) - float(unavail_sum))


def compute_capacity_changes(
    df_op: pd.DataFrame,
    tech_lookup: dict[tuple[str, str], float],
    categories: list[str],
    lookahead_days: int = 7,
    threshold: float = 0.5,
) -> list[dict]:
    """Find every step change in effective available capacity within window."""
    now = pd.Timestamp.now(tz="UTC")
    horizon = now + pd.Timedelta(days=lookahead_days)
    changes: list[dict] = []

    for site in SITES:
        for cat in categories:
            tech = tech_lookup.get((site, cat))
            if tech is None:
                continue
            sub = df_op[(df_op["__site__"] == site) & (df_op["__category__"] == cat)]
            if sub.empty:
                continue

            # Candidate transition moments = event starts AND event ends in window
            starts = sub[
                (sub["__eventStart__"] > now)
                & (sub["__eventStart__"] <= horizon)
            ][["__eventStart__"]].rename(columns={"__eventStart__": "t"})
            ends = sub[
                sub["__eventEnd__"].notna()
                & (sub["__eventEnd__"] > now)
                & (sub["__eventEnd__"] <= horizon)
            ][["__eventEnd__"]].rename(columns={"__eventEnd__": "t"})
            moments = pd.concat([starts, ends]).sort_values("t").drop_duplicates()

            if moments.empty:
                continue

            prev_avail = _capacity_at(df_op, site, cat, now, tech)
            for t in moments["t"]:
                # Sample just after the transition
                t_after = t + pd.Timedelta(seconds=1)
                new_avail = _capacity_at(df_op, site, cat, t_after, tech)
                if abs(new_avail - prev_avail) >= threshold:
                    # Find the dominant event driving the change at this moment
                    driver_starts = sub[sub["__eventStart__"] == t]
                    driver_ends = sub[sub["__eventEnd__"] == t]
                    driver = (
                        driver_starts.iloc[0]
                        if not driver_starts.empty
                        else (driver_ends.iloc[0] if not driver_ends.empty else None)
                    )
                    changes.append(
                        {
                            "site": site,
                            "category": cat,
                            "when": t,
                            "from": prev_avail,
                            "to": new_avail,
                            "tech": tech,
                            "is_start": not driver_starts.empty,
                            "driver": driver,
                        }
                    )
                    prev_avail = new_avail
    changes.sort(key=lambda c: c["when"])
    return changes


def render_changes_banner(
    changes: list[dict], cmap: dict[str, str | None]
) -> None:
    now = pd.Timestamp.now(tz="UTC")

    if not changes:
        st.markdown(
            "<div class='remit-banner'>"
            "<span class='remit-banner__title'>Zero upcoming capacity changes "
            "(next 7 days)</span></div>",
            unsafe_allow_html=True,
        )
        return

    drops = sum(1 for c in changes if c["to"] < c["from"])
    rises = sum(1 for c in changes if c["to"] > c["from"])

    banner_class = "remit-banner remit-banner--alert" if drops else "remit-banner"
    summary = []
    if drops:
        summary.append(
            f"<span style='color:{COLOR['bad']};font-weight:600'>"
            f"{drops} capacity drop{'s' if drops != 1 else ''}</span>"
        )
    if rises:
        summary.append(
            f"<span style='color:{COLOR['ok']};font-weight:600'>"
            f"{rises} restoration{'s' if rises != 1 else ''}</span>"
        )

    cards: list[str] = []
    for c in changes:
        site = c["site"]
        cat = c["category"]
        unit = DEFAULT_UNIT.get(cat, "")
        arrow_color = COLOR["bad"] if c["to"] < c["from"] else COLOR["ok"]
        arrow = "↓" if c["to"] < c["from"] else "↑"
        when_dt = c["when"]
        hours_away = (when_dt - now).total_seconds() / 3600
        if hours_away < 24:
            when_str = f"in {hours_away:.0f} h ({when_dt.strftime('%a %H:%M')})"
        elif hours_away < 24 * 7:
            when_str = when_dt.strftime("%a %d %b %H:%M")
        else:
            when_str = when_dt.strftime("%d %b %Y %H:%M")

        driver = c["driver"]
        planned = driver["__planned__"] if driver is not None else ""
        reason_col = cmap.get("reason")
        reason = (
            str(driver[reason_col]) if driver is not None and reason_col else ""
        )
        planned_pill = pill(planned, NEUTRAL_PILL) if planned else ""
        reason_html = (
            f"<div class='remit-card__sub remit-card__sub--em'>{reason}</div>"
            if reason and reason not in ("-", "nan", "None")
            else ""
        )

        cards.append(
            f"<div class='remit-card' style='border-left-color:{arrow_color}'>"
            f"<div class='remit-card__head'>"
            f"<div>{type_pill(site, cat)} {planned_pill}</div>"
            f"<div class='remit-card__meta'>{when_str}</div>"
            f"</div>"
            f"<div class='remit-card__body' style='font-size:1.1rem'>"
            f"<b>{c['from']:g} {unit}</b> "
            f"<span style='color:{arrow_color};font-weight:700'>{arrow}</span> "
            f"<b style='color:{arrow_color}'>{c['to']:g} {unit}</b> "
            f"<span class='remit-card__meta'>(tech max {c['tech']:g})</span>"
            f"</div>"
            f"{reason_html}"
            f"</div>"
        )

    st.markdown(
        f"<details class='remit-collapse' open>"
        f"<summary>"
        f"<div class='{banner_class}'>"
        f"<span class='remit-chev'>&#9656;</span> "
        f"<span class='remit-banner__title'>Upcoming capacity changes "
        f"(next 7 days)</span> · " + " · ".join(summary)
        + "<span class='remit-hint remit-hint--expand'> · click to expand</span>"
        + "<span class='remit-hint remit-hint--compress'> · click to compress</span>"
        + "</div>"
        "</summary>"
        "<div class='remit-collapse__body'>" + "".join(cards) + "</div>"
        "</details>",
        unsafe_allow_html=True,
    )


def compute_recent_changes(
    df: pd.DataFrame, cmap: dict[str, str | None], lookback_hours: int = 24
) -> list[dict]:
    """REMITs created, revised, ended or dismissed within the lookback window.

    Works from latest-revision data: every revision carries a fresh
    publication timestamp, so a publication inside the window means the
    notice changed since then. `df` (not `df_op`) is used so dismissed
    REMITs are visible here.
    """
    now = pd.Timestamp.now(tz="UTC")
    cutoff = now - pd.Timedelta(hours=lookback_hours)
    rev_col = cmap.get("revisionNumber")

    recent = df[
        df["__site__"].isin(SITES)
        & df["__publication__"].notna()
        & (df["__publication__"] >= cutoff)
    ]
    items: list[dict] = []
    for _, row in recent.iterrows():
        status = str(row["__status__"]).lower()
        end = row["__eventEnd__"]
        rev = row[rev_col] if rev_col else None
        try:
            rev_num = int(float(rev)) if rev is not None and pd.notna(rev) else 1
        except (ValueError, TypeError):
            rev_num = 1

        if "dismiss" in status:
            kind, kind_color = "Dismissed", COLOR["bad"]
        elif pd.notna(end) and end < now:
            kind, kind_color = "Ended", COLOR["muted"]
        elif rev_num > 1:
            kind, kind_color = "Revised", COLOR["warn"]
        else:
            kind, kind_color = "New", COLOR["info"]

        items.append(
            {
                "site": row["__site__"],
                "category": row["__category__"] or "—",
                "kind": kind,
                "kind_color": kind_color,
                "publication": row["__publication__"],
                "rev_num": rev_num,
                "row": row,
            }
        )
    items.sort(key=lambda x: x["publication"], reverse=True)
    return items


def render_recent_banner(
    items: list[dict], cmap: dict[str, str | None], lookback_hours: int = 24
) -> None:
    now = pd.Timestamp.now(tz="UTC")

    if not items:
        st.markdown(
            "<div class='remit-banner'>"
            f"<span class='remit-banner__title'>Zero recent REMIT changes "
            f"(last {lookback_hours} h)</span></div>",
            unsafe_allow_html=True,
        )
        return

    order = ["Dismissed", "Ended", "Revised", "New"]
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    summary = " · ".join(
        f"<span style='color:{next(i['kind_color'] for i in items if i['kind'] == k)};"
        f"font-weight:600'>{counts[k]} {k.lower()}</span>"
        for k in order
        if k in counts
    )
    # Alert styling if anything dropped out of the active picture
    alert = any(it["kind"] in ("Dismissed", "Ended") for it in items)
    banner_class = "remit-banner remit-banner--warn" if alert else "remit-banner"

    reason_col = cmap.get("reason")
    unit_col = cmap.get("unit")
    thread_col = cmap.get("threadId")

    cards: list[str] = []
    for it in items:
        row = it["row"]
        cat = it["category"]
        unit = (
            str(row[unit_col])
            if unit_col and pd.notna(row[unit_col])
            else DEFAULT_UNIT.get(cat, "")
        )
        unavail = row["__unavailCapacity__"]
        avail = row["__availCapacity__"]
        thread = row[thread_col] if thread_col else ""
        pub = it["publication"]
        hrs = (now - pub).total_seconds() / 3600
        pub_str = (
            f"{hrs:.0f} h ago"
            if hrs >= 1
            else f"{(now - pub).total_seconds() / 60:.0f} min ago"
        )
        reason = str(row[reason_col]) if reason_col else ""
        reason_html = (
            f"<div class='remit-card__sub remit-card__sub--em'>{reason}</div>"
            if reason and reason not in ("-", "nan", "None")
            else ""
        )
        cap_html = ""
        if pd.notna(unavail):
            avail_txt = (
                f" · available {avail:g} {unit}" if pd.notna(avail) else ""
            )
            cap_html = (
                f"<div class='remit-card__body'>"
                f"<b>{unavail:g} {unit}</b> unavailable{avail_txt}</div>"
            )

        cards.append(
            f"<div class='remit-card' "
            f"style='border-left-color:{it['kind_color']}'>"
            f"<div class='remit-card__head'>"
            f"<div>{pill(it['kind'], it['kind_color'])} "
            f"{type_pill(it['site'], cat)}</div>"
            f"<div class='remit-card__meta'>Thread {thread} · "
            f"rev {it['rev_num']} · published {pub_str}</div>"
            f"</div>"
            f"{cap_html}"
            f"<div class='remit-card__sub'>"
            f"{fmt_dt(row['__eventStart__'])} → "
            f"{fmt_dt(row['__eventEnd__'])}</div>"
            f"{reason_html}"
            f"</div>"
        )

    st.markdown(
        f"<details class='remit-collapse' open>"
        f"<summary>"
        f"<div class='{banner_class}'>"
        f"<span class='remit-chev'>&#9656;</span> "
        f"<span class='remit-banner__title'>Recent REMIT changes "
        f"(last {lookback_hours} h)</span> · " + summary
        + "<span class='remit-hint remit-hint--expand'> · click to expand</span>"
        + "<span class='remit-hint remit-hint--compress'> · click to compress</span>"
        + "</div>"
        "</summary>"
        "<div class='remit-collapse__body'>" + "".join(cards) + "</div>"
        "</details>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Rendering — hero cards
# ---------------------------------------------------------------------------

def render_event_card(row: pd.Series, cmap: dict[str, str | None]) -> str:
    cat = row["__category__"] or "—"
    planned = row["__planned__"]
    cat_color = COLOR.get(cat, COLOR["muted"])

    tech = row["__techCapacity__"]
    unavail = row["__unavailCapacity__"]
    avail = row["__availCapacity__"]
    unit = row[cmap["unit"]] if cmap["unit"] else ""
    reason = row[cmap["reason"]] if cmap["reason"] else ""
    remarks = row[cmap["remarks"]] if cmap["remarks"] else ""
    thread = row[cmap["threadId"]] if cmap["threadId"] else ""
    rev = row[cmap["revisionNumber"]] if cmap["revisionNumber"] else ""

    pct_unavail = (unavail / tech * 100) if pd.notna(tech) and tech else 0
    remarks_str = (
        f" — {remarks}"
        if remarks and str(remarks) not in ("-", "nan", "None", "")
        else ""
    )

    return (
        f"<div class='remit-card' style='border-left-color:{cat_color}'>"
        f"<div class='remit-card__head'>"
        f"<div>{type_pill(row['__site__'], cat)} {pill(planned, NEUTRAL_PILL)}</div>"
        f"<div class='remit-card__meta'>Thread {thread} · rev {rev}</div>"
        f"</div>"
        f"<div class='remit-card__body'>"
        f"<b>{unavail:g} {unit}</b> unavailable "
        f"({pct_unavail:.0f}% of {tech:g}) · available {avail:g} {unit}</div>"
        f"<div class='remit-card__sub'>"
        f"{fmt_dt(row['__eventStart__'])} → {fmt_dt(row['__eventEnd__'])}</div>"
        f"<div class='remit-card__sub remit-card__sub--em'>"
        f"{reason}{remarks_str}</div>"
        f"</div>"
    )


def dial_gradient_color(pct: float) -> str:
    """Map percent-available to a smooth red(0%) → amber(50%) → green(100%)
    gradient. Used purely for the capacity dials so the wheel colour reads as
    a continuous availability scale; planned/unplanned severity is conveyed by
    the Active outages section below, not by colour here.
    """
    pct = max(0.0, min(100.0, float(pct)))
    # Anchor stops use the existing palette's red and green endpoints with an
    # amber midpoint, interpolated linearly in RGB.
    stops = [
        (0.0, (0xDC, 0x26, 0x26)),    # red    #dc2626
        (50.0, (0xF5, 0x9E, 0x0B)),   # amber  #f59e0b
        (100.0, (0x16, 0xA3, 0x4A)),  # green  #16a34a
    ]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if pct <= p1:
            t = (pct - p0) / (p1 - p0) if p1 > p0 else 0.0
            r = round(c0[0] + (c1[0] - c0[0]) * t)
            g = round(c0[1] + (c1[1] - c0[1]) * t)
            b = round(c0[2] + (c1[2] - c0[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#16a34a"


def dial_figure(pct: float, color: str) -> go.Figure:
    """A doughnut 'dial' showing percent-available, mirroring the desktop
    dashboard's capacity dials (Chart.js doughnuts there, Plotly here)."""
    pct = max(0.0, min(100.0, float(pct)))
    fig = go.Figure(
        go.Pie(
            values=[pct, 100 - pct],
            hole=0.72,
            sort=False,
            direction="clockwise",
            rotation=0,
            marker=dict(colors=[color, "#eef2f7"], line=dict(width=0)),
            textinfo="none",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=128,
        paper_bgcolor="rgba(0,0,0,0)",
        annotations=[
            dict(
                text=f"<b>{pct:.0f}%</b>",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=24, color=color),
            )
        ],
    )
    return fig


def render_site_headline(
    site: str,
    df_active_site: pd.DataFrame,
    df_all_site_future: pd.DataFrame,
    cmap: dict[str, str | None],
    categories: list[str],
) -> None:
    st.markdown(
        f"<div class='remit-sitecard__title'>{site_label(site)}</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(categories), gap="small")
    for col, cat in zip(cols, categories):
        tech, avail, unavail, has_unplanned, n = site_category_headline(
            df_active_site, df_all_site_future, site, cat
        )
        if pd.notna(tech) and tech > 0:
            if pd.isna(avail):
                avail = tech  # nothing active → fully available
            pct = (avail / tech) * 100
        else:
            pct = float("nan")

        color = dial_gradient_color(pct if pd.notna(pct) else 100)

        # Unit string for this site×category, taken from the data
        unit_col = cmap.get("unit")
        unit_str = ""
        if unit_col:
            unit_vals = df_active_site[
                (df_active_site["__site__"] == site)
                & (df_active_site["__category__"] == cat)
            ][unit_col].dropna()
            if not unit_vals.empty:
                unit_str = str(unit_vals.mode().iloc[0])
            else:
                unit_str = DEFAULT_UNIT.get(cat, "")
        else:
            unit_str = DEFAULT_UNIT.get(cat, "")

        count_txt = f"{n} active event{'s' if n != 1 else ''}"
        with col:
            st.markdown(
                f"<div class='remit-dial__cat'>{cat_pill(cat)}</div>",
                unsafe_allow_html=True,
            )
            if pd.notna(pct):
                st.plotly_chart(
                    dial_figure(pct, color),
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"dial-{site}-{cat}",
                )
                avail_str = f"{avail:g}" if pd.notna(avail) else "—"
                tech_str = f"{tech:g}" if pd.notna(tech) else "—"
                st.markdown(
                    f"<div class='remit-dial__sub'>{avail_str} / {tech_str} "
                    f"{unit_str}</div>"
                    f"<div class='remit-dial__count'>{count_txt}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div class='remit-dial__sub'><i>no capacity "
                    "reference</i></div>",
                    unsafe_allow_html=True,
                )


def render_site_active(
    site: str,
    df_active_site: pd.DataFrame,
    cmap: dict[str, str | None],
    categories: list[str],
) -> None:
    st.markdown(
        f"<div class='remit-kpi__cat' style='font-size:1rem;"
        f"margin-bottom:0.2rem'>{site_label(site)}</div>",
        unsafe_allow_html=True,
    )

    for cat in categories:
        sub = df_active_site[df_active_site["__category__"] == cat]
        if sub.empty:
            continue
        expanded = cat != "Storage"  # storage collapsed
        with st.expander(f"{cat} — {len(sub)} active", expanded=expanded):
            for _, row in sub.iterrows():
                st.markdown(render_event_card(row, cmap), unsafe_allow_html=True)

    if df_active_site.empty:
        st.markdown(
            "<div class='remit-banner' style='border-left-color:var(--remit-ok);"
            "background:#f0fdf4'><span class='remit-banner__title' "
            "style='color:var(--remit-ok)'>All capacity available</span> — "
            "no active outages.</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tabs: upcoming, timeline, gantt, all data
# ---------------------------------------------------------------------------

def _safe_block(label: str, fn) -> None:
    """Run a render function, surfacing any error instead of a blank panel."""
    try:
        fn()
    except Exception as exc:
        st.error(f"{label} failed to render: {exc}")
        st.exception(exc)


def _add_now_line(fig: go.Figure, now: pd.Timestamp) -> None:
    """Vertical 'now' marker that survives plotly's tz-aware datetime quirks."""
    x = now.isoformat()
    fig.add_shape(
        type="line",
        xref="x",
        yref="paper",
        x0=x,
        x1=x,
        y0=0,
        y1=1,
        line=dict(color="#111827", width=1, dash="dot"),
    )
    fig.add_annotation(
        x=x,
        xref="x",
        y=1.02,
        yref="paper",
        text="now",
        showarrow=False,
        font=dict(size=11, color="#111827"),
    )


def render_upcoming(
    df_up: pd.DataFrame, cmap: dict[str, str | None], categories: list[str]
) -> None:
    if df_up.empty:
        st.info("No upcoming REMITs in window.")
        return
    for cat in categories:
        sub = df_up[df_up["__category__"] == cat]
        if sub.empty:
            continue
        muted = cat == "Storage"
        cat_color = COLOR.get(cat, COLOR["muted"])
        st.markdown(
            f"<div style='margin-top:0.6rem'>{cat_pill(cat)} "
            f"<span class='remit-card__meta'>— {len(sub)}</span></div>",
            unsafe_allow_html=True,
        )
        for _, row in sub.iterrows():
            opacity = "0.75" if muted else "1.0"
            site = row["__site__"]
            unit = row[cmap["unit"]] if cmap["unit"] else ""
            unavail = row["__unavailCapacity__"]
            reason = row[cmap["reason"]] if cmap["reason"] else ""
            st.markdown(
                f"<div class='remit-card' style='border-left-color:{cat_color};"
                f"opacity:{opacity};margin:0.3rem 0;padding:0.45rem 0.7rem'>"
                f"<span class='remit-line'><b>{site_label(site)}</b> · "
                f"{fmt_dt(row['__eventStart__'])} → "
                f"{fmt_dt(row['__eventEnd__'])} · "
                f"<b>{unavail:g} {unit}</b> unavailable · "
                f"{pill(row['__planned__'], NEUTRAL_PILL)} "
                f"<span class='remit-line__meta'>{reason}</span></span>"
                f"</div>",
                unsafe_allow_html=True,
            )


def compute_capacity_series(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    tech_lookup: dict[tuple[str, str], float],
    categories: list[str],
) -> pd.DataFrame:
    """Exact step-function of available capacity per (site, category).

    Capacity only changes at an event start or end, so we evaluate it on
    those breakpoints rather than on a fixed daily/hourly grid. This makes a
    2-hour outage show as a precise 2-hour dip, at any zoom level.
    """
    records = []
    for site in SITES:
        for cat in categories:
            tech = tech_lookup.get((site, cat))
            if tech is None:
                continue
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            sub = sub.dropna(subset=["__eventStart__"])

            # Breakpoints = window edges + every event start/end inside it
            bps: set[pd.Timestamp] = {start, end}
            for _, r in sub.iterrows():
                s = r["__eventStart__"]
                e = r["__eventEnd__"]
                if start <= s <= end:
                    bps.add(s)
                if pd.notna(e) and start <= e <= end:
                    bps.add(e)
            ordered = sorted(bps)

            # For each segment [bp_i, bp_i+1) evaluate capacity at its midpoint;
            # emit the value at the segment's left edge. line_shape="hv" then
            # draws a flat step. A trailing point closes the last segment.
            for i in range(len(ordered) - 1):
                seg_start = ordered[i]
                seg_end = ordered[i + 1]
                mid = seg_start + (seg_end - seg_start) / 2
                avail = _capacity_at(df, site, cat, mid, tech)
                records.append(
                    {
                        "date": seg_start,
                        "site": site,
                        "category": cat,
                        "available": avail,
                        "technical": tech,
                    }
                )
            if len(ordered) >= 2:
                last_mid = ordered[-2] + (ordered[-1] - ordered[-2]) / 2
                records.append(
                    {
                        "date": ordered[-1],
                        "site": site,
                        "category": cat,
                        "available": _capacity_at(df, site, cat, last_mid, tech),
                        "technical": tech,
                    }
                )
    return pd.DataFrame(records)


def detect_conflicts(
    df_op: pd.DataFrame, categories: list[str], cmap: dict[str, str | None]
) -> list[dict]:
    """Find overlapping REMITs for the same (site, category) that disagree on
    available capacity or end time — i.e. potential data-quality issues or
    competing notices that need a human to reconcile."""
    now = pd.Timestamp.now(tz="UTC")
    conflicts: list[dict] = []
    thread_col = cmap.get("threadId")

    for site in SITES:
        for cat in categories:
            sub = df_op[
                (df_op["__site__"] == site) & (df_op["__category__"] == cat)
            ].dropna(subset=["__eventStart__"])
            rows = list(sub.iterrows())
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    _, a = rows[i]
                    _, b = rows[j]
                    a_e = a["__eventEnd__"] if pd.notna(a["__eventEnd__"]) else FAR_FUTURE
                    b_e = b["__eventEnd__"] if pd.notna(b["__eventEnd__"]) else FAR_FUTURE
                    ov_start = max(a["__eventStart__"], b["__eventStart__"])
                    ov_end = min(a_e, b_e)
                    if ov_start >= ov_end:
                        continue  # no overlap
                    if ov_end < now:
                        continue  # overlap is entirely in the past

                    a_av = a["__availCapacity__"]
                    b_av = b["__availCapacity__"]
                    avail_differs = (
                        pd.notna(a_av)
                        and pd.notna(b_av)
                        and abs(float(a_av) - float(b_av)) > 0.5
                    )
                    end_differs = (
                        pd.notna(a["__eventEnd__"])
                        and pd.notna(b["__eventEnd__"])
                        and a["__eventEnd__"] != b["__eventEnd__"]
                    ) or (
                        pd.isna(a["__eventEnd__"]) != pd.isna(b["__eventEnd__"])
                    )
                    if not (avail_differs or end_differs):
                        continue

                    conflicts.append(
                        {
                            "site": site,
                            "category": cat,
                            "overlap_start": ov_start,
                            "overlap_end": ov_end if ov_end != FAR_FUTURE else None,
                            "avail_differs": avail_differs,
                            "end_differs": end_differs,
                            "a": a,
                            "b": b,
                            "thread_col": thread_col,
                        }
                    )
    conflicts.sort(key=lambda c: c["overlap_start"])
    return conflicts


def render_conflicts(conflicts: list[dict], cmap: dict[str, str | None]) -> None:
    if not conflicts:
        st.success("No overlapping REMITs with conflicting capacity or end times.")
        return

    st.markdown(
        f"<div class='remit-banner remit-banner--warn'>"
        f"<span class='remit-banner__title'>{len(conflicts)} overlapping "
        f"REMIT pair{'s' if len(conflicts) != 1 else ''}</span> active for the "
        f"same period with differing availability or end time — review for "
        f"data-quality issues or competing notices.</div>",
        unsafe_allow_html=True,
    )

    rev_col = cmap.get("revisionNumber")
    thread_col = cmap.get("threadId")
    reason_col = cmap.get("reason")

    def _ident(row: pd.Series) -> str:
        t = str(row[thread_col]) if thread_col else "?"
        r = f" rev {row[rev_col]}" if rev_col else ""
        return f"{t}{r}"

    for c in conflicts:
        a, b = c["a"], c["b"]
        tags = []
        if c["avail_differs"]:
            tags.append(pill("availability mismatch", COLOR["bad"]))
        if c["end_differs"]:
            tags.append(pill("end-time mismatch", COLOR["warn"]))
        ov_end = fmt_dt(c["overlap_end"]) if c["overlap_end"] is not None else "open-ended"
        cat_color = COLOR.get(c["category"], COLOR["muted"])

        def _line(row: pd.Series) -> str:
            av = row["__availCapacity__"]
            un = row["__unavailCapacity__"]
            reason = str(row[reason_col]) if reason_col else ""
            reason = (
                ""
                if reason in ("-", "nan", "None", "")
                else f" — <i>{reason}</i>"
            )
            return (
                f"<div class='remit-line'>"
                f"<b>{_ident(row)}</b> · "
                f"{fmt_dt(row['__eventStart__'])} → "
                f"{fmt_dt(row['__eventEnd__'])} · "
                f"avail <b>{av:g}</b> / unavail <b>{un:g}</b> · "
                f"<span class='remit-line__meta'>{row['__planned__']}"
                f"{reason}</span></div>"
            )

        st.markdown(
            f"<div class='remit-card' style='border-left-color:{cat_color}'>"
            f"<div class='remit-row'>"
            f"{type_pill(c['site'], c['category'])}"
            f"<span>{' '.join(tags)}</span></div>"
            f"<div class='remit-card__sub'>"
            f"Overlap: {fmt_dt(c['overlap_start'])} → {ov_end}</div>"
            f"{_line(a)}{_line(b)}"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_site_timeline(
    site: str,
    df_op: pd.DataFrame,
    horizon_days: int,
    categories: list[str],
) -> None:
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(days=7)
    end = now + pd.Timedelta(days=horizon_days)

    # Storage is excluded from the timeline: it is in TWh while
    # Withdrawal/Injection are in GWh/d, so a shared y-axis would flatten
    # it. Storage availability is still shown in the headline cards.
    categories = [c for c in categories if c != "Storage"]
    if not categories:
        st.info("No Withdrawal/Injection categories to plot.")
        return

    tech_lookup = tech_capacity_lookup(df_op, categories)
    series = compute_capacity_series(df_op, start, end, tech_lookup, categories)
    site_series = series[series["site"] == site] if not series.empty else series
    if site_series.empty:
        st.info(f"No capacity data for {site}.")
        return

    # Lock y-axis: 0 → highest technical capacity for this site + 10%
    site_techs = [
        tech_lookup[(site, c)] for c in categories if (site, c) in tech_lookup
    ]
    y_max = max(site_techs) * 1.1 if site_techs else None

    fig = go.Figure()

    for cat in categories:
        cs = site_series[site_series["category"] == cat].sort_values("date")
        if cs.empty:
            continue
        unit = DEFAULT_UNIT.get(cat, "")
        fig.add_trace(
            go.Scatter(
                x=cs["date"],
                y=cs["available"],
                mode="lines",
                name=f"{cat} available",
                line=dict(
                    color=COLOR[cat],
                    width=2.5,
                    shape="hv",  # exact step function
                    dash="dot" if cat == "Storage" else "solid",
                ),
                hovertemplate=(
                    f"%{{x|%d %b %Y %H:%M}}<br>{cat}: "
                    f"%{{y:.2f}} {unit}<extra></extra>"
                ),
            )
        )
        tech = tech_lookup.get((site, cat))
        if tech is not None:
            fig.add_trace(
                go.Scatter(
                    x=cs["date"],
                    y=[tech] * len(cs),
                    mode="lines",
                    name=f"{cat} technical max",
                    line=dict(color=COLOR[cat], width=1.5, dash="longdash"),
                    opacity=0.75,
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

    # Technical-max labels, vertically de-conflicted so close values
    # (e.g. Aldbrough W 287.78 / I 293.33) stay individually readable.
    tech_items = [
        (cat, tech_lookup[(site, cat)], DEFAULT_UNIT.get(cat, ""))
        for cat in categories
        if (site, cat) in tech_lookup
    ]
    tech_items.sort(key=lambda x: x[1])  # ascending by value
    min_sep = (y_max * 0.075) if y_max else 0.0
    label_ys: list[float] = []
    for _, tech, _ in tech_items:
        ly = tech
        if label_ys and ly < label_ys[-1] + min_sep:
            ly = label_ys[-1] + min_sep
        label_ys.append(ly)
    for (cat, tech, unit), ly in zip(tech_items, label_ys):
        if abs(ly - tech) > 1e-6:
            # dotted leader connecting the offset box to the actual line
            fig.add_shape(
                type="line",
                xref="paper",
                yref="y",
                x0=1.0,
                x1=1.0,
                y0=tech,
                y1=ly,
                line=dict(color=COLOR[cat], width=1, dash="dot"),
            )
        fig.add_annotation(
            x=1.0,
            xref="paper",
            y=ly,
            yref="y",
            text=f"{cat} max {tech:g} {unit}",
            showarrow=False,
            xanchor="left",
            xshift=8,
            font=dict(size=10, color=COLOR[cat]),
            bgcolor="rgba(255,255,255,0.95)",
            bordercolor=COLOR[cat],
            borderwidth=1,
            borderpad=2,
        )

    _add_now_line(fig, now)
    fig.update_xaxes(tickformat="%d %b\n%H:%M")
    fig.update_layout(
        title=f"{site_label(site)} — available capacity",
        height=320,
        margin=dict(l=20, r=130, t=40, b=20),
        legend=dict(orientation="h", y=-0.25),
        yaxis=dict(
            title="Available",
            range=[0, y_max] if y_max is not None else None,
        ),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_gantt(df_op: pd.DataFrame, horizon_days: int) -> None:
    now = pd.Timestamp.now(tz="UTC")
    # Calendar window: at most 1 month back, horizon days forward.
    start = now - pd.Timedelta(days=30)
    end = now + pd.Timedelta(days=horizon_days)

    sub = df_op.dropna(subset=["__eventStart__"]).copy()
    # Treat open-ended events as running to the window edge for display
    sub["__endFill__"] = sub["__eventEnd__"].fillna(end)
    mask = (sub["__endFill__"] >= start) & (sub["__eventStart__"] <= end)
    sub = sub[mask]
    if sub.empty:
        st.info("No events with valid dates in this window.")
        return

    sub["row"] = sub["__site__"].map(site_label) + " — " + sub["__category__"]

    # Clip bar display to the window so multi-year REMITs don't blow out the
    # axis — hover still reports the true start/end/duration.
    sub["__displayStart__"] = sub["__eventStart__"].clip(lower=start)
    sub["__displayEnd__"] = sub["__endFill__"].clip(upper=end)

    # Minimum visual width so a couple-hour outage is still a visible block.
    min_visual = pd.Timedelta(hours=6)
    disp_dur = sub["__displayEnd__"] - sub["__displayStart__"]
    short = disp_dur < min_visual
    sub.loc[short, "__displayEnd__"] = (
        sub.loc[short, "__displayStart__"] + min_visual
    )

    true_dur = sub["__endFill__"] - sub["__eventStart__"]
    sub["Start"] = sub["__eventStart__"].dt.strftime("%d %b %Y %H:%M")
    sub["End"] = sub["__eventEnd__"].dt.strftime("%d %b %Y %H:%M")
    sub["End"] = sub["End"].fillna("open-ended")
    sub["Hours"] = (true_dur.dt.total_seconds() / 3600).round(1)
    sub["Unavailable"] = sub["__unavailCapacity__"]

    fig = px.timeline(
        sub,
        x_start="__displayStart__",
        x_end="__displayEnd__",
        y="row",
        color="__planned__",
        color_discrete_map={
            "Planned": COLOR["Planned"],
            "Unplanned": COLOR["Unplanned"],
            "Unknown": COLOR["muted"],
        },
        hover_name="row",
        hover_data={
            "__planned__": True,
            "Start": True,
            "End": True,
            "Hours": True,
            "Unavailable": True,
            "__displayStart__": False,
            "__displayEnd__": False,
            "row": False,
        },
        labels={"__planned__": "Type"},
    )
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(
        range=[start, end],
        rangeslider=dict(visible=True, thickness=0.06),
        tickformat="%d %b\n%H:%M",
    )
    _add_now_line(fig, now)
    fig.update_layout(
        height=460,
        margin=dict(l=20, r=20, t=20, b=40),
        legend=dict(orientation="h", y=-0.35, title=""),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Window: 1 month back to the selected horizon. Bars are clipped to "
        "this window and widened to a 6 h minimum for visibility — hover "
        "shows the true start, end and duration."
    )


def render_all_data(
    df_all: pd.DataFrame,
    df_history: pd.DataFrame | None,
    cmap: dict[str, str | None],
) -> None:
    sites = st.multiselect("Site", SITES, default=SITES)
    cats = st.multiselect("Category", CATEGORIES, default=CATEGORIES)
    show_dismissed = st.checkbox("Include Dismissed", value=False)

    df = df_all if df_history is None else df_history
    if not show_dismissed:
        df = df[~df["__status__"].str.contains("dismiss", case=False, na=False)]
    df = df[df["__site__"].isin(sites) & df["__category__"].isin(cats)]
    df = df.sort_values("__eventStart__", ascending=False)

    # Pick display columns based on what was detected
    display_cols: list[str] = []
    label_map: dict[str, str] = {}
    for label, key in [
        ("Thread", "threadId"),
        ("Rev", "revisionNumber"),
        ("Site", "__site__"),
        ("Category", "__category__"),
        ("Planned", "__planned__"),
        ("Status", "__status__"),
        ("Start", "__eventStart__"),
        ("End", "__eventEnd__"),
        ("Published", "__publication__"),
        ("Unavail", "__unavailCapacity__"),
        ("Avail", "__availCapacity__"),
        ("Tech", "__techCapacity__"),
        ("Unit", "unit"),
        ("Reason", "reason"),
        ("Remarks", "remarks"),
    ]:
        actual = cmap.get(key, key) if not key.startswith("__") else key
        if actual and actual in df.columns:
            display_cols.append(actual)
            label_map[actual] = label

    st.dataframe(
        df[display_cols].rename(columns=label_map),
        use_container_width=True,
        height=480,
        hide_index=True,
    )
    st.caption(f"{len(df)} rows")


def render_revisions(
    df_history: pd.DataFrame, cmap: dict[str, str | None]
) -> None:
    thread_col = cmap.get("threadId")
    if not thread_col:
        st.info("Thread ID column not detected; revisions view unavailable.")
        return
    threads = sorted(df_history[thread_col].dropna().astype(str).unique())
    if not threads:
        st.info("No threads found.")
        return
    pick = st.selectbox("Pick a thread", threads)
    sub = df_history[df_history[thread_col].astype(str) == pick].copy()
    rev_col = cmap.get("revisionNumber")
    if rev_col and rev_col in sub.columns:
        sub = sub.sort_values(rev_col)
    cols = [c for c in [
        rev_col, "__status__", "__planned__", "__eventStart__", "__eventEnd__",
        "__unavailCapacity__", "__availCapacity__",
        cmap.get("reason"), cmap.get("remarks"), "__publication__",
    ] if c and c in sub.columns]
    st.dataframe(sub[cols], use_container_width=True, hide_index=True)


HORIZON_PRESETS = {"7d": 7, "14d": 14, "30d": 30, "60d": 60, "90d": 90}


def _use_preset_horizon() -> None:
    st.session_state["horizon_mode"] = "preset"


def _use_custom_horizon() -> None:
    # Entering a custom value switches to custom mode and clears the preset
    # selection so the pills don't look active alongside it.
    st.session_state["horizon_mode"] = "custom"
    st.session_state["horizon_preset"] = None


def render_horizon_selector() -> int:
    """Preset horizon pills + a one-click 'Custom' popover (validated 1–730
    days). Selection persists across reruns via widget keys + a mode flag, so
    the 5-minute auto-refresh doesn't reset it. The number_input natively
    prevents non-integer / out-of-range entries.
    """
    if "horizon_preset" not in st.session_state:
        st.session_state["horizon_preset"] = "30d"
    if "horizon_custom" not in st.session_state:
        st.session_state["horizon_custom"] = 30
    if "horizon_mode" not in st.session_state:
        st.session_state["horizon_mode"] = "preset"

    col_pills, col_custom = st.columns([5, 1.1])
    with col_pills:
        st.segmented_control(
            "Horizon",
            list(HORIZON_PRESETS.keys()),
            key="horizon_preset",
            on_change=_use_preset_horizon,
            label_visibility="collapsed",
        )
    with col_custom:
        with st.popover("Custom", use_container_width=True):
            st.number_input(
                "Number of days",
                min_value=1,
                max_value=730,
                step=1,
                key="horizon_custom",
                on_change=_use_custom_horizon,
                help="Whole number of days, 1 to 730 (max 2 years).",
            )
            st.caption("Integer between 1 and 730 days (≤ 2 years).")

    if st.session_state["horizon_mode"] == "custom":
        return int(st.session_state["horizon_custom"])
    preset = st.session_state.get("horizon_preset") or "30d"
    return HORIZON_PRESETS[preset]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

head_l, head_r = st.columns([6, 1], vertical_alignment="center")
with head_l:
    st.markdown(
        "<div class='remit-masthead'>"
        "<div class='remit-devbar'>&#9679; DEV ENVIRONMENT &#9679;</div>"
        "<div class='remit-header__title'>REMIT &mdash; SSE Hornsea gas storage</div>"
        "<div class='remit-header__sub'>Aldbrough &amp; Hornsea &middot; live "
        "REMIT / UoF data from "
        "<a href='https://thermaloutages.sse.com/gas-uof'>thermaloutages.sse.com</a>"
        "</div></div>",
        unsafe_allow_html=True,
    )
with head_r:
    if st.button("⟳ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Storage REMITs are always included (three wheels: Withdrawal / Injection /
# Storage). Storage is still excluded from the GWh/d capacity timeline inside
# render_site_timeline because it is measured in TWh, not flow.
ACTIVE_CATEGORIES = list(CATEGORIES)

# Load with graceful degradation. The fetch retries through SSE's transient
# WAF 403s, but if a load still fails — or this is a cold start (wake-from-
# sleep) while SSE is briefly unreachable — we must NOT crash. Keep the last
# good snapshot in session_state and render it behind a banner; on a true cold
# start with nothing cached, show a friendly retry state that self-recovers on
# the next 5-min auto-refresh.
_fetch_error: str | None = None
try:
    _fresh = fetch_remit("Latest")
    if _fresh.empty:
        _fetch_error = "API returned no records."
    else:
        st.session_state["last_good_raw"] = _fresh
        st.session_state["last_good_at"] = pd.Timestamp.now(tz="UTC")
except Exception as exc:
    _fetch_error = str(exc)

raw = st.session_state.get("last_good_raw")

if raw is None or raw.empty:
    # Cold start and SSE briefly unreachable — show a clean "connecting" state,
    # never a crash. Auto-refresh (every 5 min) will populate it.
    st.info(
        "⏳ Connecting to the SSE REMIT feed — the dashboard populates "
        "automatically as soon as data arrives, and retries every 5 minutes."
    )
    if _fetch_error:
        with st.expander("Connection detail"):
            st.write(_fetch_error)
    if st.button("Retry now"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

if _fetch_error:
    # We have last-good data but the latest live fetch failed — show it behind
    # a staleness banner rather than hiding the whole dashboard.
    _last_at = st.session_state.get("last_good_at")
    _age = ""
    if _last_at is not None:
        _mins = int((pd.Timestamp.now(tz="UTC") - _last_at).total_seconds() // 60)
        _age = f" from {_mins} min ago" if _mins > 0 else " from moments ago"
    st.warning(
        f"⚠️ Showing last good data{_age} — the live refresh is failing right "
        "now and will retry automatically."
    )
    with st.expander("Live-fetch error detail"):
        st.write(_fetch_error)

cmap = detect_columns(raw)
df = normalise(raw, cmap)

# Detection diagnostics
missing = [k for k, v in cmap.items() if v is None
           and k in ("asset", "eventStart", "eventEnd", "typeOfEvent",
                     "techCapacity", "unavailCapacity")]
if missing:
    st.warning(
        "Some fields could not be detected automatically: "
        + ", ".join(missing)
        + ". Some views may be incomplete. Expand the diagnostics below."
    )
    with st.expander("Field-detection diagnostics"):
        st.write({"detected": cmap, "columns": list(raw.columns)})

# Operational dataset: latest revisions, not dismissed, with known site,
# and (optionally) excluding storage.
df_op = df[
    df["__site__"].isin(SITES)
    & ~df["__status__"].str.contains("dismiss", case=False, na=False)
    & df["__category__"].isin(ACTIVE_CATEGORIES)
].copy()

now = pd.Timestamp.now(tz="UTC")
df_active = active_now(df_op, now)

# Upcoming capacity-change alerts (banner above the hero)
_tech_lookup = tech_capacity_lookup(df_op, ACTIVE_CATEGORIES)
_changes = compute_capacity_changes(df_op, _tech_lookup, ACTIVE_CATEGORIES, lookahead_days=7)
render_changes_banner(_changes, cmap)

# Recent changes — what moved in the last 24 h (uses df, so dismissed
# REMITs are included)
_recent = compute_recent_changes(df, cmap, lookback_hours=24)
render_recent_banner(_recent, cmap, lookback_hours=24)

# Overlapping/conflicting REMITs — computed up front so the capacity
# timelines can shade the affected periods.
_conflicts = detect_conflicts(df_op, ACTIVE_CATEGORIES, cmap)

# Main screen — per site, split horizontally:
#   1. capacity availability cards
#   2. capacity timeline
#   3. active-now cards
st.divider()
section_header("Capacity availability", "Live — latest revision per thread")
hero_l, hero_r = st.columns(2, gap="large")
with hero_l:
    render_site_headline(
        "Aldbrough",
        df_active[df_active["__site__"] == "Aldbrough"],
        df_op[df_op["__site__"] == "Aldbrough"],
        cmap,
        ACTIVE_CATEGORIES,
    )
with hero_r:
    render_site_headline(
        "Atwick",
        df_active[df_active["__site__"] == "Atwick"],
        df_op[df_op["__site__"] == "Atwick"],
        cmap,
        ACTIVE_CATEGORIES,
    )

st.divider()
section_header("Active outages")
act_l, act_r = st.columns(2, gap="large")
with act_l:
    render_site_active(
        "Aldbrough",
        df_active[df_active["__site__"] == "Aldbrough"],
        cmap,
        ACTIVE_CATEGORIES,
    )
with act_r:
    render_site_active(
        "Atwick",
        df_active[df_active["__site__"] == "Atwick"],
        cmap,
        ACTIVE_CATEGORIES,
    )

st.divider()
horizon_days = render_horizon_selector()
df_upcoming = upcoming(df_op, now, horizon_days)
section_header("Capacity timeline", f"Next {horizon_days} days")
tl_l, tl_r = st.columns(2, gap="large")
with tl_l:
    _safe_block(
        "Aldbrough timeline",
        lambda: render_site_timeline("Aldbrough", df_op, horizon_days, ACTIVE_CATEGORIES),
    )
with tl_r:
    _safe_block(
        "Hornsea timeline",
        lambda: render_site_timeline("Atwick", df_op, horizon_days, ACTIVE_CATEGORIES),
    )

st.divider()
section_header("Detail views")

include_history = st.toggle(
    "Include older revisions (All data / Revisions tabs)",
    value=False,
    help="Adds historical revisions to the All data and Revisions tabs only. "
    "Operational views always use the latest revision per thread.",
)

# Tabs
conflict_label = (
    f"Conflicts ({len(_conflicts)})" if _conflicts else "Conflicts"
)
tab_up, tab_gantt, tab_conf, tab_data, tab_rev = st.tabs(
    [
        f"Upcoming ({horizon_days}d)",
        "Outage calendar",
        conflict_label,
        "All data",
        "Revisions",
    ]
)


with tab_up:
    _safe_block("Upcoming", lambda: render_upcoming(df_upcoming, cmap, ACTIVE_CATEGORIES))

with tab_gantt:
    _safe_block("Outage calendar", lambda: render_gantt(df_op, horizon_days))

with tab_conf:
    _safe_block("Conflicts", lambda: render_conflicts(_conflicts, cmap))

history_df: pd.DataFrame | None = None
if include_history:
    try:
        hist_raw = fetch_remit("All")
        if not hist_raw.empty:
            history_df = normalise(hist_raw, detect_columns(hist_raw))
    except Exception as exc:
        st.warning(f"Couldn't fetch historical revisions: {exc}")

with tab_data:
    render_all_data(df, history_df, cmap)

with tab_rev:
    if include_history and history_df is not None:
        render_revisions(history_df, cmap)
    else:
        st.info(
            "Enable “Include older revisions” at the top of the page to browse "
            "the revision history of each REMIT thread."
        )

st.caption(
    f"Data refreshed at {now.strftime('%d %b %Y %H:%M UTC')}. "
    f"Auto-refresh every 5 min — use ⟳ Refresh to force reload."
)
