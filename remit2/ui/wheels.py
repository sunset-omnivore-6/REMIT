"""Glance wheels (design review B2): one wheel per site/measure answering
"are we OK?" from fill level, state colour and the number in the middle.

States — a decision, not a gradient (agreed defaults):
    Full     ≥ 99.95% of maximum   slate ring (no colour when nothing is wrong)
    Reduced  50% to just under     gold (light mode adds a dark edge for 3:1)
    Severe   above 0, below 50%    raspberry (never red: it must not read as Unplanned)
    Out      exactly 0             empty ring tinted raspberry
    Stale    data older than 15 min grey dashed ring; the wall shows a banner
Each state also carries a word and an icon, so colour never works alone.
Solid colour = how much is left; the charts keep hatched cause colours = why.

Pure HTML/SVG strings (no Plotly): crisp at any size. The SVG <title> gives
the hover breakdown; aria-label gives the screen-reader sentence.
"""
from __future__ import annotations

import html
import math

import pandas as pd

from ..adhoc.combine import PanelSeries, lost_parts
from ..adhoc.narrate import ChangeEvent
from ..adhoc.units import q as fq, unit_of
from ..core.constants import site_label
from .hero import day_label, part_ids, rel_label, time_label

SEVERE_BELOW = 0.5          # Severe below 50% of maximum
FULL_AT = 0.9995            # Full at (effectively) 100%
STALE_AFTER_MIN = 15        # data older than this greys the wheels and raises the wall banner
WORD = {"full": "Full", "reduced": "Reduced", "severe": "Severe", "out": "Out", "stale": "Stale"}
MEASURES = ("Withdrawal", "Injection", "Storage")
WALL_LIST_N = 2             # changes listed under each wall chart; only these get numbered badges


def state_of(available: float, tech: float, stale: bool = False) -> str:
    if stale:
        return "stale"
    if available <= 1e-6:
        return "out"
    f = available / tech if tech else 0.0
    if f >= FULL_AT:
        return "full"
    return "severe" if f < SEVERE_BELOW else "reduced"


def pct_text(available: float, tech: float) -> str:
    """Whole percent; never shows 100 unless full, nor 0 unless out."""
    f = available / tech if tech else 0.0
    if f >= FULL_AT:
        return "100"
    if available <= 1e-6:
        return "0"
    return str(max(1, min(99, round(f * 100))))


def data_age_min(fetched_at, now: pd.Timestamp) -> float | None:
    if fetched_at is None:
        return None
    return (now - pd.Timestamp(fetched_at)) / pd.Timedelta(minutes=1)


