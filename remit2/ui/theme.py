"""Design tokens and page CSS (design review rev A, sheets 01–06).

One type family (IBM Plex Sans), one scale — 34 / 28 / 20 / 15 / 13 / 12 px —
and two weights (400, 600). Colour has one job each: ink for text, lines and
buttons; the three cause colours for DATA ONLY (always hatched as well as
coloured); grey for anything before now; the site bands and plot tints for
place; green/amber/red for feed status only, always with a word.

Two token sets: LIGHT (desktop, phone) and DARK (the wall screen, ?mode=wall).
The dark cause colours are re-stepped for the dark ground — never the light
ones on black — and validated all-pairs (CVD ΔE ≥ 10, normal ΔE ≥ 16,
contrast ≥ 5:1 against every dark surface). Cause colours never carry text.
"""
from __future__ import annotations

import streamlit as st

FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

LIGHT = dict(
    page="#f5f5f2", card="#ffffff", ink="#1c2430", ink2="#566070", ink3="#838c9a", on_ink="#ffffff",
    rule="rgba(28,36,48,.13)", rule2="rgba(28,36,48,.08)",
    grid="rgba(28,36,48,.055)", grid_mon="rgba(28,36,48,.14)", axis="rgba(28,36,48,.24)", nameplate="rgba(28,36,48,.34)",
    avail="rgba(28,36,48,.055)", avail_past="rgba(28,36,48,.03)", avail_sw="#dde2e8",
    ink_past="#a3abb6", past="#8e98a5",
    planned="#0072B2", unplanned="#D55E00", adhoc="#009E73",
    good="#1f8f3a", warn="#b45309", bad="#c62828", focus="#1c2430",
    band={"Atwick": "#e9eef2", "Aldbrough": "#f1ece3"},
    plot={"Atwick": "#f1f6fb", "Aldbrough": "#fcf4ea"},
)

DARK = dict(
    page="#0c1015", card="#161c23", ink="#e8edf2", ink2="#9ea9b5", ink3="#7c8794", on_ink="#0c1015",
    rule="rgba(232,237,242,.13)", rule2="rgba(232,237,242,.07)",
    grid="rgba(232,237,242,.06)", grid_mon="rgba(232,237,242,.14)", axis="rgba(232,237,242,.2)", nameplate="rgba(232,237,242,.34)",
    avail="rgba(232,237,242,.07)", avail_past="rgba(232,237,242,.04)", avail_sw="#2a323c",
    ink_past="#5d6773", past="#5d6773",
    # Re-stepped for dark: lighter blue so Planned never sinks into the ground.
    planned="#459cdd", unplanned="#e06f36", adhoc="#1dab80",
    good="#3fbf62", warn="#f0a340", bad="#ff6b6b", focus="#e8edf2",
    band={"Atwick": "#111820", "Aldbrough": "#1a1612"},
    plot={"Atwick": "#18202a", "Aldbrough": "#221d17"},
)

LANE_KEY = {"Planned REMIT": "planned", "Unplanned REMIT": "unplanned", "Ad-hoc": "adhoc"}
LANE_PATTERN = {"planned": "/", "unplanned": "\\", "adhoc": "."}


def tokens(wall: bool = False) -> dict:
    return DARK if wall else LIGHT


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _hatch_css(color: str, angle: int) -> str:
    return f"background:repeating-linear-gradient({angle}deg,{color} 0 1.6px,{rgba(color, .17)} 1.6px 4.2px);"


def _dots_css(color: str) -> str:
    return f"background:radial-gradient({color} 1.15px, {rgba(color, .17)} 1.35px) 0 0/5px 5px;"


def swatch(key: str, past: bool = False) -> str:
    """Inline legend/status swatch. key: planned | unplanned | adhoc | avail."""
    cls = "sw-avail" if key == "avail" else f"sw-{'past-' if past else ''}{key}"
    return f"<i class='sw {cls}' aria-hidden='true'></i>"


