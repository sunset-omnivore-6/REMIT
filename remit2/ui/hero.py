"""Hero cards: header tile + narrative + two-row Plotly figure (step line over
cause lanes) + table twin. Accessible by construction: text twins always
rendered; lanes carry colour AND pattern AND a word; shape encodes change
direction; nothing depends on hover alone."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..adhoc.combine import LANES, PanelSeries
from ..adhoc.model import EquipmentConfig
from ..adhoc.narrate import narrate_panel, plant_terms
from ..core.capacity import short_thread
from ..core.constants import site_label
from ..core.timeutil import LONDON, fmt_local
from . import theme
from .controls import Controls


def _naive_local(ts: pd.Timestamp):
    """Plotly coerces tz-aware datetimes to UTC; plot naive Europe/London."""
    return pd.Timestamp(ts).tz_convert(LONDON).tz_localize(None)


def _driver_text(seg) -> str:
    lines = []
    for d in seg.state.drivers:
        if d.binding:
            red = f" −{d.reduction:.1f}" if d.reduction is not None else ""
            lines.append(f"{d.label}{red}")
    return "<br>".join(lines) if lines else "no outages"


CAUSE_PRIORITY = ("Ad-hoc", "Unplanned REMIT", "Planned REMIT")


def _cause_of(seg) -> str | None:
    f = seg.state.flags()
    for lane, key in zip(CAUSE_PRIORITY, ("adhoc", "remit_unplanned", "remit_planned")):
        if f[key]:
            return lane
    return None


def _cause_runs(series: PanelSeries) -> list[tuple[str | None, list[tuple[pd.Timestamp, float]]]]:
    """Contiguous runs of segments sharing a cause -> polyline points for a
    filled step area (last point closes the run at its own held value)."""
    runs: list[tuple[str | None, list]] = []
    for seg in series.segments:
        cause = _cause_of(seg)
        if runs and runs[-1][0] == cause:
            runs[-1][1].append((seg.start, seg.available))
        else:
            runs.append((cause, [(seg.start, seg.available)]))
        runs[-1][1].append((seg.end, seg.available))
    return runs


def panel_figure(series: PanelSeries, equipment: EquipmentConfig, patterns: bool = True,
                 wall: bool = False, bg: str = theme.PAGE) -> go.Figure:
    tech = series.tech
    start, end = series.window
    now = series.now
    pts = series.points.copy()
    seg_starts = pd.Series([s.start for s in series.segments])
    idx = seg_starts.searchsorted(pts["date"], side="right") - 1
    idx = idx.clip(0, max(0, len(series.segments) - 1))
    pts["pct"] = [100.0 * v / tech if tech else 0 for v in pts["available"]]
    pts["drivers"] = [_driver_text(series.segments[i]) if series.segments else "" for i in idx]
    pts["x"] = pts["date"].map(_naive_local)

    fig = go.Figure()
    fig.add_hline(y=tech, line=dict(color=theme.NAMEPLATE, width=1))
    fig.add_annotation(x=_naive_local(end), y=tech, text=f"nameplate {tech:g}", showarrow=False, xanchor="right",
                       yanchor="bottom", font=dict(size=11, color=theme.INK_SOFT))

    # Area under the line, coloured (and hatched) by the cause of the level.
    shown: set[str] = set()
    for cause, poly in _cause_runs(series):
        if cause is None:
            continue            # no fill where nothing is out: only real causes are shaded
        color = theme.LANE_COLOR[cause]
        name = cause
        kw = dict(fillcolor=theme.rgba(color, 0.32 if cause else 0.10))
        if patterns and cause:
            kw["fillpattern"] = dict(shape=theme.LANE_PATTERN[cause], size=7, solidity=0.25, fgcolor=color, bgcolor=theme.rgba(color, 0.18))
        fig.add_trace(go.Scatter(
            x=[_naive_local(t) for t, _ in poly], y=[v for _, v in poly], mode="lines",
            line=dict(width=0, shape="hv"), fill="tozeroy", name=name, legendgroup=name,
            showlegend=name not in shown, hoverinfo="skip", **kw,
        ))
        shown.add(name)

    fig.add_trace(go.Scatter(
        x=pts["x"], y=pts["available"], mode="lines", name="Available", showlegend=False,
        line=dict(color=theme.INK, width=2.2, shape="hv"),
        customdata=list(zip(pts["pct"], pts["drivers"])),
        hovertemplate="<b>%{y:.1f} GWh/d</b> · %{customdata[0]:.0f}% of nameplate<br>%{customdata[1]}<extra></extra>",
    ))
    ups = [s for s in series.segments if s.delta_prev > 1e-6]
    downs = [s for s in series.segments if s.delta_prev < -1e-6]
    for segs, sym in ((downs, "triangle-down"), (ups, "triangle-up")):
        if segs:
            fig.add_trace(go.Scatter(
                x=[_naive_local(s.start) for s in segs], y=[s.available for s in segs], mode="markers",
                marker=dict(symbol=sym, size=11, color=theme.INK, line=dict(color=bg, width=2)),
                hoverinfo="skip", showlegend=False,
            ))
    cur = series.segment_at(now)
    x_now = _naive_local(now)
    # Fade the past: a veil in the row's own background colour drawn ABOVE the
    # data left of now, so what is coming reads first and history stays legible.
    fig.add_vrect(x0=_naive_local(start), x1=x_now, fillcolor=theme.rgba(bg, 0.58), line_width=0, layer="above")
    fig.add_vline(x=x_now, line=dict(color=theme.INK_SOFT, width=1))
    if cur is not None:
        fig.add_annotation(x=x_now, y=cur.available, text=f"now {cur.available:.1f}", showarrow=False,
                           xanchor="left", yanchor="bottom", xshift=6, yshift=4,
                           font=dict(size=12, color=theme.INK), bgcolor=theme.rgba(bg, 0.9))

    # No zoom/pan: the window is set by "Days ahead"; an accidental drag-zoom
    # with the modebar hidden had no way back.
    fig.update_yaxes(range=[-0.018 * tech, 1.14 * tech], gridcolor=theme.GRID, zeroline=False,
                     showline=False, fixedrange=True, ticks="", nticks=4, tickfont=dict(size=11, color=theme.INK_SOFT))
    fig.update_xaxes(type="date", range=[_naive_local(start), _naive_local(end)], showgrid=False, fixedrange=True,
                     showline=True, linecolor="#cbd5e1", ticks="outside", ticklen=4, tickcolor="#cbd5e1",
                     tickfont=dict(size=11, color=theme.INK_SOFT),
                     tickformatstops=[dict(dtickrange=[None, 3600000 * 12], value="%H:%M\n%d %b"),
                                      dict(dtickrange=[3600000 * 12, None], value="%d %b")])
    fig.update_layout(
        height=260 if wall else 205, margin=dict(l=34, r=8, t=6, b=26), showlegend=False,
        hovermode="x unified", hoverlabel=dict(bgcolor=theme.SURFACE, bordercolor=theme.GRID, align="left",
                                                font=dict(family=theme.FONT, size=12, color=theme.INK)),
        plot_bgcolor=bg, paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.FONT, size=16 if wall else 12, color=theme.INK),
        transition=dict(duration=0), dragmode=False,
    )
    return fig


def panel_table(series: PanelSeries) -> pd.DataFrame:
    rows = []
    for s in series.segments:
        remit = [f"{short_thread(d.id)} ({'P' if d.planned else 'U'})" for d in s.state.drivers if d.binding and d.source == "remit"]
        adhoc = [d.id for d in s.state.drivers if d.binding and d.source == "adhoc"]
        rows.append({
            "From": fmt_local(s.start), "To": fmt_local(s.end), "Available GWh/d": round(s.available, 2),
            "% nameplate": round(s.state.pct, 0), "Change": round(s.delta_prev, 2) if abs(s.delta_prev) > 1e-6 else None,
            "REMIT": ", ".join(remit), "Ad-hoc": ", ".join(adhoc),
        })
    return pd.DataFrame(rows)


def _status_html(state) -> str:
    f = state.flags()
    parts = [lane for lane, key in (("Planned REMIT", "remit_planned"), ("Unplanned REMIT", "remit_unplanned"),
                                    ("Ad-hoc", "adhoc")) if f[key]]
    if not parts:
        return "<span class='r2-status'><i class='sw sw-none'></i>No outage</span>"
    return " ".join(f"<span class='r2-status'><i class='sw {theme.LANE_CLASS[p]}'></i>{p}</span>" for p in parts)


def _numbers_html(series: PanelSeries, equipment: EquipmentConfig, controls: Controls) -> str:
    site, direction = series.site, series.direction
    cfg = equipment.get(site, direction)
    cur = series.segment_at(series.now)
    tech = series.tech
    if cur is None:
        return f"<div class='r2-num'><div class='dir'>{direction}</div><div class='val'>—</div></div>"
    pct = cur.state.pct
    plant = controls.show_as == "Plant" and cfg.plant_view
    if plant:
        big = f"<div class='val val--text'>{plant_terms(cur.state, equipment, site, direction)}</div>"
        sub = f"{cur.available:.1f} of {tech:g} GWh/d · {pct:.0f}%"
    else:
        big = f"<div class='val'>{cur.available:.1f}<span class='unit'>GWh/d</span></div>"
        sub = f"of {tech:g} · {pct:.0f}%"
    ph = "<div class='note'>placeholder unit values</div>" if plant and any(u.placeholder for u in cfg.units) else ""
    return (
        f"<div class='r2-num'><div class='dir'>{direction}</div>{big}<div class='of'>{sub}</div>"
        f"<div class='r2-meter' role='meter' aria-valuemin='0' aria-valuemax='{tech:g}' aria-valuenow='{cur.available:.1f}'"
        f" aria-label='{site_label(site)} {direction} available'><span style='width:{max(0, min(100, pct)):.1f}%'></span></div>"
        f"<div class='r2-stline'>{_status_html(cur.state)}</div>{ph}</div>"
    )


def _short(ts) -> str:
    t = pd.Timestamp(ts).tz_convert(LONDON)
    return t.strftime("%a&nbsp;%d&nbsp;%b") + " " + t.strftime("%H:%M")   # time may wrap; the date never splits


def _up_class(series: PanelSeries, variant: str) -> str:
    return "r2-up" + ("" if variant == "panel" else f" r2-up--{variant}")


def _up_style(series: PanelSeries, variant: str) -> str:
    return f" style='background:{theme.PLOT_BG.get(series.site, theme.SURFACE)}'" if variant == "tint" else ""


def _upcoming_html(series: PanelSeries, limit: int = 4, variant: str = "panel") -> str:
    future = [s for s in series.segments if s.start > series.now and abs(s.delta_prev) > 1e-6]
    days = max(1, (series.window[1] - series.now).days)
    if not future:
        return f"<div class='{_up_class(series, variant)}'{_up_style(series, variant)}><div class='hd'>Coming up</div><div class='none'>No changes in the next {days} days.</div></div>"
    rows = []
    for s in future[:limit]:
        glyph = "▼" if s.delta_prev < 0 else "▲"
        cls = "dn" if s.delta_prev < 0 else "upv"
        why = "; ".join(short_thread(d.id) if d.source == "remit" else d.id for d in s.state.drivers if d.binding) \
            or ("outage ends" if s.delta_prev > 0 else "")
        rows.append(f"<li><span class='g {cls}'>{glyph}</span><span class='v'>{s.available:.1f}</span>"
                    f"<span class='t'>{_short(s.start)}</span><span class='w'>{why}</span></li>")
    more = f"<div class='more'>+ {len(future) - limit} more</div>" if len(future) > limit else ""
    return f"<div class='{_up_class(series, variant)}'{_up_style(series, variant)}><div class='hd'>Coming up</div><ul>{''.join(rows)}</ul>{more}</div>"


def render_panel_card(series: PanelSeries, equipment: EquipmentConfig, controls: Controls, wall: bool = False) -> None:
    """One site/direction row: numbers | wide chart | coming up. Rows share
    column widths and date range, so timelines line up down the page."""
    key = f"card-{series.site.lower()}-{series.direction.lower()}"
    mode = "plant" if controls.show_as == "Plant" else "values"
    variant = up_variant()
    plot_bg = theme.PLOT_BG.get(series.site, theme.SURFACE)
    fig = panel_figure(series, equipment, True, wall, plot_bg)
    cfg = {"displayModeBar": False, "responsive": True, "scrollZoom": False}
    numbers = (_numbers_html(series, equipment, controls)
               + f"<p class='r2-sr'>{narrate_panel(series, equipment, mode)}</p>")
    with st.container(key=key):
        if variant == "left":
            c1, c2 = st.columns([1.25, 5.95], gap="medium", vertical_alignment="top")
            with c1:
                st.markdown(numbers + _upcoming_html(series, 3, variant), unsafe_allow_html=True)
            with c2:
                st.plotly_chart(fig, width="stretch", config=cfg, key=f"fig-{key}")
            return
        c1, c2, c3 = st.columns([0.95, 4.9, 1.35], gap="medium", vertical_alignment="top")
        with c1:
            st.markdown(numbers, unsafe_allow_html=True)
        with c2:
            st.plotly_chart(fig, width="stretch", config=cfg, key=f"fig-{key}")
        with c3:
            st.markdown(_upcoming_html(series, 4, variant), unsafe_allow_html=True)


def up_variant() -> str:
    """Coming-up layout under evaluation: ?up=tint|panel|plain|left (default tint)."""
    v = st.query_params.get("up", "tint")
    return v if v in ("panel", "plain", "tint", "left") else "tint"