def is_stale(fetched_at, now: pd.Timestamp) -> bool:
    age = data_age_min(fetched_at, now)
    return age is None or age > STALE_AFTER_MIN


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def _r(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def arc_path(cx: float, cy: float, r: float, f: float) -> str:
    """SVG arc from 12 o'clock clockwise through fraction f (0 < f < 1)."""
    a0 = -math.pi / 2
    a1 = a0 + f * 2 * math.pi
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    return f"M{_r(x0)} {_r(y0)}A{_r(r)} {_r(r)} 0 {1 if f > 0.5 else 0} 1 {_r(x1)} {_r(y1)}"


def state_icon(state: str, t: dict, size: int = 14) -> str:
    s = f"<svg class='g-ico' width='{size}' height='{size}' viewBox='0 0 16 16' aria-hidden='true'>"
    cut = t["cut"]
    if state == "full":
        c = t["st_full"]
        return s + (f"<circle cx='8' cy='8' r='6.6' fill='none' stroke='{c}' stroke-width='1.8'/>"
                    f"<path d='M5 8.3l2 2 4-4.3' fill='none' stroke='{c}' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>")
    if state == "reduced":
        edge = f" stroke='{t['st_edge']}' stroke-width='1.2'" if t.get("st_edge") else ""
        return s + f"<path d='M8 1.6L14.4 8 8 14.4 1.6 8z' fill='{t['st_reduced']}'{edge}/></svg>"
    if state == "severe":
        return s + (f"<path d='M8 1.4L15 14.2H1z' fill='{t['st_severe']}'/>"
                    f"<rect x='7.15' y='5.6' width='1.7' height='4.6' rx='.8' fill='{cut}'/><circle cx='8' cy='12.1' r='.95' fill='{cut}'/></svg>")
    if state == "out":
        return s + (f"<circle cx='8' cy='8' r='7' fill='{t['st_severe']}'/>"
                    f"<path d='M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2' stroke='{cut}' stroke-width='1.8' stroke-linecap='round'/></svg>")
    c = t["st_stale"]
    return s + (f"<circle cx='8' cy='8' r='6.6' fill='none' stroke='{c}' stroke-width='1.8'/>"
                f"<path d='M8 4.6V8l2.4 1.6' fill='none' stroke='{c}' stroke-width='1.8' stroke-linecap='round'/></svg>")


def wheel_svg(available: float, tech: float, t: dict, *, unit: str = "", direction: str = "Withdrawal", d: int = 112,
              next_frac: float | None = None, stale: bool = False, sub: bool = True, label: str = "") -> str:
    """The glance wheel: track (what's missing), quarter ticks, solid state arc,
    optional next-change notch, % in ink with the exact value beneath."""
    k = state_of(available, tech, stale)
    w = max(7, round(d * 0.092))
    pad = round(d * 0.085)
    W = d + 2 * pad
    c = W / 2
    r = (d - w) / 2
    f = max(0.0, min(1.0, available / tech if tech else 0.0))
    g: list[str] = []
    track = _rgba(t["st_severe"], 0.22 if t["cut"] == "#ffffff" else 0.3) if k == "out" else t["wtrack"]
    dash = " stroke-dasharray='3 3'" if k == "stale" else ""
    g.append(f"<circle class='g-track' cx='{_r(c)}' cy='{_r(c)}' r='{_r(r)}' fill='none' stroke='{track}' stroke-width='{w}'{dash}/>")
    for q in (0, 0.25, 0.5, 0.75):
        a = -math.pi / 2 + q * 2 * math.pi
        r0 = r + w / 2 + 2.5
        r1 = r0 + max(4, d * 0.04)
        g.append(f"<line x1='{_r(c + r0 * math.cos(a))}' y1='{_r(c + r0 * math.sin(a))}' x2='{_r(c + r1 * math.cos(a))}' "
                 f"y2='{_r(c + r1 * math.sin(a))}' stroke='{t['wtick']}' stroke-width='1.2'/>")
    col = t["st_stale"] if k == "stale" else (t["st_severe"] if k == "out" else t[f"st_{k}"])
    if f > 0.0005:
        full = f >= FULL_AT

        def shape(sw: float, stroke: str, cls: str) -> str:
            if full:
                return f"<circle class='{cls}' cx='{_r(c)}' cy='{_r(c)}' r='{_r(r)}' fill='none' stroke='{stroke}' stroke-width='{_r(sw)}'/>"
            return (f"<path class='{cls}' d='{arc_path(c, c, r, f)}' fill='none' stroke='{stroke}' stroke-width='{_r(sw)}' "
                    f"stroke-linecap='round'/>")
        if k == "reduced" and t.get("st_edge"):
            g.append(shape(w + 2.2, t["st_edge"], "g-edge"))
            g.append(shape(w - 0.6, col, "g-arc"))
        else:
            g.append(shape(w, col, "g-arc"))
    if next_frac is not None and k != "stale":
        a = -math.pi / 2 + max(0.0, min(1.0, next_frac)) * 2 * math.pi
        ro = r + w / 2 + 3
        s = max(4.5, d * 0.045)
        tx, ty = c + ro * math.cos(a), c + ro * math.sin(a)
        base = ro + s * 1.7
        bx, by = c + base * math.cos(a), c + base * math.sin(a)
        px, py = -math.sin(a) * s, math.cos(a) * s
        g.append(f"<path class='g-next-mark' d='M{_r(tx)} {_r(ty)}L{_r(bx + px)} {_r(by + py)}L{_r(bx - px)} {_r(by - py)}Z' "
                 f"fill='{t['ink']}' stroke='{t['wbg']}' stroke-width='1.5' stroke-linejoin='round'/>")
    fs, fsp, fss = round(d * 0.26), round(d * 0.13), max(10, round(d * 0.098))
    ty = c + fs * 0.18 - (fss * 0.35 if sub else -fs * 0.12)
    ink = t["ink3"] if k == "stale" else t["ink"]
    g.append(f"<text x='{_r(c)}' y='{_r(ty)}' text-anchor='middle' fill='{ink}'><tspan font-size='{fs}' font-weight='600'>"
             f"{pct_text(available, tech)}</tspan><tspan font-size='{fsp}' font-weight='600' dx='1' dy='{_r(-fs * 0.32)}'>%</tspan></text>")
    if sub:
        g.append(f"<text x='{_r(c)}' y='{_r(ty + fss * 1.45)}' text-anchor='middle' font-size='{fss}' fill='{t['ink2']}'>"
                 f"{fq(available, direction)} of {tech:g}</text>")
    lab = html.escape(label or f"{WORD[k]}, {pct_text(available, tech)}% ({fq(available, direction)} of {tech:g} {unit})", quote=True)
    return (f"<svg class='g-wheel g-wheel--{k}' width='{W}' height='{W}' viewBox='0 0 {W} {W}' role='img' aria-label='{lab}'>"
            f"<title>{lab}</title>{''.join(g)}</svg>")


# ---------------------------------------------------------------------------
# Words around the wheel
# ---------------------------------------------------------------------------

def cause_short(series: PanelSeries) -> str:
    cur = series.segment_at(series.now)
    if cur is None:
        return ""
    parts = lost_parts(cur.state)
    if not parts:
        return ""
    return "REMIT + ad-hoc" if len(parts) > 1 else parts[0].lane


def breakdown(series: PanelSeries, equipment) -> str:
    """Hover text: every cause at this moment with its size."""
    cur = series.segment_at(series.now)
    if cur is None:
        return ""
    d, u = series.direction, unit_of(series.direction)
    head = f"{site_label(series.site)} {d.lower()}: {fq(cur.available, d)} of {series.tech:g} {u} ({pct_text(cur.available, series.tech)}%)"
    parts = lost_parts(cur.state)
    if not parts:
        return head + " · full capacity"
    return head + " · " + "; ".join(f"{p.lane} {part_ids(p, series, equipment, cur.state)} −{fq(p.amount, d)}".replace("  ", " ")
                                    for p in parts)


def next_line(series: PanelSeries, events: list[ChangeEvent], long: bool = False, cls: str = "g-next") -> str:
    if not events:
        days = max(1, (series.window[1] - series.now).days)
        return f"<div class='{cls}'>No change in the next {days} days</div>"
    ev = events[0]
    lvl = "Full" if abs(ev.available - series.tech) < 1e-6 else pct_text(ev.available, series.tech) + "%"
    arrow = "▼" if ev.delta < 0 else "▲"
    rel = rel_label(ev.at, series.now)
    when = (f"{day_label(ev.at)} {time_label(ev.at)} · {rel}" if long
            else (f"{rel} {time_label(ev.at)}" if rel in ("today", "tomorrow") else f"{day_label(ev.at)} {time_label(ev.at)}"))
    return f"<div class='{cls}'>Next <b>{arrow} {lvl}</b> · {when}</div>"


def state_line(series: PanelSeries, t: dict, stale: bool = False, icon: int = 14) -> str:
    cur = series.segment_at(series.now)
    k = state_of(cur.available if cur else 0.0, series.tech, stale)
    why = "" if stale else cause_short(series)
    return (f"<div class='g-st'>{state_icon(k, t, icon)}<b>{WORD[k]}</b>"
            + (f"<span class='g-why'>· {why}</span>" if why else "") + "</div>")


def glance_unit(series: PanelSeries, events: list[ChangeEvent], equipment, t: dict, *, d: int = 112, stale: bool = False,
                sub: bool = True) -> str:
    cur = series.segment_at(series.now)
    avail = cur.available if cur else 0.0
    nxt = events[0].available / series.tech if events and not stale else None
    wheel = wheel_svg(avail, series.tech, t, unit=unit_of(series.direction), direction=series.direction, d=d, next_frac=nxt,
                      stale=stale, sub=sub, label=breakdown(series, equipment) + (" · data stale" if stale else ""))
    return (f"<div class='g-unit'><div class='g-lab'>{series.direction}</div>{wheel}"
            f"{state_line(series, t, stale)}{next_line(series, events)}</div>")


def strip_html(panels: dict, events: dict, equipment, t: dict, *, stale: bool = False) -> str:
    """Six wheels under the toolbar: one panel per site (on its plot tint), measures in row order."""
    out = []
    for site in ("Atwick", "Aldbrough"):
        units = "".join(glance_unit(panels[(site, m)], events[(site, m)], equipment, t, stale=stale) for m in MEASURES)
        out.append(f"<section class='g-site g-site--{site.lower()}'><header class='g-hd'><b>{site_label(site)}</b>"
                   f"<span>{site} storage</span></header><div class='g-row'>{units}</div></section>")
    return f"<div class='g-strip'>{''.join(out)}</div>"


# ---------------------------------------------------------------------------
# Wall board pieces (the charts between them are Plotly, placed by page.py)
# ---------------------------------------------------------------------------

def wall_cell_top(series: PanelSeries, events: list[ChangeEvent], equipment, t: dict, stale: bool) -> str:
    cur = series.segment_at(series.now)
    avail = cur.available if cur else 0.0
    d, u = series.direction, unit_of(series.direction)
    nxt = events[0].available / series.tech if events and not stale else None
    wheel = wheel_svg(avail, series.tech, t, unit=u, direction=d, d=156, next_frac=nxt, stale=stale,
                      label=breakdown(series, equipment) + (" · data stale" if stale else ""))
    return (f"<div class='wb-top'>{wheel}<div class='wb-txt'><div class='wb-lab'>{d}</div>"
            f"<div class='wb-val'>{fq(avail, d)}<span>/ {series.tech:g} {u}</span></div>"
            f"{state_line(series, t, stale, icon=16)}{next_line(series, events, long=True, cls='wb-next')}</div></div>")


def wall_cell_list(series: PanelSeries, events: list[ChangeEvent]) -> str:
    if not events:
        return "<ol class='wb-up'><li><span></span><span>No changes in the next 30 days</span></li></ol>"
    d = series.direction
    items = "".join(
        f"<li><span class='num'>{e.n}</span><b>{day_label(e.at)} {time_label(e.at)} &nbsp;{'▼' if e.delta < 0 else '▲'} "
        f"{fq(e.available, d)}</b><span>{html.escape(e.why)}</span></li>" for e in events[:WALL_LIST_N])
    return f"<ol class='wb-up'>{items}</ol>"


def stale_banner(fetched_at, now: pd.Timestamp, t: dict) -> str:
    age = data_age_min(fetched_at, now)
    if fetched_at is None:
        return (f"<div class='wb-banner'>{state_icon('reduced', t, 18)}No data has arrived yet."
                f"<span>The board fills in as soon as the feed answers. Retrying every minute.</span></div>")
    loc = pd.Timestamp(fetched_at).tz_convert("Europe/London")
    return (f"<div class='wb-banner'>{state_icon('reduced', t, 18)}Data is {int(age)} minutes old — the feed is not updating."
            f"<span>Showing the last good data from {loc.strftime('%H:%M')} {loc.strftime('%Z')}. Retrying every minute.</span></div>")


def state_keys(t: dict) -> str:
    return ("<div class='wb-keys'>" + "".join(f"<span>{state_icon(k, t, 14)}{WORD[k]}</span>" for k in ("full", "reduced", "severe", "out"))
            + "</div>")