def _css(t: dict, wall: bool) -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=swap');
html, body, .stApp, [data-testid="stMarkdownContainer"] *, button, input, textarea {{ font-family:{FONT}; }}
.stApp {{ background:{t['page']}; color:{t['ink']}; }}
.block-container {{ padding:{'1.4rem 3rem 1rem' if wall else '2rem 2.5rem 3rem'}; max-width:100%; }}
[data-testid="stMarkdownContainer"] p {{ font-size:15px; }}
button:focus-visible, [role="button"]:focus-visible, a:focus-visible, input:focus-visible,
summary:focus-visible, [tabindex]:focus-visible {{ outline:2px solid {t['focus']} !important; outline-offset:2px !important; }}
header[data-testid="stHeader"] {{ background:transparent; }}

/* ---- Masthead: kicker · 34/600 title · one-line lede | live status ---- */
.r2-kicker {{ font-size:13px; color:{t['ink2']}; margin-bottom:6px; }}
[data-testid="stMarkdownContainer"] h1.r2-h1, .r2-h1 {{ font-size:34px; font-weight:600; line-height:1.08; letter-spacing:-.018em; color:{t['ink']}; margin:0; padding:0; }}
.r2-lede {{ font-size:15px; color:{t['ink2']}; margin:8px 0 0; }}
.r2-live {{ display:flex; justify-content:flex-end; align-items:center; gap:8px; font-size:13px; color:{t['ink2']};
  white-space:nowrap; font-variant-numeric:tabular-nums; }}
.r2-live b {{ font-weight:600; color:{t['ink']}; }}
.r2-live .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.r2-live--live .dot {{ background:{t['good']}; box-shadow:0 0 0 3px {rgba(t['good'], .2)}; }}
.r2-live--stale .dot {{ background:{t['warn']}; }} .r2-live--stale b {{ color:{t['warn']}; }}
.r2-live--bad .dot {{ background:{t['bad']}; }} .r2-live--bad b {{ color:{t['bad']}; }}
.r2-live--sample .dot {{ background:{t['ink3']}; }}
.r2-sub {{ font-size:12px; color:{t['ink3']}; text-align:right; margin-top:4px; }}
.st-key-r2mast [data-testid="stHorizontalBlock"] {{ align-items:flex-end; }}
.st-key-r2live [data-testid="stHorizontalBlock"] {{ gap:.25rem; flex-wrap:nowrap; justify-content:flex-end; align-items:center; }}
.st-key-r2live [data-testid="stColumn"] {{ flex:0 0 auto !important; width:auto !important; min-width:0 !important; }}
.st-key-r2live button {{ min-height:28px; height:28px; width:28px; padding:0; border:1px solid {t['rule']}; background:{t['card']}; color:{t['ink2']}; }}

/* ---- Toolbar: one ruled row — days · Values/Plant · legend · ad-hoc chip · New ---- */
.st-key-r2toolbar {{ border-top:1px solid {t['rule']}; border-bottom:1px solid {t['rule']}; padding:6px 0; margin:14px 0 22px; }}
.st-key-r2toolbar [data-testid="stHorizontalBlock"] {{ align-items:center; flex-wrap:nowrap; row-gap:6px; }}
.st-key-r2toolbar [data-testid="stColumn"] {{ flex:0 0 auto !important; width:auto !important; min-width:0 !important; }}
.st-key-r2toolbar [data-testid="stColumn"]:has(.r2-legend) {{ flex:0 1 auto !important; min-width:0 !important; }}
.st-key-r2toolbar [data-testid="stColumn"]:has([class*="st-key-r2chip"]) {{ margin-left:auto; }}
.st-key-r2toolbar [data-testid="stButtonGroup"] button {{ min-height:32px; padding:0 12px; }}
.st-key-r2toolbar [data-testid="stButtonGroup"] button p {{ font-size:13px; }}
.st-key-r2toolbar input {{ font-size:15px; }}
.st-key-r2toolbar [data-testid="stNumberInput"] {{ width:104px; }}
.r2-lbl {{ font-size:13px; color:{t['ink2']}; white-space:nowrap; }}
.r2-legend {{ display:flex; flex-wrap:wrap; gap:4px 16px; font-size:13px; color:{t['ink2']}; padding-left:18px;
  border-left:1px solid {t['rule']}; align-items:center; }}
