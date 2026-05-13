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
    ("Aldbrough", "Withdrawal"): 342.3,   # GWh/d
    ("Aldbrough", "Injection"): 311.56,   # GWh/d
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
    """For each day, each (site, cat), compute available capacity."""
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
    records = []
    for site in SITES:
        for cat in categories:
            tech = tech_lookup.get((site, cat))
            if tech is None:
                continue
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            for day in days:
                active = sub[
                    (sub["__eventStart__"] <= day)
                    & (
                        sub["__eventEnd__"].isna()
                        | (sub["__eventEnd__"] >= day)
                    )
                ]
                if active.empty:
                    avail = tech
                else:
                    # conservative: smallest reported availability across active events
                    a = active["__availCapacity__"].dropna()
                    avail = float(a.min()) if not a.empty else max(
                        tech - float(active["__unavailCapacity__"].fillna(0).sum()),
                        0.0,
                    )
                records.append(
                    {
                        "date": day,
                        "site": site,
                        "category": cat,
                        "available": avail,
                        "technical": tech,
                    }
                )
    return pd.DataFrame(records)


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
            cs = site_series[site_series["category"] == cat]
            if cs.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=cs["date"],
                    y=cs["available"],
                    mode="lines",
                    name=f"{cat} available",
                    line=dict(
                        color=COLOR[cat],
                        width=2,
                        dash="dot" if cat == "Storage" else "solid",
                    ),
                    hovertemplate="%{x|%d %b %Y}: %{y:.2f}<extra></extra>",
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
        fig.update_layout(
            title=f"{site} — available capacity",
            height=320,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", y=-0.2),
            yaxis_title="Available",
        )
        st.plotly_chart(fig, use_container_width=True)


def render_gantt(df_op: pd.DataFrame, horizon_days: int) -> None:
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(days=7)
    end = now + pd.Timedelta(days=horizon_days)
    mask = (df_op["__eventEnd__"] >= start) & (df_op["__eventStart__"] <= end)
    sub = df_op[mask].copy()
    if sub.empty:
        st.info("No events in window.")
        return

    sub["row"] = sub["__site__"] + " — " + sub["__category__"]
    sub["label"] = sub["__planned__"]
    sub = sub.dropna(subset=["__eventStart__", "__eventEnd__"])
    if sub.empty:
        st.info("No events with valid dates in window.")
        return

    fig = px.timeline(
        sub,
        x_start="__eventStart__",
        x_end="__eventEnd__",
        y="row",
        color="__planned__",
        color_discrete_map={
            "Planned": COLOR["Planned"],
            "Unplanned": COLOR["Unplanned"],
            "Unknown": COLOR["muted"],
        },
        hover_data={
            "__site__": True,
            "__category__": True,
            "__unavailCapacity__": True,
            "__eventStart__": "|%d %b %Y %H:%M",
            "__eventEnd__": "|%d %b %Y %H:%M",
            "row": False,
            "__planned__": False,
        },
    )
    fig.update_yaxes(autorange="reversed")
    _add_now_line(fig, now)
    fig.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig, use_container_width=True)


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
tab_up, tab_tl, tab_gantt, tab_data, tab_rev = st.tabs(
    [
        f"Upcoming ({horizon_days}d)",
        "Capacity timeline",
        "Outage calendar",
        "All data",
        "Revisions",
    ]
)

with tab_up:
    render_upcoming(df_upcoming, cmap, ACTIVE_CATEGORIES)

with tab_tl:
    render_timeline(df_op, horizon_days, ACTIVE_CATEGORIES)

with tab_gantt:
    render_gantt(df_op, horizon_days)

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
