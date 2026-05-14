from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = "https://thermaloutages.sse.com/api/v1/outages/gasuof"
SITES = ["Aldbrough", "Atwick"]
CATEGORIES = ["Withdrawal", "Injection", "Storage"]
PAGE_SIZE = 100
FAR_FUTURE = pd.Timestamp("2099-01-01", tz="UTC")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://thermaloutages.sse.com/gas-uof",
}

# Nameplate technical capacities — used as a fallback when no current REMIT
# carries a technicalCapacity figure for a given (site, category). Values
# from SSE's published facility data.
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

COLOR = {
    "ok": "#16a34a",
    "warn": "#f59e0b",
    "bad": "#dc2626",
    "info": "#2563eb",
    "muted": "#9ca3af",
    "Withdrawal": "#dc2626",
    "Injection": "#2563eb",
    "Storage": "#9ca3af",
    "Planned": "#2563eb",
    "Unplanned": "#dc2626",
}

st.set_page_config(
    page_title="REMIT — Aldbrough & Atwick",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="Fetching REMIT data…")
def fetch_remit(revisions: str = "Latest") -> pd.DataFrame:
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "pageNumber": page,
            "pageSize": PAGE_SIZE,
            "sortDirection": "DESC",
            "sortBy": "PublicationDateTime",
            "revisionsReturned": revisions,
            "outageDateMatch": "CONTAINED",
        }
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

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

        if not items:
            break
        rows.extend(items)

        if total is not None and len(rows) >= total:
            break
        if len(items) < PAGE_SIZE:
            break
        page += 1
        if page > 200:
            break

    return pd.json_normalize(rows)


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
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.78em;font-weight:600;"
        f"white-space:nowrap'>{text}</span>"
    )