.r2-legend span {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }}
[class*="st-key-r2chip"] button {{ min-height:32px; padding:0 12px; font-size:13px; border:1px solid {t['rule']};
  background:{t['card']}; color:{t['ink']}; white-space:nowrap; }}
[class*="st-key-r2chip"] button p {{ font-size:13px; }}
[class*="st-key-r2chip"] button::before {{ content:""; width:18px; height:11px; margin-right:8px; border-radius:2px; {_dots_css(t['adhoc'])} }}
.st-key-r2chip_review button {{ color:{t['warn']}; border-color:{rgba(t['warn'], .55)}; }}
.st-key-r2new button {{ min-height:32px; padding:0 14px; white-space:nowrap; }}
.st-key-r2new button p {{ font-size:13px; font-weight:600; }}

/* ---- Swatches: colour AND hatch (45° planned, 135° unplanned, dots ad-hoc) ---- */
.sw {{ display:inline-block; width:18px; height:11px; border-radius:2px; flex:none; vertical-align:-1px; }}
.sw-planned {{ {_hatch_css(t['planned'], 45)} }}
.sw-unplanned {{ {_hatch_css(t['unplanned'], -45)} }}
.sw-adhoc {{ {_dots_css(t['adhoc'])} }}
.sw-past-planned, .sw-past-unplanned {{ {_hatch_css(t['past'], 45)} }}
.sw-past-adhoc {{ {_dots_css(t['past'])} }}
.sw-avail {{ background:{t['avail_sw']}; }}

/* ---- Site bands (full bleed) ---- */
[class*="st-key-site-"] {{ margin:0 -{'3rem' if wall else '2.5rem'}; padding:{'12px 3rem 8px' if wall else '18px 2.5rem 16px'};
  width:calc(100% + {'6rem' if wall else '5rem'}) !important; max-width:none !important; }}
.st-key-site-atwick {{ background:{t['band']['Atwick']}; }}
.st-key-site-aldbrough {{ background:{t['band']['Aldbrough']}; margin-top:-1rem; }}
.r2-sitehead {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 14px; }}
.r2-sitehead h2 {{ font-size:{'24px' if wall else '20px'}; font-weight:600; color:{t['ink']}; margin:0; padding:0; letter-spacing:-.005em; }}
.r2-sitemeta {{ font-size:{'14px' if wall else '13px'}; color:{t['ink2']}; }}
[class*="st-key-card-"] {{ border-top:1px solid {t['rule2']}; padding-top:10px; margin-top:4px; }}
[class*="st-key-card-"][class*="-withdrawal"] {{ border-top:0; }}

/* ---- Headline block: now · cause · next ---- */
.r2-kpi {{ padding-top:4px; }}
.r2-kpi .lab {{ font-size:{'15px' if wall else '13px'}; color:{t['ink2']}; }}
.r2-kpi .val {{ font-size:{'44px' if wall else '28px'}; font-weight:600; line-height:1.15; letter-spacing:-.01em; margin-top:3px;
  white-space:nowrap; color:{t['ink']}; font-variant-numeric:tabular-nums; }}
