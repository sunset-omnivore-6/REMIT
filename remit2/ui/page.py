"""Page composition. The main body is a fragment that re-runs every 5 min
(paused while a dialog is open) so the 5-min data cache is refreshed in place."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from ..core.capacity import compute_capacity_changes, compute_recent_changes, short_thread
from ..core.constants import site_label
from ..core.operational import tech_capacity_lookup
from ..core.timeutil import fmt_local
from . import data as d
from . import theme
from .controls import render_controls
from .hero import render_panel_card

TITLE = "REMIT 2.0 — Hornsea & Aldbrough availability"


def _wall() -> bool:
    return st.query_params.get("mode") == "wall"


def _banner(text: str, level: str = "warn") -> None:
    icon = {"warn": "⚠️", "bad": "⛔", "info": "ℹ️"}[level]
    st.markdown(f"<div class='r2-banner r2-banner--{level}'>{icon} {text}</div>", unsafe_allow_html=True)


def _masthead(fetched_at, source: str) -> None:
    when = f"data fetched {fmt_local(fetched_at)}" if fetched_at is not None else "no data yet"
    src = {"fixture": " · FIXTURE DATA", "session": " · last good copy", "snapshot": " · disk snapshot", "none": ""}.get(source, "")
    st.markdown(
        f"<div class='r2-mast'><h1>{TITLE}</h1><span class='sub'>Available capacity by site and direction · "
        f"published REMITs + ad-hoc adjustments · {when}{src} · times Europe/London</span></div>",
        unsafe_allow_html=True,
    )


@st.dialog("New ad-hoc adjustment")
def _new_adhoc_dialog() -> None:
    st.info("The ad-hoc register is being connected (next milestone). The form will go here: "
            "Site → Direction → Units or Rate change → When → Notes → Save.")
    if st.button("Close"):
        st.rerun()


def _register_strip(register, now) -> None:
    n_active = sum(1 for r in register.records if r.status(now) == "active")
    n_planned = sum(1 for r in register.records if r.status(now) == "planned")
    left, right = st.columns([5, 1.2], vertical_alignment="center")
    with left:
        st.markdown(
            "<div class='r2-strip'><b>Ad-hoc adjustments</b>"
            f"<span class='stat'>Active {n_active}</span><span class='stat'>Planned {n_planned}</span>"
            "<span style='color:#475569'>None recorded yet.</span></div>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button("＋ New ad-hoc", type="primary", width="stretch"):
            _new_adhoc_dialog()


def _recent_and_upcoming(data: d.RemitData, now: pd.Timestamp, horizon: int) -> None:
    cats = ["Withdrawal", "Injection"]
    with st.expander("Recent REMIT changes (last 24 h)", expanded=False):
        items = compute_recent_changes(data.df, data.cmap, lookback_hours=24, now=now)
        if not items:
            st.markdown("<div class='r2-row'>No REMIT changes in the last 24 hours.</div>", unsafe_allow_html=True)
        for it in items:
            row = it["row"]
            thread = row[data.cmap["threadId"]] if data.cmap.get("threadId") else ""
            st.markdown(
                f"<div class='r2-row'><span class='k'>{it['kind']}</span>"
                f"<span>{site_label(it['site'])} · {it['category']}</span>"
                f"<span class='m'>{short_thread(thread)} · rev {it['rev_num']} · published {fmt_local(it['publication'])}</span>"
                f"<span class='m'>{fmt_local(row['__eventStart__'])} → {fmt_local(row['__eventEnd__'])}</span></div>",
                unsafe_allow_html=True,
            )
    with st.expander(f"Upcoming REMIT capacity changes (next {min(horizon, 30)} d)", expanded=False):
        tech = tech_capacity_lookup(data.df_op, cats)
        changes = compute_capacity_changes(data.df_op, tech, cats, lookahead_days=min(horizon, 30), now=now)
        if not changes:
            st.markdown("<div class='r2-row'>No published capacity changes ahead.</div>", unsafe_allow_html=True)
        for c in changes:
            glyph = "▼" if c["to"] < c["from"] else "▲"
            st.markdown(
                f"<div class='r2-row'><span class='k'>{glyph} {site_label(c['site'])} · {c['category']}</span>"
                f"<span>{c['from']:.1f} → <b>{c['to']:.1f}</b> GWh/d</span><span class='m'>{fmt_local(c['when'])}</span></div>",
                unsafe_allow_html=True,
            )


def _body() -> None:
    wall = _wall()
    controls = render_controls(wall)
    if controls.refresh:
        st.cache_data.clear()
        st.rerun()
    data = d.load_remit()
    now = pd.Timestamp.now(tz="UTC")
    _masthead(data.fetched_at, data.source)
    if data.source == "none":
        _banner("Connecting to the SSE REMIT feed — the page fills in automatically once data arrives (retries every 5 minutes).", "info")
        if data.error:
            with st.expander("Connection detail"):
                st.write(data.error)
        return
    if data.error:
        _banner(f"Live refresh failing — showing the last good data fetched {fmt_local(data.fetched_at)}. Retrying automatically.", "warn")
        with st.expander("Connection detail"):
            st.write(data.error)
    if "__unitUnknown__" in data.df.columns and bool(data.df["__unitUnknown__"].any()):
        _banner("Some REMIT rows use an unrecognised unit of measurement and are shown unconverted.", "warn")

    equipment = d.get_equipment()
    register, version = d.get_register()
    if not wall:
        _register_strip(register, now)
    panels = d.compute_panels(data, register, version, controls.horizon_days, now)

    for site in ("Atwick", "Aldbrough"):
        cols = st.columns(2, gap="large")
        for col, direction in zip(cols, ("Withdrawal", "Injection")):
            with col:
                render_panel_card(panels[(site, direction)], equipment, controls, wall)
    if not wall:
        st.markdown("<div class='r2-sec'>On demand</div>", unsafe_allow_html=True)
        _recent_and_upcoming(data, now, controls.horizon_days)
    st.markdown(
        f"<p class='r2-foot'>Cause lanes: {theme.chip('Planned REMIT', theme.PLANNED)} {theme.chip('Unplanned REMIT', theme.UNPLANNED)} "
        f"{theme.chip('Ad-hoc', theme.ADHOC)} — each lane is hatched as well as coloured. "
        f"Auto-refresh every 5 min.</p>", unsafe_allow_html=True)


def render() -> None:
    theme.inject_css(_wall())
    if st.session_state.get("r2_dialog_open"):
        _body()
    else:
        st.fragment(run_every=timedelta(minutes=5))(_body)()
