"""Page composition (design review sheets 04–06).

Desktop and phone: masthead (title + live status + Wall view) → one ruled
toolbar → six glance wheels → Hornsea and Aldbrough bands (three rows each) →
ad-hoc register → REMIT changes as tabs.

Wall screen (review B2): a 2×3 board — sites as rows, measures as columns —
on the dark tokens, with no controls beyond a faint "Standard view" button.
Reached with the Wall view button or the URL ?mode=wall (the button sets it,
so the link stays shareable). Refreshes every minute, greys itself out with a
banner when data is older than 15 minutes, and reloads the page if the
connection to the server is lost for more than 5 minutes.

The body is a fragment that re-runs on a timer (paused while a dialog is open)
so the 5-min data cache refreshes in place.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ..adhoc.model import DIRECTIONS
from ..adhoc.narrate import change_events
from ..adhoc.units import q as fq, unit_of
from ..core.capacity import compute_recent_changes, short_thread
from ..core.constants import site_label
from ..core.timeutil import LONDON
from . import controls as ctl
from . import data as d
from . import forms, theme
from .hero import day_label, panel_figure, render_panel_card, time_label
from .register_view import render_register, review_count
from . import wheels as wh

TITLE = "Hornsea &amp; Aldbrough availability"
WALL_PLOT_H = 122         # wall board charts: two sites × (wheel + chart + list) must fit 1920×1080
LEDE = "Withdrawal, injection and storage capacity from published REMIT notices and ad-hoc plant changes."


def is_wall() -> bool:
    """The wall screen is chosen by URL, not by the device: <app url>/?mode=wall.
    The Wall view / Standard view buttons set and clear it."""
    return st.query_params.get("mode") == "wall"


def _set_wall(on: bool) -> None:
    if on:
        st.query_params["mode"] = "wall"
    elif "mode" in st.query_params:
        del st.query_params["mode"]
    st.session_state["r2_dialog_open"] = False
    st.rerun()          # full-app rerun: the theme and refresh cadence follow the mode


def _banner(text: str, level: str = "warn") -> None:
    st.markdown(f"<div class='r2-banner r2-banner--{level}'>{text}</div>", unsafe_allow_html=True)


def _feed_status(data: d.RemitData, now: pd.Timestamp) -> tuple[str, str, str]:
    """(css modifier, word, detail) — status is always a word, never colour alone."""
    if data.fetched_at is None:
        return "bad", "No data", "waiting for the feed"
    loc = pd.Timestamp(data.fetched_at).tz_convert(LONDON)
    stamp = f"data {loc.strftime('%H:%M')} {loc.strftime('%Z')}"
    if data.source == "fixture":
        return "sample", "Sample data", stamp
    if data.error:
        age = int((now - data.fetched_at) / pd.Timedelta(minutes=1))
        if data.source == "snapshot" or age > 30:
            return "bad", "Feed failing", stamp
        return "stale", f"Stale · {age} min", stamp
    return "live", "Live", stamp


def _masthead(data: d.RemitData, now: pd.Timestamp) -> bool:
    """Kicker, one-line title and lede | live status with refresh. Returns refresh click."""
    mod, word, detail = _feed_status(data, now)
    with st.container(key="r2mast"):
        c1, c2 = st.columns([3, 1.25], vertical_alignment="bottom")
        with c1:
            st.markdown(f"<div class='r2-kicker'>SSE gas storage · REMIT</div><h1 class='r2-h1'>{TITLE}</h1>"
                        f"<p class='r2-lede'>{LEDE}</p>", unsafe_allow_html=True)
        with c2:
            with st.container(key="r2live"):
                a, b, c = st.columns([1, 0.15, 0.5], gap="small", vertical_alignment="center")
                with a:
                    st.markdown(f"<div class='r2-live r2-live--{mod}'><span class='dot'></span><b>{word}</b>"
                                f"<span>{detail}</span></div>", unsafe_allow_html=True)
                with b:
                    clicked = st.button("", icon=":material/refresh:", type="tertiary", key="r2_refresh",
                                        help="Refresh now — fetch the latest REMIT data")
                with c:
                    with st.container(key="r2modebtn"):
                        if st.button("Wall view", icon=":material/tv:", key="r2_to_wall",
                                     help="Switch to the wall screen: dark, large, no controls (link: ?mode=wall)"):
                            _set_wall(True)
            st.markdown("<div class='r2-sub'>Refreshes every 5 minutes · UK times</div>", unsafe_allow_html=True)
    return clicked


def _toolbar(loaded, equipment, now, actor: str, editor: bool, df_op) -> None:
    """One ruled row: days · Values/Plant · legend · ad-hoc chip (opens the register) · New ad-hoc."""
    reg = loaded.register
    live = [r for r in reg.records if r.status(now) in ("active", "planned")]
    n_active = sum(1 for r in live if r.status(now) == "active")
    n_planned = len(live) - n_active
    n_review = review_count(reg, equipment, now)
    store_ok = loaded.status in ("ok", "local")
    last = reg.meta.get("updated_at")
    last_txt = (f"Last change {pd.Timestamp(last).tz_convert(LONDON).strftime('%d %b %H:%M')} by {reg.meta.get('updated_by')}"
                if last else "No changes recorded yet")
    if loaded.status == "local":
        last_txt += " · local store"
    with st.container(key="r2toolbar"):
        c = st.columns(7, gap="small", vertical_alignment="center")
        with c[0]:
            st.markdown("<span class='r2-lbl'>Show next</span>", unsafe_allow_html=True)
        with c[1]:
            ctl.days_input()
        with c[2]:
            st.markdown("<span class='r2-lbl'>days</span>", unsafe_allow_html=True)
        with c[3]:
            ctl.show_as_input()
        with c[4]:
            st.markdown(theme.legend_html(), unsafe_allow_html=True)
        with c[5]:
            label = f"Ad-hoc: **{n_active}** active · **{n_planned}** planned" + (f" · **{n_review}** to review" if n_review else "")
            if st.button(label, key="r2chip_review" if n_review else "r2chip", help=f"Open the register. {last_txt}"):
                st.session_state["r2_reg_open"] = True
        with c[6]:
            help_ = None if editor else "Only listed editors can add ad-hocs"
            with st.container(key="r2new"):
                if st.button("+ New ad-hoc", type="primary", disabled=not (editor and store_ok), help=help_):
                    st.session_state["af_reset"] = True
                    st.session_state["r2_dialog_open"] = True
                    forms.new_adhoc_dialog(equipment, reg, df_op, actor)
    if not store_ok:
        msg = {"stale": "The ad-hoc register can’t be reached — showing the last copy, read-only.",
               "snapshot": "The ad-hoc register can’t be reached — showing a saved copy, read-only.",
               "unavailable": "The ad-hoc register is unavailable — charts show REMITs only."}[loaded.status]
        _banner(msg, "warn")


def _site_meta(site: str, panels, register, now) -> str:
    ids = {dr.id for direction in DIRECTIONS for s in panels[(site, direction)].segments
           if s.end > now for dr in s.state.drivers if dr.source == "remit"}
    act = sum(1 for r in register.records if r.site == site and r.status(now) == "active")
    pln = sum(1 for r in register.records if r.site == site and r.status(now) == "planned")
    adhoc = (f"ad-hoc: {act} active" + (f", {pln} planned" if pln else "")) if (act or pln) else "no ad-hocs"
    return f"{site} storage · {len(ids)} REMIT{'s' if len(ids) != 1 else ''} in view · {adhoc}"


def _site_bands(panels, register, equipment, controls, now, wall: bool) -> None:
    for site in ("Atwick", "Aldbrough"):
        with st.container(key=f"site-{site.lower()}"):          # full-bleed tinted band per site
            st.markdown(f"<div class='r2-sitehead'><h2>{site_label(site)}</h2>"
                        f"<span class='r2-sitemeta'>{_site_meta(site, panels, register, now)}</span></div>",
                        unsafe_allow_html=True)
            for direction in DIRECTIONS:
                # All rows share one time scale, so dates appear once, under the last row (storage).
                render_panel_card(panels[(site, direction)], equipment, controls, wall, show_x=direction == DIRECTIONS[-1],
                                  plot_h=WALL_PLOT_H if wall else None)


def _changes_tabs(data: d.RemitData, panels, equipment, now) -> None:
    recent = compute_recent_changes(data.df, data.cmap, lookback_hours=24, now=now)
    upcoming = []
    for (site, direction), series in panels.items():
        for e in change_events(series, equipment):
            upcoming.append((e, f"{site_label(site)} · {direction}", direction))
    upcoming.sort(key=lambda x: x[0].at)
    t1, t2 = st.tabs([f"Recent REMIT changes ({len(recent)})", f"Upcoming ({len(upcoming)})"])
    with t1:
        if not recent:
            st.markdown("<p class='r2-td'>No REMIT changes in the last 24 hours.</p>", unsafe_allow_html=True)
        else:
            rows = []
            for it in recent:
                row = it["row"]
                thread = row[data.cmap["threadId"]] if data.cmap.get("threadId") else ""
                pub = it["publication"]
                rows.append(
                    f"<tr><td><span class='r2-kind'>{it['kind']}</span></td><td>{site_label(it['site'])} · {it['category']}</td>"
                    f"<td>{short_thread(thread)} <span class='muted'>rev {it['rev_num']}</span></td>"
                    f"<td>{day_label(row['__eventStart__']) + ' ' + time_label(row['__eventStart__']) if pd.notna(row['__eventStart__']) else ''}"
                    f" → {day_label(row['__eventEnd__']) + ' ' + time_label(row['__eventEnd__']) if pd.notna(row['__eventEnd__']) else 'open'}</td>"
                    f"<td class='muted'>{day_label(pub)} {time_label(pub)}</td></tr>")
            st.markdown("<table class='r2-t'><thead><tr><th>Change</th><th>Site · type</th><th>REMIT</th><th>Outage window (UK)</th>"
                        f"<th>Published</th></tr></thead><tbody>{''.join(rows)}</tbody></table>", unsafe_allow_html=True)
    with t2:
        if not upcoming:
            st.markdown("<p class='r2-td'>No changes ahead in this window.</p>", unsafe_allow_html=True)
        else:
            rows = "".join(
                f"<tr><td>{day_label(e.at)} {time_label(e.at)}</td><td>{where}</td>"
                f"<td><b>{'▼' if e.delta < 0 else '▲'} {fq(e.available, dr)}</b> <span class='muted'>({'+' if e.delta > 0 else '−'}"
                f"{fq(abs(e.delta), dr)}) {unit_of(dr)}</span></td>"
                f"<td>{e.why}</td></tr>" for e, where, dr in upcoming)
            st.markdown("<table class='r2-t'><thead><tr><th>When (UK)</th><th>Site · type</th><th>Level after</th><th>Why</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table>", unsafe_allow_html=True)


def _wall_board(data: d.RemitData, panels, equipment, now: pd.Timestamp) -> None:
    """2×3 ambient board: sites as rows, measures as columns. Each cell: big
    wheel + value, state and next change; the 30-day chart; the next two changes."""
    t = theme.tokens(True)
    stale = wh.is_stale(data.fetched_at, now)
    mod, word, _ = _feed_status(data, now)
    loc = now.tz_convert(LONDON)
    gas_day = day_label(now - pd.Timedelta(hours=5)) if loc.hour < 5 else day_label(now)
    with st.container(key="wb-stale" if stale else "wb"):
        st.markdown(
            f"<div class='wb-head'><div class='wb-title'>SSE gas storage · REMIT<b>{TITLE}</b></div>"
            f"<div class='wb-mid'>{theme.legend_html()}{wh.state_keys(t)}</div>"
            f"<div class='wb-clock'><b>{loc.strftime('%H:%M')}</b><span>{loc.strftime('%Z')} · gas day {gas_day}</span>"
            f"<span class='r2-live r2-live--{mod}'><span class='dot'></span><b>{word}</b></span></div></div>"
            + (wh.stale_banner(data.fetched_at, now, t) if stale else ""), unsafe_allow_html=True)
        for site in ("Atwick", "Aldbrough"):
            with st.container(key=f"wb-site-{site.lower()}"):
                st.markdown(f"<div class='wb-sitename'><b>{site_label(site)}</b><span>{site} storage</span></div>",
                            unsafe_allow_html=True)
                for col, m in zip(st.columns(3, gap="medium"), wh.MEASURES):
                    series = panels[(site, m)]
                    events = change_events(series, equipment)
                    with col:
                        st.markdown(wh.wall_cell_top(series, events, equipment, t, stale), unsafe_allow_html=True)
                        st.plotly_chart(panel_figure(series, equipment, wall=True, show_x=True, events=events, plot_h=WALL_PLOT_H),
                                        width="stretch", config={"displayModeBar": False, "responsive": True, "scrollZoom": False},
                                        key=f"wb-fig-{site}-{m}")
                        st.markdown(wh.wall_cell_list(series, events), unsafe_allow_html=True)
        upd = pd.Timestamp(data.fetched_at).tz_convert(LONDON).strftime("%H:%M") if data.fetched_at is not None else "—"
        st.markdown("<div class='wb-foot'><span>Shading = capacity out, by cause · wheel colour = state · numbers on charts = next changes"
                    f"</span><span>Data {upd} · refreshes every minute · UK times</span></div>", unsafe_allow_html=True)


def _wall_exit() -> None:
    with st.container(key="r2modebtn"):
        if st.button("Standard view", icon=":material/close_fullscreen:", key="r2_to_std", help="Back to the standard page"):
            _set_wall(False)


def _watchdog() -> None:
    """Wall self-recovery: every rerun (1 min) stamps a heartbeat in the page; a
    small watcher installed once in the page reloads it when the heartbeat is
    older than 5 minutes AND the server answers again (never onto an error page)."""
    beat = int(pd.Timestamp.now(tz="UTC").timestamp())
    with st.container(key="r2watch"):
        components.html(
            "<script>(function(){try{var P=window.parent;P.__r2beat=Date.now();if(!P.__r2watch){var s=P.document.createElement('script');"
            "s.textContent=\"window.__r2watch=setInterval(function(){if(Date.now()-(window.__r2beat||0)>300000){"
            "fetch(location.href,{cache:'no-store'}).then(function(r){if(r.ok)location.reload();}).catch(function(){});}},30000);\";"
            f"P.document.head.appendChild(s);}}}}catch(e){{}}}})();</script><!-- beat {beat} -->", height=0)


def _body() -> None:
    wall = is_wall()
    ctl.init_state()
    data = d.load_remit()
    now = pd.Timestamp.now(tz="UTC")
    if wall:
        _wall_exit()
        _watchdog()
        if data.source == "none":
            t = theme.tokens(True)
            st.markdown(f"<div class='wb-head'><div class='wb-title'>SSE gas storage · REMIT<b>{TITLE}</b></div></div>"
                        + wh.stale_banner(None, now, t), unsafe_allow_html=True)
            return
    elif _masthead(data, now):
        st.session_state["r2_dialog_open"] = False
        st.cache_data.clear()
        st.rerun()
    if data.source == "none":
        _banner("Connecting to the SSE REMIT feed — the page fills in automatically once data arrives (retries every 5 minutes).", "info")
        if data.error and not wall:
            with st.expander("Connection detail"):
                st.write(data.error)
        return
    if data.error and not wall:
        _banner(f"Live refresh failing — showing the last good data from {day_label(data.fetched_at)} {time_label(data.fetched_at)}. "
                "Retrying automatically.", "warn")
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
    if wall:
        controls = ctl.current()
        controls.show_as = "Values"
        panels = d.compute_panels(data, register, version, 30, now)      # the wall always shows the next 30 days
        _wall_board(data, panels, equipment, now)
        return
    _toolbar(loaded, equipment, now, actor, editor, data.df_op)
    controls = ctl.current()
    panels = d.compute_panels(data, register, version, controls.horizon_days, now)
    events = {key: change_events(series, equipment) for key, series in panels.items()}
    st.markdown(wh.strip_html(panels, events, equipment, theme.tokens(False), stale=wh.is_stale(data.fetched_at, now)),
                unsafe_allow_html=True)
    _site_bands(panels, register, equipment, controls, now, wall)

    n_live = sum(1 for r in register.records if r.status(now) in ("active", "planned"))
    with st.expander(f"Ad-hoc register · {n_live} live", expanded=bool(st.session_state.get("r2_reg_open", True))):
        render_register(register, equipment, now, actor, editor, loaded.status in ("ok", "local"))
    _changes_tabs(data, panels, equipment, now)
    st.caption(f"Signed in as {actor}{' · editor' if editor else ' · viewer'}")
    st.markdown("<p class='r2-foot'>Shading marks capacity that is out, by cause — hatched as well as coloured; grey before now. "
                "Numbers on the charts match the Coming up lists. Wheels: slate = full, gold = reduced, raspberry = below half. "
                "For the wall display use Wall view (top right), or open the page with ?mode=wall.</p>",
                unsafe_allow_html=True)


def render() -> None:
    wall = is_wall()
    theme.inject_css(wall)
    if st.session_state.get("r2_dialog_open"):
        _body()
    else:
        st.fragment(run_every=timedelta(minutes=1 if wall else 5))(_body)()
