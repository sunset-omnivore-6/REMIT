"""Hero cards: header tile + narrative + two-row Plotly figure (step line over
cause lanes) + table twin. Accessible by construction: text twins always
rendered; lanes carry colour AND pattern AND a word; shape encodes change
direction; nothing depends on hover alone."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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


def panel_figure(series: PanelSeries, equipment: EquipmentConfig, patterns: bool = True,
                 wall: bool = False) -> go.Figure:
    tech = series.tech
    start, end = series.window
    now = series.now
    pts = series.points.copy()
    # Per-point driver text and pct via the segment each point falls in.
    seg_starts = pd.Series([s.start for s in series.segments])
    idx = seg_starts.searchsorted(pts["date"], side="right") - 1
    idx = idx.clip(0, max(0, len(series.segments) - 1))
    pts["pct"] = [100.0 * v / tech if tech else 0 for v in pts["available"]]
    pts["drivers"] = [_driver_text(series.segments[i]) if series.segments else "" for i in idx]
    pts["x"] = pts["date"].map(_naive_local)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.76, 0.24], vertical_spacing=0.06)

    # Row 1 — past wash, nameplate hairline, step line, change markers
    fig.add_vrect(x0=_naive_local(start), x1=_naive_local(now), fillcolor="rgba(15,23,42,0.035)", line_width=0, row=1, col=1)
    fig.add_hline(y=tech, line=dict(color=theme.NAMEPLATE, width=1), row=1, col=1)
    fig.add_annotation(x=_naive_local(end), y=tech, text=f"nameplate {tech:g}", showarrow=False, xanchor="right",
                       yanchor="bottom", font=dict(size=11, color=theme.INK_SOFT), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=pts["x"], y=pts["available"], mode="lines", name="Available",
        line=dict(color=theme.INK, width=2.2, shape="hv"), fill="tozeroy", fillcolor="rgba(15,23,42,0.06)",
        customdata=list(zip(pts["pct"], pts["drivers"])),
        hovertemplate="<b>%{y:.1f} GWh/d</b> · %{customdata[0]:.0f}% of nameplate<br>%{customdata[1]}<extra></extra>",
    ), row=1, col=1)
    ups = [s for s in series.segments if s.delta_prev > 1e-6]
    downs = [s for s in series.segments if s.delta_prev < -1e-6]
    for segs, sym, name in ((downs, "triangle-down", "drop"), (ups, "triangle-up", "restore")):
        if segs:
            fig.add_trace(go.Scatter(
                x=[_naive_local(s.start) for s in segs], y=[s.available for s in segs], mode="markers", name=name,
                marker=dict(symbol=sym, size=11, color=theme.INK, line=dict(color=theme.SURFACE, width=2)),
                hoverinfo="skip", showlegend=False,
            ), row=1, col=1)
    cur = series.segment_at(now)
    if cur is not None:
        fig.add_annotation(x=_naive_local(now), y=cur.available, text=f"now {cur.available:.1f}", showarrow=False,
                           xanchor="left", yanchor="bottom", xshift=6, yshift=4,
                           font=dict(size=12, color=theme.INK), bgcolor="rgba(255,255,255,.85)", row=1, col=1)

    # Row 2 — cause lanes (horizontal bars on a date axis: base=start, x=duration ms)
    for lane in LANES:
        bars = [l for l in series.lanes if l.lane == lane]
        color = theme.LANE_COLOR[lane]
        marker = dict(color=color, opacity=0.85, line=dict(color=theme.SURFACE, width=1))
        if patterns:
            # fillmode="overlay": hatch drawn OVER the lane colour (the default
            # "replace" mode would paint the hatch on a transparent bar).
            marker["pattern"] = dict(shape=theme.LANE_PATTERN[lane], size=6, solidity=0.3,
                                     fillmode="overlay", fgcolor=theme.SURFACE, fgopacity=0.55)
        if not bars:
            fig.add_trace(go.Bar(x=[0], base=[_naive_local(start)], y=[lane], orientation="h", marker=marker,
                                 hoverinfo="skip", showlegend=False), row=2, col=1)
            continue
        total = (end - start).total_seconds()
        fig.add_trace(go.Bar(
            x=[(l.end - l.start).total_seconds() * 1000 for l in bars],
            base=[_naive_local(l.start) for l in bars],
            y=[lane] * len(bars), orientation="h", marker=marker, name=lane, showlegend=False,
            text=[", ".join(short_thread(i) for i in l.ids) if (l.end - l.start).total_seconds() > 0.08 * total else "" for l in bars],
            textposition="inside", insidetextanchor="start", textfont=dict(color=theme.SURFACE, size=11),
            customdata=[(l.label, fmt_local(l.start), fmt_local(l.end)) for l in bars],
            hovertemplate="<b>" + lane + "</b><br>%{customdata[0]}<br>%{customdata[1]} → %{customdata[2]}<extra></extra>",
        ), row=2, col=1)

    # now line across both rows
    x_now = _naive_local(now)
    fig.add_vline(x=x_now, line=dict(color=theme.INK, width=1.5))

    fig.update_yaxes(range=[-0.018 * tech, 1.12 * tech], title_text="GWh/d", gridcolor=theme.GRID, zeroline=False,
                     showline=True, linecolor=theme.GRID, mirror=True, row=1, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=list(reversed(LANES)), showgrid=False, showline=True,
                     linecolor=theme.GRID, mirror=True, tickfont=dict(size=11),
                     tickvals=list(LANES), ticktext=["Planned", "Unplanned", "Ad-hoc"], row=2, col=1)
    fig.update_xaxes(type="date", range=[_naive_local(start), _naive_local(end)], gridcolor=theme.GRID,
                     showline=True, linecolor=theme.GRID, mirror=True,
                     tickformatstops=[dict(dtickrange=[None, 3600000 * 12], value="%H:%M\n%d %b"),
                                      dict(dtickrange=[3600000 * 12, None], value="%d %b")])
    fig.update_xaxes(title_text="Europe/London", row=2, col=1)
    fig.update_layout(
        height=420 if wall else 320, margin=dict(l=70, r=14, t=22, b=40), barmode="overlay", bargap=0.35,
        hovermode="x unified", hoverlabel=dict(bgcolor=theme.SURFACE, bordercolor=theme.GRID, align="left",
                                                font=dict(family=theme.FONT, size=12, color=theme.INK)),
        plot_bgcolor=theme.SURFACE, paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
        font=dict(family=theme.FONT, size=16 if wall else 12, color=theme.INK),
        transition=dict(duration=0), uirevision="panel",
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


def _tile_html(series: PanelSeries, equipment: EquipmentConfig, controls: Controls) -> str:
    site, direction = series.site, series.direction
    cfg = equipment.get(site, direction)
    cur = series.segment_at(series.now)
    tech = series.tech
    if cur is None:
        return f"<div class='r2-tile'><span class='label'>{site_label(site)} · {direction}</span><span class='value'>—</span></div>"
    plant = controls.show_as == "Plant" and cfg.plant_view
    value = plant_terms(cur.state, equipment, site, direction) if plant else f"{cur.available:.1f}"
    unit = "" if plant else "<span class='unit'>GWh/d</span>"
    value_html = f"<span class='value' style='font-size:{'1.35rem' if plant else '2.1rem'}'>{value}</span>{unit}"
    pct = cur.state.pct
    nxt = next((s for s in series.segments if s.start > series.now and abs(s.delta_prev) > 1e-6), None)
    if nxt is None:
        next_html = "<div class='r2-next'>No change in the horizon.</div>"
    else:
        glyph, word = ("▼", "drop") if nxt.delta_prev < 0 else ("▲", "restore")
        who = "; ".join(d.label for d in nxt.state.drivers if d.binding) or ("outage ends" if nxt.delta_prev > 0 else "—")
        next_html = f"<div class='r2-next'>Next: {glyph} {word} to <b>{nxt.available:.1f}</b> at {fmt_local(nxt.start)} <span class='sub'>({who})</span></div>"
    chips = ""
    flags = cur.state.flags()
    for lane, flag in (("Planned REMIT", flags["remit_planned"]), ("Unplanned REMIT", flags["remit_unplanned"]), ("Ad-hoc", flags["adhoc"])):
        if flag:
            chips += theme.chip(lane, theme.LANE_COLOR[lane])
    if not chips:
        chips = "<span class='r2-chip' style='border-color:#94a3b8'><i style='background:#94a3b8'></i>No outage</span>"
    placeholder = " · placeholder unit values" if any(u.placeholder for u in cfg.units) and controls.show_as == "Plant" else ""
    return (
        f"<div class='r2-tile'><span class='label'>{site_label(site)} · {direction}</span>"
        f"{value_html}<span class='sub'>{pct:.0f}% of {tech:g}{placeholder}</span></div>"
        f"<div class='r2-meter' role='meter' aria-valuemin='0' aria-valuemax='{tech:g}' aria-valuenow='{cur.available:.1f}'"
        f" aria-label='{site_label(site)} {direction} available'><span style='width:{max(0, min(100, pct)):.1f}%'></span></div>"
        f"{next_html}<div class='r2-chips'>{chips}</div>"
    )


def render_panel_card(series: PanelSeries, equipment: EquipmentConfig, controls: Controls, wall: bool = False) -> None:
    key = f"card-{series.site.lower()}-{series.direction.lower()}"
    with st.container(key=key):
        st.markdown(_tile_html(series, equipment, controls), unsafe_allow_html=True)
        mode = "plant" if controls.show_as == "Plant" else "values"
        st.markdown(f"<p class='r2-narr'>{narrate_panel(series, equipment, mode)}</p>", unsafe_allow_html=True)
        st.plotly_chart(panel_figure(series, equipment, controls.patterns, wall), width="stretch",
                        config={"displayModeBar": False, "responsive": True}, key=f"fig-{key}")
        if not wall:
            with st.expander("Table view", expanded=controls.show_tables):
                t = panel_table(series)
                st.dataframe(t, width="stretch", hide_index=True, height=min(400, 38 * (len(t) + 1) + 4))
                st.download_button("Download CSV", t.to_csv(index=False).encode(), mime="text/csv",
                                   file_name=f"availability_{series.site}_{series.direction}.csv", key=f"dl-{key}")