.r2-kpi .of {{ font-size:{'15px' if wall else '13px'}; font-weight:400; color:{t['ink2']}; letter-spacing:0; margin-left:6px; }}
.r2-kpi .cause {{ display:flex; align-items:center; gap:7px; font-size:{'15px' if wall else '13px'}; margin-top:8px; line-height:1.3; color:{t['ink']}; }}
.r2-kpi .cause + .cause {{ margin-top:4px; }}
.r2-kpi .ids {{ color:{t['ink3']}; }}
.r2-kpi .next {{ font-size:{'15px' if wall else '13px'}; color:{t['ink2']}; margin-top:9px; line-height:1.45; font-variant-numeric:tabular-nums; }}
.r2-kpi .next b {{ color:{t['ink']}; font-weight:600; }}
.r2-kpi .muted {{ color:{t['ink3']}; }}
.r2-kpi .plant {{ font-size:17px; font-weight:600; margin-top:4px; line-height:1.3; color:{t['ink']}; }}
.r2-kpi .sub {{ font-size:12px; color:{t['ink3']}; margin-top:6px; }}
.r2-kpi .note {{ font-size:12px; color:{t['warn']}; margin-top:4px; }}
.r2-units {{ display:flex; gap:3px; margin-top:9px; width:100%; max-width:230px; }}
.r2-unit {{ position:relative; height:28px; border-radius:3px; background:{t['card']}; border:1px solid {t['rule']};
  display:grid; place-items:center; font-size:11px; color:{t['ink2']}; overflow:hidden; min-width:0; }}
.r2-unit span {{ position:relative; white-space:nowrap; padding:0 3px; border-radius:2px; }}
.r2-unit--adhoc {{ border-color:transparent; {_dots_css(t['adhoc'])} }}
.r2-unit--planned {{ border-color:transparent; {_hatch_css(t['planned'], 45)} }}
.r2-unit--unplanned {{ border-color:transparent; {_hatch_css(t['unplanned'], -45)} }}
.r2-unit--adhoc span, .r2-unit--planned span, .r2-unit--unplanned span {{ background:{t['card']}; color:{t['ink']}; }}

/* ---- Coming up: numbered, two-line items; hairline box on the band ---- */
.r2-up {{ border:1px solid {t['rule']}; border-radius:4px; padding:9px 12px 8px; margin-top:{'20px' if wall else '22px'}; }}
.r2-up .hd {{ display:flex; justify-content:space-between; align-items:baseline; font-size:{'13.5px' if wall else '12px'};
  color:{t['ink2']}; font-weight:600; margin-bottom:2px; }}
.r2-up .hd span + span {{ font-weight:400; }}
.r2-up ol {{ list-style:none; margin:0; padding:0; }}
.r2-up li {{ display:grid; grid-template-columns:18px minmax(0,1fr) auto; column-gap:8px; padding:7px 0 6px; border-top:1px solid {t['rule2']}; margin:0; }}
.r2-up li:first-child {{ border-top:0; }}
.r2-up .num {{ width:18px; height:18px; border-radius:50%; background:{t['ink']}; color:{t['on_ink']}; font-size:10.5px; font-weight:600;
  display:grid; place-items:center; margin-top:1px; }}
