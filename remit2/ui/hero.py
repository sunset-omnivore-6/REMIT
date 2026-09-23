"""One site/direction row (design review sheets 02–03): headline block | chart | Coming up.

The chart shades only what is MISSING: the band between the line and the
maximum, split into its REMIT part (T − R) and its ad-hoc part (R − Avail),
each coloured AND hatched by cause. What is available stays a calm grey wash.
Colour starts at now — history is grey with the same hatch directions.
Future steps carry numbered markers that match the Coming up list; the grid is
the gas day (05:00 UK), darker on Mondays. One unified tooltip lists every
cause at the hovered moment. Nothing depends on hover alone: the headline
block, the numbered list and a screen-reader sentence carry the same facts.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..adhoc.combine import LostPart, PanelSeries, lost_parts
from ..adhoc.model import EquipmentConfig
from ..adhoc.narrate import ChangeEvent, change_events, narrate_panel
from ..core.capacity import short_thread
from ..core.timeutil import LONDON
from . import theme
from .controls import Controls

EPS = 1e-6


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _loc(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(LONDON)


def _naive_local(ts):
    """Plotly coerces tz-aware datetimes to UTC; plot naive Europe/London."""
    return _loc(ts).tz_localize(None)


def day_label(ts) -> str:
    t = _loc(ts)
    return f"{t.strftime('%a')} {t.day} {t.strftime('%b')}"      # 'Thu 24 Sep'


def time_label(ts) -> str:
    return _loc(ts).strftime("%H:%M")


def rel_label(ts, now) -> str:
    n = (_loc(ts).normalize() - _loc(now).normalize()).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n > 1:
        return f"in {n} days"
    return "yesterday" if n == -1 else f"{-n} days ago"


def _cap(v: float) -> str:
    return f"{v:g}" if abs(v - round(v)) > 1e-9 else str(int(round(v)))


def _tick(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def part_ids(part: LostPart, series: PanelSeries, equipment: EquipmentConfig, state) -> str:
    if part.lane == "Ad-hoc":
        labels = {u.id: u.label for u in equipment.get(series.site, series.direction).units}
        return ", ".join(d.id + (f" ({', '.join(labels.get(u, u) for u in d.units)})" if d.units else "")
                         for d in state.drivers if d.source == "adhoc" and d.binding)
    return ", ".join(short_thread(i) for i in part.ids)


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def _rects(rects: list[tuple]) -> tuple[list, list]:
    xs, ys = [], []
    for x0, x1, y0, y1 in rects:
        xs += [x0, x1, x1, x0, x0, None]
        ys += [y0, y0, y1, y1, y0, None]
    return xs, ys


def _gas_days(start, end) -> list[pd.Timestamp]:
    """05:00 UK each day within the window (UTC timestamps)."""
    out = []
    d = _loc(start).normalize() - pd.Timedelta(days=1)
    stop = _loc(end).normalize() + pd.Timedelta(days=1)
    while d <= stop:
        t = pd.Timestamp(d.year, d.month, d.day, 5, 0).tz_localize(LONDON).tz_convert("UTC")
        if start <= t <= end:
            out.append(t)
        d += pd.Timedelta(days=1)
    return out


def _hover_text(series: PanelSeries, equipment: EquipmentConfig, seg, t: dict, past: bool) -> str:
    parts = lost_parts(seg.state)
    head = f"<b>{seg.available:.1f}</b> of {_cap(series.tech)} GWh/d available" + (" · history" if past else "")
    if not parts:
        return head + "<br>Full capacity"
    rows = []
    for p in parts:
        col = t["past"] if past else t[theme.LANE_KEY[p.lane]]
        ids = part_ids(p, series, equipment, seg.state)
        rows.append(f"<span style='color:{col}'>▬</span> {p.lane}{' · ' + ids if ids else ''}  <b>−{p.amount:.1f}</b>")
    return head + "<br>" + "<br>".join(rows)


def panel_figure(series: PanelSeries, equipment: EquipmentConfig, *, wall: bool = False, show_x: bool = True,
                 mini: bool = False, max_events: int | None = None, events: list[ChangeEvent] | None = None) -> go.Figure:
    t = theme.tokens(wall)
    T = series.tech
    S, E = series.window
    N = series.now
    bg = t["plot"].get(series.site, t["card"])
    X = _naive_local
    mark_y = 1.095 * T

    # Split segments at now: history is drawn grey.
    segs = []
    for s in series.segments:
        a, b = max(s.start, S), min(s.end, E)
        if b <= a:
            continue
        if a < N < b:
            segs += [(a, N, s, True), (N, b, s, False)]
        else:
            segs.append((a, b, s, b <= N))

    fig = go.Figure()
    shapes = [dict(type="rect", xref="x", yref="y", x0=X(S), x1=X(E), y0=0, y1=T, fillcolor=bg, line_width=0, layer="below")]
    span_days = (E - S) / pd.Timedelta(days=1)
    gd = _gas_days(S, E)
    for g in gd:
        mon = _loc(g).weekday() == 0
        if span_days > 62 and not mon:
            continue
        shapes.append(dict(type="line", xref="x", yref="y", x0=X(g), x1=X(g), y0=0, y1=T, layer="below",
                           line=dict(color=t["grid_mon"] if mon else t["grid"], width=1)))
    shapes.append(dict(type="line", xref="x", yref="y", x0=X(S), x1=X(E), y0=T / 2, y1=T / 2, layer="below",
                       line=dict(color=t["grid"], width=1)))

    # Available: a calm grey wash under the line (lighter in the past).
    for past in (True, False):
        xs, ys = _rects([(X(a), X(b), 0, s.available) for a, b, s, p in segs if p == past and s.available > EPS])
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", mode="lines", line=dict(width=0),
                                     fillcolor=t["avail_past"] if past else t["avail"], hoverinfo="skip", showlegend=False))

    # Lost capacity by cause: REMIT part from R up to the maximum, ad-hoc part below it.
    groups: dict[tuple[str, bool], list] = {}
    gaps: list[tuple] = []
    for a, b, s, past in segs:
        parts = lost_parts(s.state)
        r = max(0.0, min(s.state.remit_avail, T))
        for p in parts:
            key = theme.LANE_KEY[p.lane]
            y0, y1 = (r, T) if p.lane != "Ad-hoc" else (s.available, r)
            groups.setdefault((key, past), []).append((X(a), X(b), y0, y1))
        if len(parts) == 2:
            gaps.append((X(a), X(b), r))
    for (key, past), rects in groups.items():
        col = t["past"] if past else t[key]
        wash = theme.rgba(col, .12 if past else .17)
        xs, ys = _rects(rects)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, fill="toself", mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False, fillcolor=wash,
            fillpattern=dict(shape=theme.LANE_PATTERN[key], fgcolor=col, bgcolor=wash,
                             size=5 if key == "adhoc" else 6, solidity=0.34 if key == "adhoc" else 0.3),
        ))
    if gaps:   # 2px surface gap between the stacked REMIT and ad-hoc parts
        xs, ys = [], []
        for x0, x1, y in gaps:
            xs += [x0, x1, None]
            ys += [y, y, None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=bg, width=2), hoverinfo="skip", showlegend=False))

    shapes.append(dict(type="line", xref="x", yref="y", x0=X(S), x1=X(E), y0=T, y1=T, line=dict(color=t["nameplate"], width=1)))
    shapes.append(dict(type="line", xref="x", yref="y", x0=X(S), x1=X(E), y0=0, y1=0, line=dict(color=t["axis"], width=1)))

    # The availability line: ink ahead of now, grey behind it.
    for past in (True, False):
        xs, ys = [], []
        for a, b, s, p in segs:
            if p == past:
                xs += [X(a), X(b)]
                ys += [s.available, s.available]
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
                                     line=dict(color=t["ink_past"] if past else t["ink"], width=1.5 if past else 2)))

    # Numbered changes: marker above the plot, faint line down through it.
    events = change_events(series, equipment) if events is None else events
    if max_events is not None:
        events = events[:max_events]
    min_gap = (E - S) * 0.022
    last = None
    mx, my, mt = [], [], []
    for ev in events:
        shapes.append(dict(type="line", xref="x", yref="y", x0=X(ev.at), x1=X(ev.at), y0=0, y1=T,
                           line=dict(color=theme.rgba(t["ink"], .2), width=1)))
        at = ev.at if last is None or ev.at - last >= min_gap else last + min_gap
        if at != ev.at:
            shapes.append(dict(type="line", xref="x", yref="y", x0=X(at), x1=X(ev.at), y0=mark_y, y1=T,
                               line=dict(color=theme.rgba(t["ink"], .5), width=1)))
        last = at
        mx.append(X(at))
        my.append(mark_y)
        mt.append(str(ev.n))
    if mx:
        fig.add_trace(go.Scatter(x=mx, y=my, mode="markers+text", text=mt, textposition="middle center",
                                 textfont=dict(color=t["on_ink"], size=12 if wall else 10, family=theme.FONT),
                                 marker=dict(size=20 if wall else 16, color=t["ink"]), cliponaxis=False,
                                 hoverinfo="skip", showlegend=False))

    # Now: line, label, point and value.
    cur = series.segment_at(N)
    annotations = []
    if S < N < E:
        shapes.append(dict(type="line", xref="x", yref="y", x0=X(N), x1=X(N), y0=0, y1=1.14 * T,
                           line=dict(color=t["ink"], width=1.5)))
        annotations.append(dict(x=X(N), y=mark_y, text="<b>Now</b>", showarrow=False, xanchor="right", xshift=-5,
                                font=dict(size=13 if wall else 11, color=t["ink2"])))
        if cur is not None:
            v = cur.available
            fig.add_trace(go.Scatter(x=[X(N)], y=[v], mode="markers", hoverinfo="skip", showlegend=False, cliponaxis=False,
                                     marker=dict(size=9, color=t["ink"], line=dict(color=bg, width=2))))
            high = v > 0.8 * T
            annotations.append(dict(x=X(N), y=v, text=f"<b>{v:.1f}</b>", showarrow=False, xanchor="left", xshift=7,
                                    yanchor="top" if high else "bottom", yshift=-5 if high else 5,
                                    font=dict(size=15 if wall else 12, color=t["ink"]), bgcolor=theme.rgba(bg, .85)))
    if not mini:
        annotations.append(dict(xref="paper", x=0, y=mark_y, text="GWh/d", showarrow=False, xanchor="right", xshift=-2,
                                font=dict(size=12 if wall else 10.5, color=t["ink3"])))

    # Hover: one unified tooltip listing every cause at that moment.
    pts = series.points
    if series.segments and not pts.empty:
        starts = pd.Series([s.start for s in series.segments])
        idx = (starts.searchsorted(pts["date"], side="right") - 1).clip(0, len(series.segments) - 1)
        cache: dict = {}
        texts = []
        for i, d in zip(idx, pts["date"]):
            k = (int(i), bool(d < N))
            if k not in cache:
                cache[k] = _hover_text(series, equipment, series.segments[k[0]], t, k[1])
            texts.append(cache[k])
        fig.add_trace(go.Scatter(x=[X(d) for d in pts["date"]], y=pts["available"], mode="lines",
                                 line=dict(width=0, color="rgba(0,0,0,0)"), customdata=texts,
                                 hovertemplate="%{customdata}<extra></extra>", showlegend=False))

    # Axes: the top edge is the maximum; dates once per site (show_x).
    if span_days <= 120:
        ticks = [g for g in gd if _loc(g).weekday() == 0]
        text, last_m = [], None
        for g in ticks:
            m = _loc(g).strftime("%b")
            text.append(f"Mon {_loc(g).day}" + (f" {m}" if m != last_m else ""))
            last_m = m
    else:
        ticks = [g for g in gd if _loc(g).day == 1]
        text = [_loc(g).strftime("%b %Y") if _loc(g).month == 1 else _loc(g).strftime("%b") for g in ticks]
    fig.update_xaxes(type="date", range=[X(S), X(E)], showgrid=False, zeroline=False, fixedrange=True,
                     tickvals=[X(g) for g in ticks], ticktext=text, showticklabels=show_x, ticks="",
                     tickfont=dict(size=13 if wall else 11, color=t["ink3"]),
                     showspikes=True, spikemode="across", spikesnap="cursor", spikecolor=t["ink"], spikethickness=1,
                     spikedash="solid", hoverformat="%a %-d %b · %H:%M")
    fig.update_yaxes(range=[-0.02 * T, 1.17 * T], tickvals=[0, T / 2, T], ticktext=["0", _tick(T / 2), _cap(T)],
                     showgrid=False, zeroline=False, showline=False, fixedrange=True, ticks="",
                     tickfont=dict(size=13 if wall else 11, color=t["ink3"]))
    plot_h = 100 if mini else 150
    b = 22 if show_x else 10
    fig.update_layout(
        height=plot_h + 4 + b, margin=dict(l=50 if wall else 40, r=10, t=4, b=b), showlegend=False,
        shapes=shapes, annotations=annotations, hovermode="x unified",
        hoverlabel=dict(bgcolor=t["card"], bordercolor=t["rule"], align="left",
                        font=dict(family=theme.FONT, size=12, color=t["ink"])),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.FONT, size=12, color=t["ink"]),
        transition=dict(duration=0), dragmode=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Headline block (now · cause · next) and Plant tiles
# ---------------------------------------------------------------------------

def _next_html(events: list[ChangeEvent], series: PanelSeries) -> str:
    if not events:
        days = max(1, (series.window[1] - series.now).days)
        return f"<div class='next muted'>No change in the next {days} days</div>"
    ev = events[0]
    return (f"<div class='next'>Next <b>{'▼' if ev.delta < 0 else '▲'} {ev.available:.1f}</b><br>"
            f"{day_label(ev.at)} {time_label(ev.at)} <span class='muted'>· {rel_label(ev.at, series.now)}</span></div>")


def _plant_html(series: PanelSeries, equipment: EquipmentConfig, state, next_html: str) -> str:
    cfg = equipment.get(series.site, series.direction)
    T = series.tech
    lost = set(state.lost_units)
    units = [dict(id=u.id, label=u.label, gwhd=u.gwhd_lost, st="adhoc" if u.id in lost else "on") for u in cfg.units]
    uniform = len({u["gwhd"] for u in units}) == 1
    r_red = T - max(0.0, min(state.remit_avail, T))
    remit_parts = [p for p in lost_parts(state) if p.lane != "Ad-hoc"]
    rkey = theme.LANE_KEY[remit_parts[0].lane] if remit_parts else "planned"
    est = 0
    if r_red > EPS and units:
        if uniform:     # REMITs are GWh/d only: convert to the nearest whole units, marked ≈
            k = int(round(r_red / units[0]["gwhd"])) if units[0]["gwhd"] else 0
            for u in reversed(units):
                if k <= 0:
                    break
                if u["st"] == "on":
                    u["st"], k, est = rkey, k - 1, est + 1
        else:
            m = next((u for u in units if u["st"] == "on" and abs(u["gwhd"] - r_red) <= 0.15 * u["gwhd"]), None)
            if m:
                m["st"], est = rkey, 1
    on = [u for u in units if u["st"] == "on"]
    tiles = "".join(
        f"<div class='r2-unit r2-unit--{u['st']}' style='flex:{'1 1 0' if uniform else str(u['gwhd']) + ' 1 0;min-width:78px'}'>"
        f"<span>{'≈ ' if u['st'] in ('planned', 'unplanned') else ''}{u['label']}</span></div>" for u in units)
    noun = cfg.unit_noun or "unit"
    head = (f"{len(on)} of {len(units)} {noun}s running" if uniform
            else (" + ".join(u["label"] for u in on) or "Nothing") + " running")
    sub = f"{state.available:.1f} / {_cap(T)} GWh/d" + (" · ≈ estimated from REMIT" if est else "")
    if state.cap is not None and state.available <= state.cap + EPS:
        sub += f" · rate capped at {state.cap:.1f}"
    note = "<div class='note'>Placeholder unit values</div>" if any(u.placeholder for u in cfg.units) else ""
    return (f"<div class='r2-kpi'><div class='lab'>{series.direction} · plant</div><div class='plant'>{head}</div>"
            f"<div class='r2-units'>{tiles}</div><div class='sub'>{sub}</div>{note}{next_html}</div>")


def kpi_html(series: PanelSeries, equipment: EquipmentConfig, controls: Controls, events: list[ChangeEvent]) -> str:
    cur = series.segment_at(series.now)
    if cur is None:
        return f"<div class='r2-kpi'><div class='lab'>{series.direction}</div><div class='val'>—</div></div>"
    nxt = _next_html(events, series)
    if controls.show_as == "Plant" and equipment.get(series.site, series.direction).plant_view:
        return _plant_html(series, equipment, cur.state, nxt)
    parts = lost_parts(cur.state)
    if parts:
        cause = "".join(
            f"<div class='cause'>{theme.swatch(theme.LANE_KEY[p.lane])}<span>{p.lane} "
            f"<span class='ids'>{part_ids(p, series, equipment, cur.state)}</span></span></div>" for p in parts)
    else:
        cause = "<div class='cause muted'>✓ <span>Full capacity</span></div>"
    return (f"<div class='r2-kpi'><div class='lab'>{series.direction}</div>"
            f"<div class='val'>{cur.available:.1f}<span class='of'>/ {_cap(series.tech)} GWh/d</span></div>{cause}{nxt}</div>")


# ---------------------------------------------------------------------------
# Coming up
# ---------------------------------------------------------------------------

def upcoming_html(series: PanelSeries, events: list[ChangeEvent], limit: int = 4) -> str:
    days = max(1, (series.window[1] - series.now).days)
    if not events:
        return (f"<div class='r2-up'><div class='hd'><span>Coming up</span></div>"
                f"<p class='none'>No changes in the next {days} days.</p></div>")
    items = "".join(
        f"<li><span class='num'>{e.n}</span><span class='when'><b>{day_label(e.at)}</b> {time_label(e.at)}</span>"
        f"<span class='chg'><i>{'▼' if e.delta < 0 else '▲'}</i>{e.available:.1f}</span><span class='why'>{e.why}</span></li>"
        for e in events[:limit])
    more = f"<div class='more'>+ {len(events) - limit} more</div>" if len(events) > limit else ""
    n = len(events)
    return (f"<div class='r2-up'><div class='hd'><span>Coming up</span><span>{n} change{'s' if n != 1 else ''}</span></div>"
            f"<ol>{items}</ol>{more}</div>")


def render_panel_card(series: PanelSeries, equipment: EquipmentConfig, controls: Controls, wall: bool = False,
                      show_x: bool = True) -> None:
    """Headline block | wide chart | Coming up. Rows share column widths and
    the time window, so the charts line up down the page."""
    key = f"card-{series.site.lower()}-{series.direction.lower()}"
    mode = "plant" if controls.show_as == "Plant" else "values"
    events = change_events(series, equipment)
    fig = panel_figure(series, equipment, wall=wall, show_x=show_x, events=events)
    head = kpi_html(series, equipment, controls, events) + f"<p class='r2-sr'>{narrate_panel(series, equipment, mode)}</p>"
    with st.container(key=key):
        widths = [1, 4.6, 1.5] if wall else [1, 3.85, 1.46]
        c1, c2, c3 = st.columns(widths, gap="medium", vertical_alignment="top")
        with c1:
            st.markdown(head, unsafe_allow_html=True)
        with c2:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "responsive": True, "scrollZoom": False},
                            key=f"fig-{key}")
        with c3:
            st.markdown(upcoming_html(series, events, 2 if wall else 4), unsafe_allow_html=True)
