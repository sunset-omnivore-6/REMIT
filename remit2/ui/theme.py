"""Design tokens and page CSS.

Direction: an editorial, low-chrome page — hairline rules instead of boxes,
one type family (IBM Plex Sans) at restrained weights, tabular numbers, and
colour reserved for meaning (the three causes). Accessibility: Okabe–Ito cause
palette (validated all-pairs light/dark), always hatched as well as coloured,
WCAG-AA ink, visible focus, reduced motion respected, a screen-reader
sentence per chart."""
from __future__ import annotations

import streamlit as st

PLANNED = "#0072B2"     # blue
UNPLANNED = "#D55E00"   # vermillion
ADHOC = "#009E73"       # bluish green
INK = "#1e293b"
INK_SOFT = "#5b6475"
MUTED = "#8a93a3"
RULE = "#e3e5e8"
GRID = "#eceef1"
NAMEPLATE = "#b9bfc9"
SURFACE = "#ffffff"
PAGE = "#fcfcfb"
FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

LANE_COLOR = {"Planned REMIT": PLANNED, "Unplanned REMIT": UNPLANNED, "Ad-hoc": ADHOC}
LANE_PATTERN = {"Planned REMIT": "/", "Unplanned REMIT": "\\", "Ad-hoc": "."}
LANE_CLASS = {"Planned REMIT": "sw-planned", "Unplanned REMIT": "sw-unplanned", "Ad-hoc": "sw-adhoc"}


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _hatch(color: str, angle: int) -> str:
    return (f"background:repeating-linear-gradient({angle}deg,{color} 0 1.5px,{rgba(color, .22)} 1.5px 4px);"
            f"box-shadow:inset 0 0 0 1px {rgba(color, .55)};")


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body, .stApp, [data-testid="stMarkdownContainer"] *, button, input {{ font-family:{FONT}; }}
.stApp {{ background:{PAGE}; }}
.block-container {{ padding:3.4rem 2.4rem 3rem; max-width:100%; }}
[data-testid="stMarkdownContainer"] p {{ font-size:15px; }}
button:focus-visible, [role="button"]:focus-visible, a:focus-visible, input:focus-visible,
summary:focus-visible {{ outline:3px solid {PLANNED} !important; outline-offset:2px !important; }}