.r2-up .when {{ font-size:{'15px' if wall else '13px'}; color:{t['ink']}; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.r2-up .when b {{ font-weight:600; }}
.r2-up .chg {{ font-size:{'15px' if wall else '13px'}; font-weight:600; color:{t['ink']}; font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }}
.r2-up .chg i {{ font-style:normal; color:{t['ink2']}; font-size:11px; margin-right:2px; }}
.r2-up .why {{ grid-column:2 / 4; font-size:{'13.5px' if wall else '12px'}; color:{t['ink2']}; line-height:1.4; margin-top:1px;
  {'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;' if wall else 'overflow-wrap:anywhere;'} }}
.r2-up .none {{ font-size:13px; color:{t['ink2']}; margin:6px 0 4px; }}
.r2-up .more {{ font-size:12px; color:{t['ink2']}; padding-top:6px; border-top:1px solid {t['rule2']}; }}

/* ---- Wall header: title · legend · clock ---- */
.r2-wallhead {{ display:flex; align-items:center; justify-content:space-between; gap:30px; padding-bottom:14px; }}
.r2-wtitle {{ font-size:28px; font-weight:600; letter-spacing:-.015em; color:{t['ink']}; }}
.r2-wallhead .r2-legend {{ border-left:0; padding-left:0; font-size:14px; }}
.r2-clock {{ display:flex; align-items:baseline; gap:14px; white-space:nowrap; color:{t['ink2']}; font-size:14px; }}
.r2-clock .r2-live b {{ font-size:14px; }}
.r2-clock > b {{ font-size:40px; font-weight:600; letter-spacing:-.02em; color:{t['ink']}; font-variant-numeric:tabular-nums; }}

/* ---- Register and change lists ---- */
.r2-panelh {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; font-size:15px; font-weight:600; color:{t['ink']};
  padding-bottom:9px; border-bottom:1px solid {t['rule']}; margin-top:28px; }}
.r2-panelh .muted {{ font-size:13px; font-weight:400; color:{t['ink2']}; }}
.r2-th {{ font-size:12px; color:{t['ink3']}; padding:8px 0 2px; }}
.r2-td {{ font-size:13px; color:{t['ink']}; line-height:1.45; font-variant-numeric:tabular-nums; }}
.r2-td .muted {{ color:{t['ink3']}; }}
.r2-td b {{ font-weight:600; }}
[class*="st-key-rvrow-"] {{ border-top:1px solid {t['rule2']}; padding:8px 0 2px; }}
[class*="st-key-rvrow-"] button {{ min-height:0; padding:0 2px; color:{t['ink']}; }}
[class*="st-key-rvrow-"] button p {{ font-size:13px; font-weight:600; text-decoration:underline; text-decoration-color:{t['rule']}; text-underline-offset:3px; }}
.r2-st {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }}
.r2-st i {{ width:8px; height:8px; border-radius:50%; display:inline-block; flex:none; }}
.r2-st--active i {{ background:{t['ink']}; }}
.r2-st--planned i {{ box-shadow:inset 0 0 0 1.5px {t['ink2']}; }}
.r2-st--ended i, .r2-st--cancelled i {{ background:{t['ink3']}; opacity:.5; }}
.r2-st--ended, .r2-st--cancelled {{ color:{t['ink3']}; }}
.r2-st--review {{ color:{t['warn']}; font-weight:600; }}
.r2-st--review i {{ background:{t['warn']}; border-radius:1px; transform:rotate(45deg); width:7px; height:7px; }}
table.r2-t {{ border-collapse:collapse; width:100%; font-size:13px; color:{t['ink']}; border:0 !important; }}
[data-testid="stMarkdownContainer"] table.r2-t th, [data-testid="stMarkdownContainer"] table.r2-t td {{ border:0 !important; border-bottom:1px solid {t['rule2']} !important; background:transparent !important; }}
table.r2-t th {{ font-size:12px; font-weight:400; color:{t['ink3']}; text-align:left; padding:8px 8px 6px; border-bottom:1px solid {t['rule2']}; }}
table.r2-t td {{ padding:9px 8px; border-bottom:1px solid {t['rule2']}; vertical-align:top; font-variant-numeric:tabular-nums; }}
table.r2-t .muted {{ color:{t['ink3']}; }}
.r2-kind {{ display:inline-block; font-size:12px; padding:1px 7px; border-radius:999px; border:1px solid {t['rule']}; color:{t['ink2']}; white-space:nowrap; }}

/* ---- New ad-hoc dialog ---- */
[class*="st-key-af_units"] button[aria-pressed="true"], [class*="st-key-ef_units"] button[aria-pressed="true"] {{ {_dots_css(t['adhoc'])} border-color:{t['ink']} !important;
  box-shadow:inset 0 0 0 1px {t['ink']}; color:{t['ink']}; }}
