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
from . import controls as ctl
from .hero import render_panel_card
from . import forms
from .register_view import render_register

TITLE = "Hornsea &amp; Aldbrough availability"


def _wall() -> bool:
    return st.query_params.get("mode") == "wall"


def _banner(text: str, level: str = "warn") -> None:
    icon = {"warn": "⚠️", "bad": "⛔", "info": "ℹ️"}[level]
    st.markdown(f"<div class='r2-banner r2-banner--{level}'>{icon} {text}</div>", unsafe_allow_html=True)


def _title_line(fetched_at, source: str, days: int) -> bool:
    """Title, then the data time with a small refresh icon beside it. Returns refresh click."""
    tag = {"fixture": "FIXTURE DATA", "session": "LAST GOOD COPY", "snapshot": "DISK SNAPSHOT"}.get(source, "")
    tag_html = f"<span class='tag'>{tag}</span>" if tag else ""
    when = (f"Data <b>{fmt_local(fetched_at)}</b> · refreshes every 5 min · UK times" if fetched_at is not None
            else "Waiting for data")
    st.markdown(
        f"<div class='r2-title'><span class='kicker'>SSE gas storage · REMIT</span><h1>{TITLE}</h1>"
        f"<span class='lede'>Withdrawal and injection capacity at both sites over the next {days} days — "
        f"from published REMIT notices and ad-hoc plant changes.</span></div>", unsafe_allow_html=True)
    with st.container(key="r2fresh"):
        c1, c2 = st.columns([1, 1], gap="small", vertical_alignment="center")
        with c1:
            st.markdown(f"<span class='fresh'>{when}{tag_html}</span>", unsafe_allow_html=True)
        with c2:
            return st.button("", icon=":material/refresh:", type="tertiary", key="r2_refresh",
                             help="Refresh now — fetch the latest REMIT data")


def _toolbar(loaded, equipment, now, actor: str, editor: bool, df_op) -> None:
    """One ruled line: view controls | legend | ad-hoc status + its action."""
    reg = loaded.register
    live = [r for r in reg.records if r.status(now) in ("active", "planned")]
    n_active = sum(1 for r in live if r.status(now) == "active")
    n_planned = len(live) - n_active
    n_review = sum(1 for r in live if r.is_stale(now, equipment.stale_after_days) or r.is_overdue(now))
    store_ok = loaded.status in ("ok", "local")
    store_note = {"ok": "", "local": " · local store", "stale": " · store unreachable, read-only",
                  "snapshot": " · store unreachable, disk copy", "unavailable": " · register unavailable"}[loaded.status]
    last = reg.meta.get("updated_at")
    last_txt = (f"last change {pd.Timestamp(last).tz_convert('Europe/London').strftime('%d %b %H:%M')} · {reg.meta.get('updated_by')}"
                if last else "none recorded yet")
    review = f" · <span class='warn'>{n_review} to review</span>" if n_review else ""
    with st.container(key="r2toolbar"):
        c = st.columns([0.6, 0.85, 0.35, 1.4, 1.2, 3.2, 1.25], gap="small", vertical_alignment="top")
        with c[0]:
            st.markdown("<div class='r2-lbl'>Show next</div>", unsafe_allow_html=True)
        with c[1]:
            ctl.days_input()
        with c[2]:
            st.markdown("<div class='r2-lbl r2-lbl--days'>days</div>", unsafe_allow_html=True)
        with c[3]:
            ctl.show_as_input()
        with c[5]:
            st.markdown(
                f"<div class='r2-adhoc'>Ad-hoc: <span class='n'>{n_active}</span> active · "
                f"<span class='n'>{n_planned}</span> planned{review}"
                f"<span class='sub'>{last_txt}{store_note}</span></div>", unsafe_allow_html=True)
        with c[6]:
            help_ = None if editor else "Only listed editors can add ad-hocs"
            if st.button("＋ New ad-hoc", type="primary", width="stretch", disabled=not (editor and store_ok), help=help_):
                st.session_state["af_reset"] = True
                st.session_state["r2_dialog_open"] = True
                forms.new_adhoc_dialog(equipment, reg, df_op, actor)


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
    data = d.load_remit()
    now = pd.Timestamp.now(tz="UTC")
    controls = ctl.current()
    if _title_line(data.fetched_at, data.source, controls.horizon_days) and not wall:
        st.session_state["r2_dialog_open"] = False
        st.cache_data.clear()
        st.rerun()
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

    equipment = d.get_equipment_live()
    loaded = d.get_register()
    register, version = loaded.register, loaded.version or "none"
    actor = d.get_actor()
    editor = d.is_editor(actor)
    if flash := st.session_state.pop("r2_flash", None):
        st.success(flash)
    if not wall:
        _toolbar(loaded, equipment, now, actor, editor, data.df_op)
        controls = ctl.current()
    st.markdown(theme.key_html(), unsafe_allow_html=True)
    panels = d.compute_panels(data, register, version, controls.horizon_days, now)

    for site in ("Atwick", "Aldbrough"):
        live_adhoc = sum(1 for r in register.records if r.site == site and r.status(now) in ("active", "planned"))
        summary = []
        for direction in ("Withdrawal", "Injection"):
            cur = panels[(site, direction)].segment_at(now)
            if cur is not None:
                summary.append(f"{direction.lower()} <b>{cur.available:.1f}</b> / {panels[(site, direction)].tech:g}")
        extra = f" · {live_adhoc} live ad-hoc" if live_adhoc else ""
        with st.container(key=f"site-{site.lower()}"):          # full-bleed tinted band per site
            st.markdown(f"<div class='r2-site'><h2>{site_label(site)}</h2>"
                        f"<span class='sum'>{' · '.join(summary)} GWh/d{extra}</span></div>", unsafe_allow_html=True)
            for direction in ("Withdrawal", "Injection"):
                render_panel_card(panels[(site, direction)], equipment, controls, wall)
    if not wall:
        n_live = sum(1 for r in register.records if r.status(now) in ("active", "planned"))
        n_past = len(register.records) - n_live
        title = f"Ad-hoc register ({n_live} live" + (f" · {n_past} past)" if n_past else ")")
        with st.expander(title, expanded=bool(st.session_state.get("rv_table"))):
            render_register(register, equipment, now, actor, editor, loaded.status in ("ok", "local"))
        st.markdown("<div class='r2-sec'>More detail</div>", unsafe_allow_html=True)
        _recent_and_upcoming(data, now, controls.horizon_days)
        st.caption(f"Signed in as {actor}{' · editor' if editor else ' · viewer'}")
    st.markdown("<p class='r2-foot'>Shaded area under each line shows what is setting the level; every cause is "
                "hatched as well as coloured. Charts share one time axis, so dates line up down the page.</p>",
                unsafe_allow_html=True)


def render() -> None:
    theme.inject_css(_wall())
    if st.session_state.get("r2_dialog_open"):
        _body()
    else:
        st.fragment(run_every=timedelta(minutes=5))(_body)()