def progress_bar(pct: float, color: str) -> str:
    pct = max(0.0, min(100.0, pct))
    return (
        f"<div style='background:#e5e7eb;border-radius:6px;height:10px;width:100%'>"
        f"<div style='background:{color};width:{pct:.1f}%;height:100%;border-radius:6px'></div>"
        f"</div>"
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
      1. max from currently-active events for this (site, cat)
      2. max from any (latest-revision) event for this (site, cat)
      3. hard-coded nameplate fallback (TECH_CAPACITY_FALLBACK)
    """
    sub = df_active[
        (df_active["__site__"] == site) & (df_active["__category__"] == category)
    ]
    tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
    if pd.isna(tech):
        all_sub = df_all_site[df_all_site["__category__"] == category]
        tech = all_sub["__techCapacity__"].dropna().max() if not all_sub.empty else float("nan")
    if pd.isna(tech):
        tech = TECH_CAPACITY_FALLBACK.get((site, category), float("nan"))

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
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
            if pd.notna(tech) and tech > 0:
                out[(site, cat)] = float(tech)
            elif (site, cat) in TECH_CAPACITY_FALLBACK:
                out[(site, cat)] = TECH_CAPACITY_FALLBACK[(site, cat)]
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
    if not changes:
        return

    now = pd.Timestamp.now(tz="UTC")
    drops = sum(1 for c in changes if c["to"] < c["from"])
    rises = sum(1 for c in changes if c["to"] > c["from"])

    border = COLOR["bad"] if drops else COLOR["info"]
    bg = "#fef2f2" if drops else "#eff6ff"
    summary = []
    if drops:
        summary.append(f"<span style='color:{COLOR['bad']};font-weight:600'>{drops} capacity drop{'s' if drops != 1 else ''}</span>")
    if rises:
        summary.append(f"<span style='color:{COLOR['ok']};font-weight:600'>{rises} restoration{'s' if rises != 1 else ''}</span>")

    st.markdown(
        f"<div style='background:{bg};border-left:5px solid {border};"
        f"padding:10px 14px;margin-bottom:10px;border-radius:4px'>"
        f"<b>Upcoming capacity changes (next 7 days)</b> · " + " · ".join(summary)
        + "</div>",
        unsafe_allow_html=True,
    )

    with st.expander(f"Show {len(changes)} change{'s' if len(changes) != 1 else ''}", expanded=True):
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
            cat_color = COLOR.get(cat, COLOR["muted"])
            plan_color = COLOR.get(planned, COLOR["muted"])
            planned_pill = pill(planned, plan_color) if planned else ""
            reason_html = (
                f"<div style='font-size:0.85em;color:#6b7280;margin-top:2px'>"
                f"<i>{reason}</i></div>"
                if reason and reason not in ("-", "nan", "None")
                else ""
            )

            st.markdown(
                f"<div style='border-left:4px solid {arrow_color};"
                f"padding:8px 12px;margin:6px 0;background:#f9fafb;border-radius:4px'>"
                f"<div style='display:flex;justify-content:space-between;gap:6px;align-items:baseline'>"
                f"<div><b><span style='color:{cat_color}'>●</span> {site} {cat}</b> "
                f"{planned_pill}</div>"
                f"<div style='font-size:0.85em;color:#374151'>{when_str}</div>"
                f"</div>"
                f"<div style='font-size:1.15em;margin-top:4px'>"
                f"<b style='color:#374151'>{c['from']:g} {unit}</b> "
                f"<span style='color:{arrow_color};font-weight:700'>{arrow}</span> "
                f"<b style='color:{arrow_color}'>{c['to']:g} {unit}</b> "
                f"<span style='color:#6b7280'>(tech max {c['tech']:g})</span>"
                f"</div>"
                f"{reason_html}"
                f"</div>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Rendering — hero cards
# ---------------------------------------------------------------------------

def render_event_card(row: pd.Series, cmap: dict[str, str | None]) -> str:
    cat = row["__category__"] or "—"
    planned = row["__planned__"]
    planned_color = COLOR.get(planned, COLOR["muted"])
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

    return (
        f"<div style='border-left:4px solid {cat_color};padding:8px 12px;"
        f"margin:6px 0;background:#f9fafb;border-radius:4px'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;gap:6px'>"
        f"<div>{pill(cat, cat_color)} {pill(planned, planned_color)}</div>"
        f"<div style='font-size:0.78em;color:#6b7280'>Thread {thread} · rev {rev}</div>"
        f"</div>"
        f"<div style='margin-top:6px;font-size:0.92em'>"
        f"<b>{unavail:g} {unit}</b> unavailable "
        f"({pct_unavail:.0f}% of {tech:g}) · "
        f"available {avail:g} {unit}</div>"
        f"<div style='font-size:0.85em;color:#374151;margin-top:4px'>"
        f"{fmt_dt(row['__eventStart__'])} → {fmt_dt(row['__eventEnd__'])}</div>"
        f"<div style='font-size:0.85em;color:#374151;margin-top:4px'>"
        f"<i>{reason}</i>{(' — ' + str(remarks)) if remarks and str(remarks) not in ('-', 'nan', 'None', '') else ''}</div>"
        f"</div>"
    )


def render_site_column(
    site: str,
    df_active_site: pd.DataFrame,
    df_all_site_future: pd.DataFrame,
    cmap: dict[str, str | None],
    categories: list[str],
) -> None:
    st.markdown(f"### {site}")

    # Headline cards
    for cat in categories:
        tech, avail, unavail, has_unplanned, n = site_category_headline(
            df_active_site, df_all_site_future, site, cat
        )
        if pd.notna(tech) and tech > 0:
            if pd.isna(avail):
                avail = tech  # nothing active → fully available
            pct = (avail / tech) * 100
        else:
            pct = float("nan")

        color = headline_color(pct if pd.notna(pct) else 100, has_unplanned, cat)
        cat_color = COLOR.get(cat, COLOR["muted"])

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

        with st.container():
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:baseline;margin-top:4px'>"
                f"<div style='font-weight:600'>"
                f"<span style='color:{cat_color}'>●</span> {cat}</div>"
                f"<div style='font-size:0.85em;color:#6b7280'>"
                f"{n} active event{'s' if n != 1 else ''}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if pd.notna(pct):
                avail_str = f"{avail:g}" if pd.notna(avail) else "—"
                tech_str = f"{tech:g}" if pd.notna(tech) else "—"
                st.markdown(
                    f"<div style='font-size:1.4em;font-weight:700;color:{color}'>"
                    f"{pct:.0f}% available</div>"
                    f"<div style='font-size:0.85em;color:#374151'>"
                    f"{avail_str} of {tech_str} {unit_str}</div>"
                    f"{progress_bar(pct, color)}",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='color:#6b7280;font-style:italic'>no capacity reference</div>",
                    unsafe_allow_html=True,
                )

    st.markdown("---")
    st.markdown("**Active now**")

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
            f"<div style='color:{COLOR['ok']};font-weight:600'>"
            f"All capacity available — no active outages.</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tabs: upcoming, timeline, gantt, all data
# ---------------------------------------------------------------------------

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
        header_style = (
            "color:#6b7280;font-size:1.0em" if muted else "font-size:1.1em;font-weight:700"
        )
        st.markdown(
            f"<div style='{header_style};margin-top:8px'>{cat} — {len(sub)}</div>",
            unsafe_allow_html=True,
        )
        for _, row in sub.iterrows():
            opacity = "0.7" if muted else "1.0"
            site = row["__site__"]
            unit = row[cmap["unit"]] if cmap["unit"] else ""
            unavail = row["__unavailCapacity__"]
            reason = row[cmap["reason"]] if cmap["reason"] else ""
            st.markdown(
                f"<div style='opacity:{opacity};padding:4px 8px;"
                f"border-left:3px solid {COLOR.get(cat, COLOR['muted'])};margin:3px 0;"
                f"background:#f9fafb'>"
                f"<b>{site}</b> · "
                f"{fmt_dt(row['__eventStart__'])} → {fmt_dt(row['__eventEnd__'])} · "
                f"<b>{unavail:g} {unit}</b> unavailable · "
                f"{pill(row['__planned__'], COLOR.get(row['__planned__'], COLOR['muted']))} "
                f"<span style='color:#6b7280'>{reason}</span>"
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
        f"<div style='background:#fffbeb;border-left:5px solid {COLOR['warn']};"
        f"padding:10px 14px;margin-bottom:10px;border-radius:4px'>"
        f"<b>{len(conflicts)} overlapping REMIT pair"
        f"{'s' if len(conflicts) != 1 else ''}</b> active for the same period "
        f"with differing availability or end time — review for data-quality "
        f"issues or competing notices.</div>",
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
            reason = "" if reason in ("-", "nan", "None", "") else f" — <i>{reason}</i>"
            return (
                f"<div style='font-size:0.88em;margin:2px 0'>"
                f"<b>{_ident(row)}</b> · "
                f"{fmt_dt(row['__eventStart__'])} → {fmt_dt(row['__eventEnd__'])} · "
                f"avail <b>{av:g}</b> / unavail <b>{un:g}</b> · "
                f"{row['__planned__']}{reason}</div>"
            )

        st.markdown(
            f"<div style='border-left:4px solid {cat_color};padding:8px 12px;"
            f"margin:6px 0;background:#f9fafb;border-radius:4px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<b><span style='color:{cat_color}'>●</span> {c['site']} {c['category']}</b>"
            f"<span>{' '.join(tags)}</span></div>"
            f"<div style='font-size:0.82em;color:#6b7280;margin:3px 0'>"
            f"Overlap: {fmt_dt(c['overlap_start'])} → {ov_end}</div>"
            f"{_line(a)}{_line(b)}"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_timeline(
    df_op: pd.DataFrame, horizon_days: int, categories: list[str]
) -> None:
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(days=7)
    end = now + pd.Timedelta(days=horizon_days)

    tech_lookup = tech_capacity_lookup(df_op, categories)
    series = compute_capacity_series(df_op, start, end, tech_lookup, categories)
    if series.empty:
        st.info("Not enough data to plot capacity timeline.")
        return

    for site in SITES:
        site_series = series[series["site"] == site]
        if site_series.empty:
            continue
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
                        width=2,
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
                        name=f"{cat} technical",
                        line=dict(color=COLOR[cat], width=1, dash="dash"),
                        opacity=0.3,
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )
        _add_now_line(fig, now)
        fig.update_xaxes(
            rangeslider=dict(visible=True, thickness=0.06),
            tickformat="%d %b\n%H:%M",
        )
        fig.update_layout(
            title=f"{site} — available capacity (step = exact event boundaries)",
            height=340,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", y=-0.32),
            yaxis_title="Available",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)


def render_gantt(df_op: pd.DataFrame, horizon_days: int) -> None:
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(days=7)
    end = now + pd.Timedelta(days=horizon_days)

    sub = df_op.dropna(subset=["__eventStart__"]).copy()
    # Treat open-ended events as running to the window edge for display
    sub["__endFill__"] = sub["__eventEnd__"].fillna(end)
    mask = (sub["__endFill__"] >= start) & (sub["__eventStart__"] <= end)
    sub = sub[mask]
    if sub.empty:
        st.info("No events with valid dates in this window.")
        return

    sub["row"] = sub["__site__"] + " — " + sub["__category__"]

    # Minimum visual width so a couple-hour outage is still a visible block.
    # Hover always shows the true start/end/duration.
    min_visual = pd.Timedelta(hours=6)
    dur = sub["__endFill__"] - sub["__eventStart__"]
    sub["__displayEnd__"] = sub["__endFill__"]
    short = dur < min_visual
    sub.loc[short, "__displayEnd__"] = sub.loc[short, "__eventStart__"] + min_visual

    sub["Start"] = sub["__eventStart__"].dt.strftime("%d %b %Y %H:%M")
    sub["End"] = sub["__eventEnd__"].dt.strftime("%d %b %Y %H:%M")
    sub["End"] = sub["End"].fillna("open-ended")
    sub["Hours"] = (dur.dt.total_seconds() / 3600).round(1)
    sub["Unavailable"] = sub["__unavailCapacity__"]

    fig = px.timeline(
        sub,
        x_start="__eventStart__",
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
            "__eventStart__": False,
            "__displayEnd__": False,
            "row": False,
        },
        labels={"__planned__": "Type"},
    )
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_xaxes(
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
        "Bars shorter than 6 h are widened for visibility — hover shows true "
        "start, end and duration. Drag the slider below the chart to zoom."
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
    st.dataframe(sub[cols], use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.markdown(
    "<h2 style='margin-bottom:0'>REMIT — SSE Hornsea gas storage</h2>"
    "<div style='color:#6b7280;margin-bottom:12px'>Aldbrough &amp; Atwick — "
    "live REMIT/UoF data from "
    "<a href='https://thermaloutages.sse.com/gas-uof'>thermaloutages.sse.com</a></div>",
    unsafe_allow_html=True,
)

ctrl_l, ctrl_m, ctrl_s, ctrl_r = st.columns([2, 2, 1.4, 0.8])
with ctrl_l:
    horizon_days = st.slider("Upcoming horizon (days)", 7, 90, 30, step=1)
with ctrl_m:
    include_history = st.toggle(
        "Include older revisions (All data / Revisions tabs)",
        value=False,
        help="Adds historical revisions to the All data and Revisions tabs only. "
        "Operational views always use the latest revision per thread.",
    )
with ctrl_s:
    include_storage = st.toggle(
        "Include storage REMITs",
        value=False,
        help="Storage events are typically less operationally critical than "
        "Withdrawal/Injection. Off by default to reduce noise.",
    )
with ctrl_r:
    if st.button("⟳ Refresh"):
        st.cache_data.clear()
        st.rerun()

ACTIVE_CATEGORIES = [
    c for c in CATEGORIES if include_storage or c != "Storage"
]

try:
    raw = fetch_remit("Latest")
except Exception as exc:
    st.error(f"Failed to fetch API: {exc}")
    st.stop()

if raw.empty:
    st.warning("API returned no records.")
    st.stop()

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
df_upcoming = upcoming(df_op, now, horizon_days)

# Upcoming capacity-change alerts (banner above the hero)
_tech_lookup = tech_capacity_lookup(df_op, ACTIVE_CATEGORIES)
_changes = compute_capacity_changes(df_op, _tech_lookup, ACTIVE_CATEGORIES, lookahead_days=7)
render_changes_banner(_changes, cmap)

# Hero
hero_l, hero_r = st.columns(2, gap="large")
with hero_l:
    render_site_column(
        "Aldbrough",
        df_active[df_active["__site__"] == "Aldbrough"],
        df_op[df_op["__site__"] == "Aldbrough"],
        cmap,
        ACTIVE_CATEGORIES,
    )
with hero_r:
    render_site_column(
        "Atwick",
        df_active[df_active["__site__"] == "Atwick"],
        df_op[df_op["__site__"] == "Atwick"],
        cmap,
        ACTIVE_CATEGORIES,
    )

st.markdown("---")

# Tabs
_conflicts = detect_conflicts(df_op, ACTIVE_CATEGORIES, cmap)
conflict_label = (
    f"Conflicts ({len(_conflicts)})" if _conflicts else "Conflicts"
)
tab_up, tab_tl, tab_gantt, tab_conf, tab_data, tab_rev = st.tabs(
    [
        f"Upcoming ({horizon_days}d)",
        "Capacity timeline",
        "Outage calendar",
        conflict_label,
        "All data",
        "Revisions",
    ]
)


def _safe(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # surface the real error instead of a blank tab
        st.error(f"{label} failed to render: {exc}")
        st.exception(exc)


with tab_up:
    _safe("Upcoming", lambda: render_upcoming(df_upcoming, cmap, ACTIVE_CATEGORIES))

with tab_tl:
    _safe("Capacity timeline", lambda: render_timeline(df_op, horizon_days, ACTIVE_CATEGORIES))

with tab_gantt:
    _safe("Outage calendar", lambda: render_gantt(df_op, horizon_days))

with tab_conf:
    _safe("Conflicts", lambda: render_conflicts(_conflicts, cmap))

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
    f"Cache TTL 5 min — use ⟳ Refresh to force reload."
)