[class*="st-key-af_units"] button[aria-pressed="true"] > div, [class*="st-key-ef_units"] button[aria-pressed="true"] > div {{ background:{t['card']}; padding:0 4px; border-radius:2px; font-weight:600; }}
[class*="st-key-af_prev_"] {{ border:1px solid {t['rule']}; border-radius:6px; padding:10px 12px 12px; gap:.2rem; }}
.st-key-af_prev_atwick {{ background:{t['plot']['Atwick']}; }} .st-key-af_prev_aldbrough {{ background:{t['plot']['Aldbrough']}; }}
.st-key-af_kind_btn button p {{ font-size:13px; text-decoration:underline; text-decoration-color:{t['rule']}; text-underline-offset:3px; }}
.r2-prevhd {{ display:flex; justify-content:space-between; font-size:13px; font-weight:600; color:{t['ink']}; }}
.r2-prevhd span + span {{ font-weight:400; color:{t['ink3']}; }}
.r2-prevtxt {{ margin:0; font-size:13px !important; color:{t['ink2']}; }}
.r2-prevtxt b {{ color:{t['ink']}; }}
.r2-thr {{ display:grid; gap:5px; margin-top:10px; font-size:12px; color:{t['ink2']}; }}
.r2-thr .bar {{ height:6px; border-radius:3px; background:{t['rule']}; position:relative; overflow:hidden; }}
.r2-thr .bar span {{ position:absolute; left:0; top:0; bottom:0; border-radius:3px; background:{t['ink']}; }}
.r2-thr--over {{ color:{t['warn']}; font-weight:600; }}
.r2-thr--over .bar span {{ background:{t['warn']}; }}
.r2-thr b {{ color:{t['ink']}; }}

/* ---- Misc ---- */
.r2-sr {{ position:absolute !important; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}
.r2-banner {{ border-left:3px solid {t['rule']}; padding:.4rem .8rem; margin:.5rem 0; font-size:15px; color:{t['ink']}; }}
.r2-banner--warn {{ border-left-color:{t['warn']}; }} .r2-banner--bad {{ border-left-color:{t['bad']}; }} .r2-banner--info {{ border-left-color:{t['ink2']}; }}
[data-testid="stExpander"] details {{ border:none !important; border-top:1px solid {t['rule']} !important; border-radius:0 !important; background:transparent !important; }}
[data-testid="stExpander"] summary {{ padding-left:0 !important; font-weight:600; }}
.r2-foot {{ font-size:12px; color:{t['ink3']}; margin-top:1.2rem; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
@media (max-width: 640px) {{
  .block-container {{ padding-left:16px; padding-right:16px; }}
  [class*="st-key-site-"] {{ margin-left:-16px; margin-right:-16px; padding-left:16px; padding-right:16px; width:calc(100% + 32px) !important; }}
  [data-testid="stMarkdownContainer"] h1.r2-h1, .r2-h1 {{ font-size:26px; }} .r2-live, .r2-sub {{ justify-content:flex-start; text-align:left; }}
  .st-key-r2live [data-testid="stHorizontalBlock"] {{ justify-content:flex-start; }}
  .r2-legend {{ border-left:0; padding-left:0; }}
  .r2-up {{ margin-top:0; }}
  .st-key-r2toolbar [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; }}
  .st-key-r2toolbar [data-testid="stColumn"]:has(.r2-legend) {{ flex:1 1 100% !important; width:100% !important; order:10; height:auto !important; flex-basis:auto !important; margin-bottom:16px; }}
  .st-key-r2toolbar [data-testid="stColumn"]:has(.r2-legend) > div {{ height:auto !important; }}
  .st-key-r2toolbar [data-testid="stColumn"]:has([class*="st-key-r2chip"]) {{ margin-left:0; }}
  .st-key-rvhead {{ display:none; }}
}}
{WALL_EXTRA if wall else ''}
</style>
"""


WALL_EXTRA = """
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display:none !important; }
"""


def inject_css(wall: bool = False) -> None:
    st.markdown(_css(tokens(wall), wall), unsafe_allow_html=True)   # CSS runs inside st.markdown; scripts never do


def legend_html() -> str:
    """The one key for every chart: available, the three causes, and past."""
    items = [(swatch("avail"), "Available"), (swatch("planned"), "Planned REMIT"), (swatch("unplanned"), "Unplanned REMIT"),
             (swatch("adhoc"), "Ad-hoc"), (swatch("planned", past=True), "Past")]
    return "<div class='r2-legend'>" + "".join(f"<span>{s}{t}</span>" for s, t in items) + "</div>"