/* Title line */
.r2-title {{ display:flex; flex-direction:column; gap:.15rem; }}
.r2-title h1 {{ font-size:1.45rem; font-weight:600; color:{INK}; margin:0; padding:0; letter-spacing:-.005em; }}
.r2-title h1 span {{ color:{INK_SOFT}; font-weight:400; }}
.r2-title .fresh {{ font-size:.88rem; color:{INK_SOFT}; font-variant-numeric:tabular-nums; }}
.r2-title .fresh b {{ font-weight:500; color:{INK}; }}
.r2-title .tag {{ font-size:.72rem; letter-spacing:.06em; color:#9a3412; border:1px solid #fdba74; border-radius:3px; padding:.05rem .35rem; margin-left:.4rem; }}

/* Toolbar: one ruled line holding view controls, key and ad-hoc actions */
[class*="st-key-r2toolbar"] {{ border-top:1px solid {RULE}; border-bottom:1px solid {RULE}; padding:.35rem 0 .35rem; margin:.5rem 0 .2rem; }}
.r2-lbl {{ font-size:.85rem; color:{INK_SOFT}; white-space:nowrap; padding-top:.45rem; }}
.r2-key {{ display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.25rem 1.1rem; font-size:.84rem; color:{INK_SOFT}; margin:.9rem 0 -.6rem; }}
.r2-adhoc {{ font-size:.9rem; color:{INK}; text-align:right; line-height:1.3; padding-top:.15rem; font-variant-numeric:tabular-nums; }}
.r2-adhoc .n {{ font-weight:600; }}
.r2-adhoc .sub {{ display:block; font-size:.78rem; color:{INK_SOFT}; }}
.r2-adhoc .warn {{ color:#9a3412; }}

/* Swatches (legend + status): colour AND hatch */
.sw {{ display:inline-block; width:.95rem; height:.7rem; border-radius:1px; margin-right:.35rem; vertical-align:-1px; }}
.sw-planned {{ {_hatch(PLANNED, 45)} }}
.sw-unplanned {{ {_hatch(UNPLANNED, -45)} }}
.sw-adhoc {{ background:radial-gradient({ADHOC} 1px, {rgba(ADHOC, .2)} 1.3px) 0 0/4px 4px; box-shadow:inset 0 0 0 1px {rgba(ADHOC, .55)}; }}
.sw-none {{ background:#e5e7eb; box-shadow:inset 0 0 0 1px #cbd0d6; }}

/* Site sections */
.r2-site {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.2rem 1.2rem; margin:1.6rem 0 0; }}
.r2-site h2 {{ font-size:1.2rem; font-weight:600; color:{INK}; margin:0; padding:0; }}
.r2-site .sum {{ font-size:.9rem; color:{INK_SOFT}; font-variant-numeric:tabular-nums; }}
.r2-site .sum b {{ font-weight:500; color:{INK}; }}
[class*="st-key-card-"] {{ border-top:1px solid {RULE}; padding-top:.7rem; margin-top:.35rem; }}

/* Numbers column */
.r2-num .dir {{ font-size:.9rem; font-weight:500; color:{INK_SOFT}; }}
.r2-num .val {{ white-space:nowrap; font-size:2.05rem; font-weight:500; color:{INK}; line-height:1.1; font-variant-numeric:tabular-nums; letter-spacing:-.01em; }}
.r2-num .val--text {{ white-space:normal; font-size:1.12rem; line-height:1.3; font-weight:500; margin:.2rem 0; letter-spacing:0; }}
.r2-num .unit {{ font-size:.85rem; font-weight:400; color:{INK_SOFT}; margin-left:.3rem; letter-spacing:0; }}
.r2-num .of {{ font-size:.85rem; color:{INK_SOFT}; font-variant-numeric:tabular-nums; }}
.r2-num .note {{ font-size:.78rem; color:#9a3412; margin-top:.2rem; }}
.r2-meter {{ width:100%; max-width:11rem; height:4px; background:#e8eaee; margin:.45rem 0 .5rem; }}
.r2-meter > span {{ display:block; height:100%; background:{INK}; }}
.r2-stline {{ display:flex; flex-direction:column; gap:.15rem; }}
.r2-status {{ font-size:.85rem; color:{INK}; white-space:nowrap; }}

/* Coming up column */
.r2-up .hd {{ font-size:.78rem; color:{MUTED}; letter-spacing:.04em; margin-bottom:.25rem; }}
.r2-up ul {{ list-style:none; margin:0; padding:0; }}
.r2-up li {{ display:grid; grid-template-columns:1rem 3.1rem 1fr; column-gap:.3rem; font-size:.86rem; color:{INK};
  padding:.18rem 0; border-bottom:1px dotted {RULE}; font-variant-numeric:tabular-nums; }}
.r2-up li .w {{ grid-column:2 / 4; font-size:.76rem; color:{INK_SOFT}; overflow-wrap:anywhere; }}
.r2-up li .t {{ color:{INK_SOFT}; white-space:nowrap; font-size:.82rem; }}
.r2-up .dn {{ color:{UNPLANNED}; }} .r2-up .upv {{ color:{ADHOC}; }}
.r2-up .none, .r2-up .more {{ font-size:.85rem; color:{INK_SOFT}; }}

/* Screen-reader-only sentence (the chart's text twin) */
.r2-sr {{ position:absolute !important; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}

/* Banners and secondary sections: rules, not boxes */
.r2-banner {{ border-left:3px solid {RULE}; padding:.4rem .8rem; margin:.5rem 0; font-size:.93rem; color:{INK}; background:transparent; }}
.r2-banner--warn {{ border-left-color:#d97706; }} .r2-banner--bad {{ border-left-color:#b91c1c; }} .r2-banner--info {{ border-left-color:{PLANNED}; }}
[data-testid="stExpander"] details {{ border:none !important; border-top:1px solid {RULE} !important; border-radius:0 !important; background:transparent !important; }}
[data-testid="stExpander"] summary {{ padding-left:0 !important; font-weight:500; }}
.r2-sec {{ font-size:1.05rem; font-weight:600; color:{INK}; margin:2rem 0 .2rem; }}
.r2-row {{ display:flex; flex-wrap:wrap; gap:.4rem .8rem; align-items:baseline; padding:.4rem 0; border-bottom:1px solid {RULE}; font-size:.93rem; }}
.r2-row .k {{ font-weight:500; }} .r2-row .m {{ color:{INK_SOFT}; }}
.r2-foot {{ font-size:.8rem; color:{MUTED}; margin-top:1.2rem; }}

@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
@media (max-width: 1400px) {{ .r2-num .val {{ font-size:1.75rem; }} }}
@media (max-width: 640px) {{ .r2-lbl--days {{ display:none; }} .block-container {{ padding-left:14px; padding-right:14px; }} .r2-adhoc {{ text-align:left; }} }}
</style>
"""

WALL_CSS = """
<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }
.block-container { padding-top:1rem; }
.r2-num .val { font-size:2.6rem; }
.r2-up li { font-size:1rem; }
</style>
"""


def inject_css(wall: bool = False) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if wall:
        st.markdown(WALL_CSS, unsafe_allow_html=True)   # scripts never run inside st.markdown; CSS does


def key_html() -> str:
    """The one legend for every chart on the page."""
    items = [("sw-planned", "Planned REMIT"), ("sw-unplanned", "Unplanned REMIT"), ("sw-adhoc", "Ad-hoc"), ("sw-none", "No outage")]
    return "<div class='r2-key'>" + "".join(f"<span><i class='sw {c}'></i>{t}</span>" for c, t in items) + "</div>"


def chip(label: str, color: str) -> str:   # kept for compatibility
    return f"<span class='r2-status'><i class='sw {LANE_CLASS.get(label, 'sw-none')}'></i>{label}</span>"
