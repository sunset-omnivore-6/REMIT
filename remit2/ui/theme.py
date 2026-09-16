"""Design tokens and page CSS. Accessibility first: colour-blind-safe cause
palette (Okabe–Ito, validated all-pairs light/dark), WCAG-AA ink, no colour-
only encodings, reduced-motion respected, ≥14 px text, visible focus."""
from __future__ import annotations

import streamlit as st

# Cause lanes — colour AND pattern/word everywhere they appear.
PLANNED = "#0072B2"     # blue
UNPLANNED = "#D55E00"   # vermillion
ADHOC = "#009E73"       # bluish green
INK = "#1e293b"
INK_SOFT = "#475569"
MUTED = "#64748b"
GRID = "#e1e0d9"
NAMEPLATE = "#c3c2b7"
SURFACE = "#ffffff"
PAGE = "#f6f8fb"
BORDER = "#e2e8f0"
FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

LANE_COLOR = {"Planned REMIT": PLANNED, "Unplanned REMIT": UNPLANNED, "Ad-hoc": ADHOC}
LANE_PATTERN = {"Planned REMIT": "/", "Unplanned REMIT": "\\", "Ad-hoc": "."}
LANE_GLYPH = {"Planned REMIT": "▤", "Unplanned REMIT": "▥", "Ad-hoc": "▦"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root {{
  --r2-ink:{INK}; --r2-ink-soft:{INK_SOFT}; --r2-muted:{MUTED}; --r2-border:{BORDER};
  --r2-surface:{SURFACE}; --r2-page:{PAGE}; --r2-planned:{PLANNED}; --r2-unplanned:{UNPLANNED};
  --r2-adhoc:{ADHOC}; --r2-radius:12px;
}}
html, body, .stApp, [data-testid="stMarkdownContainer"] * {{ font-family:{FONT}; }}
.stApp {{ background:var(--r2-page); }}
.block-container {{ padding-top:3.4rem; max-width:1320px; }}
/* Minimum readable text */
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{ font-size:15px; }}
/* Visible keyboard focus everywhere */
button:focus-visible, [role="button"]:focus-visible, a:focus-visible, input:focus-visible,
[data-baseweb="tab"]:focus-visible, summary:focus-visible {{
  outline:3px solid #0072B2 !important; outline-offset:2px !important;
}}
/* Masthead */
.r2-mast {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:baseline; gap:.3rem 1rem; margin-bottom:.4rem; }}
.r2-mast h1 {{ min-width:0; overflow-wrap:normal; }}
.r2-mast h1 {{ font-size:1.35rem; font-weight:600; color:var(--r2-ink); margin:0; }}
.r2-mast .sub {{ color:var(--r2-ink-soft); font-size:.95rem; }}
/* Status banner (fetch / store state) — icon + words, never colour alone */
.r2-banner {{ border:1.5px solid var(--r2-border); border-radius:var(--r2-radius); padding:.6rem .9rem;
  margin:.4rem 0 .8rem; background:var(--r2-surface); font-size:.95rem; color:var(--r2-ink); }}
.r2-banner--warn {{ border-color:#b45309; background:#fffbeb; }}
.r2-banner--bad  {{ border-color:#b91c1c; background:#fef2f2; }}
/* Card = tile header + narrative + chart + table */
[class*="st-key-card-"] {{ background:var(--r2-surface); border:1px solid var(--r2-border);
  border-radius:var(--r2-radius); padding:.9rem 1rem 1rem; box-shadow:0 1px 2px rgba(15,23,42,.05); }}
.r2-tile {{ display:flex; flex-wrap:wrap; align-items:flex-end; gap:.4rem 1.2rem; }}
.r2-tile .label {{ font-size:.95rem; font-weight:600; color:var(--r2-ink); width:100%; }}
.r2-tile .value {{ font-size:1.9rem; font-weight:600; line-height:1; color:var(--r2-ink); font-variant-numeric:tabular-nums; }}
.r2-tile .unit {{ font-size:.95rem; font-weight:500; color:var(--r2-ink-soft); margin-left:.25rem; }}
.r2-tile .sub {{ font-size:.92rem; color:var(--r2-ink-soft); }}
.r2-meter {{ width:100%; height:6px; background:#e5e7eb; border-radius:6px; overflow:hidden; margin-top:.35rem; }}
.r2-meter > span {{ display:block; height:100%; background:#475569; border-radius:6px; }}
.r2-next {{ font-size:.92rem; color:var(--r2-ink-soft); margin-top:.4rem; }}
.r2-next b {{ font-weight:600; color:var(--r2-ink); }}
.r2-chips {{ display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.45rem; }}
.r2-chip {{ display:inline-flex; align-items:center; gap:.35rem; font-size:.8rem; font-weight:500;
  padding:.15rem .55rem; border-radius:999px; border:1.5px solid; color:var(--r2-ink); background:var(--r2-surface); }}
.r2-chip i {{ display:inline-block; width:.8rem; height:.8rem; border-radius:3px; }}
.r2-narr {{ font-size:1rem; color:var(--r2-ink); margin:.55rem 0 .2rem; line-height:1.45; }}
.r2-foot {{ font-size:.82rem; color:var(--r2-muted); margin-top:.3rem; }}
/* Register strip */
.r2-strip {{ display:flex; flex-wrap:wrap; gap:.5rem 1rem; align-items:center; border:1.5px solid var(--r2-border);
  border-radius:var(--r2-radius); background:var(--r2-surface); padding:.6rem .9rem; margin:.3rem 0 .9rem; font-size:.95rem; }}
.r2-strip b {{ font-weight:600; }}
.r2-strip .stat {{ padding:.15rem .55rem; border-radius:8px; background:#f1f5f9; }}
/* Section header */
.r2-sec {{ font-size:1.05rem; font-weight:600; color:var(--r2-ink); margin:.4rem 0 .2rem; }}
/* Plain list rows (recent / upcoming) */
.r2-row {{ display:flex; flex-wrap:wrap; gap:.4rem .8rem; align-items:baseline; padding:.45rem 0; border-bottom:1px solid var(--r2-border); font-size:.95rem; }}
.r2-row .k {{ font-weight:600; }}
.r2-row .m {{ color:var(--r2-ink-soft); }}
/* Motion: nothing animates when the user asks for reduced motion */
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
/* Wall-display mode: bigger text, no chrome */
body.r2-wall .r2-tile .value {{ font-size:2.6rem; }}
body.r2-wall header, body.r2-wall [data-testid="stToolbar"] {{ display:none; }}
@media (max-width: 640px) {{ .r2-tile .value {{ font-size:1.7rem; }} .block-container {{ padding-left:14px; padding-right:14px; }} }}
</style>
"""


WALL_CSS = """
<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }
.block-container { padding-top:.8rem; max-width:1800px; }
.r2-tile .value { font-size:2.6rem; }
.r2-narr { font-size:1.15rem; }
</style>
"""


def inject_css(wall: bool = False) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if wall:
        st.markdown(WALL_CSS, unsafe_allow_html=True)   # scripts never run inside st.markdown; CSS does


def chip(label: str, color: str) -> str:
    """Cause chip: swatch + word (never colour alone)."""
    return f"<span class='r2-chip' style='border-color:{color}'><i style='background:{color}'></i>{label}</span>"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
