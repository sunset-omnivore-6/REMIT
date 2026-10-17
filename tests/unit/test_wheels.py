"""Design review B2: glance-wheel states, the % text, staleness and the SVG."""
from pathlib import Path

import pandas as pd

from remit2.adhoc.model import EquipmentConfig, Register, new_record
from remit2.adhoc.narrate import change_events
from remit2.adhoc.combine import compute_combined_series
from remit2.ui import wheels as wh
from remit2.ui.theme import DARK, LIGHT
from tests.helpers import D, H, NOW, build_df_op, mk_remit

EQ = EquipmentConfig.load(Path(__file__).resolve().parents[2] / "config/equipment.default.json")


def test_state_thresholds():
    assert wh.state_of(30.0, 30.0) == "full"
    assert wh.state_of(29.99, 30.0) == "full"          # ≥ 99.95%
    assert wh.state_of(29.9, 30.0) == "reduced"
    assert wh.state_of(15.0, 30.0) == "reduced"        # exactly 50% is still Reduced
    assert wh.state_of(14.9, 30.0) == "severe"
    assert wh.state_of(0.1, 30.0) == "severe"
    assert wh.state_of(0.0, 30.0) == "out"
    assert wh.state_of(30.0, 30.0, stale=True) == "stale"


def test_pct_text_never_overstates():
    assert wh.pct_text(30.0, 30.0) == "100"
    assert wh.pct_text(29.9, 30.0) == "99"              # not rounded up to 100
    assert wh.pct_text(0.01, 30.0) == "1"               # not rounded down to 0
    assert wh.pct_text(0.0, 30.0) == "0"
    assert wh.pct_text(15.0, 30.0) == "50"


def test_stale_after_15_minutes():
    assert not wh.is_stale(NOW - pd.Timedelta(minutes=15), NOW)
    assert wh.is_stale(NOW - pd.Timedelta(minutes=16), NOW)
    assert wh.is_stale(None, NOW)


def test_wheel_svg_shapes():
    full = wh.wheel_svg(30.0, 30.0, LIGHT, unit="GWh/d")
    assert "g-wheel--full" in full and "<circle class='g-arc'" in full
    red = wh.wheel_svg(22.5, 30.0, LIGHT, unit="GWh/d", next_frac=1.0)
    assert "<path class='g-arc'" in red and "g-edge" in red        # light mode edge on gold
    assert "g-next-mark" in red
    assert "g-edge" not in wh.wheel_svg(22.5, 30.0, DARK, unit="GWh/d")
    out = wh.wheel_svg(0.0, 30.0, LIGHT, unit="GWh/d")
    assert "g-arc" not in out and ">0<" in out
    stale = wh.wheel_svg(22.5, 30.0, LIGHT, unit="GWh/d", next_frac=1.0, stale=True)
    assert "stroke-dasharray" in stale and "g-next-mark" not in stale
    assert "role='img'" in red and "aria-label='Reduced, 75% (22.5 of 30 GWh/d)'" in red


def test_strip_has_six_wheels():
    df_op = build_df_op([mk_remit("ATW_1402", "Atwick", "Injection", NOW + D, NOW + 3 * D, avail=15.0, unavail=15.0,
                                  planned=True)])
    reg = Register()
    reg.create(new_record("Atwick", "Injection", "unit_out", NOW - 2 * H, "test notes", units=["COMP3"]), "t@sse.com", NOW - D)
    panels, events = {}, {}
    for site in ("Atwick", "Aldbrough"):
        for m in wh.MEASURES:
            s = compute_combined_series(df_op, reg, EQ, site, m, NOW - D, NOW + 30 * D, NOW)
            panels[(site, m)], events[(site, m)] = s, change_events(s, EQ)
    out = wh.strip_html(panels, events, EQ, LIGHT)
    assert out.count("<svg class='g-wheel") == 6
    assert "g-wheel--reduced" in out and out.count("g-wheel--full") == 5
    assert "Next <b>▼ 25%</b>" in out                   # planned REMIT tomorrow takes Injection to 7.5 of 30
    assert out.count("class='g-verdict'") == 2          # one verdict per site card
    assert wh.site_verdict(panels, "Atwick", LIGHT).endswith("1 reduced</span>")
    assert wh.site_verdict(panels, "Aldbrough", LIGHT).endswith("All full</span>")
    assert wh.site_verdict(panels, "Atwick", LIGHT, stale=True).endswith("Data stale</span>")


def test_site_verdict_orders_worst_first():
    df_op = build_df_op([mk_remit("A", "Atwick", "Withdrawal", NOW - D, NOW + D, avail=0.0, unavail=130.0),
                         mk_remit("B", "Atwick", "Injection", NOW - D, NOW + D, avail=10.0, unavail=20.0),
                         mk_remit("C", "Atwick", "Storage", NOW - D, NOW + D, avail=3.0, unavail=0.47, tech=3.47)])
    panels = {("Atwick", m): compute_combined_series(df_op, Register(), EQ, "Atwick", m, NOW - D, NOW + 30 * D, NOW)
              for m in wh.MEASURES}
    v = wh.site_verdict(panels, "Atwick", LIGHT)
    assert v.endswith("1 out · 1 severe · 1 reduced</span>")
    assert wh.state_icon("out", LIGHT, 15) in v                  # icon of the worst state


def _badges(fig):
    tr = [t for t in fig.data if t.mode == "markers+text"]
    return [] if not tr else list(tr[0].x)


def test_wall_badges_only_for_listed_changes_and_never_touch():
    """Ten storage changes a few hours apart (review B2 feedback): the wall
    numbers only the changes it lists, and badges keep a gap between them."""
    from remit2.ui.hero import panel_figure
    rows = [mk_remit(f"ATW_13{i:02d}", "Atwick", "Storage", NOW + D + i * 6 * H, NOW + D + i * 6 * H + 3 * H,
                     avail=3.0, unavail=0.47, planned=True, tech=3.47) for i in range(5)]
    s = compute_combined_series(build_df_op(rows), Register(), EQ, "Atwick", "Storage", NOW - 7 * D, NOW + 30 * D, NOW)
    ev = change_events(s, EQ)
    assert len(ev) == 10
    wall = panel_figure(s, EQ, wall=True, events=ev, badges=wh.WALL_LIST_N)
    assert len(_badges(wall)) == 2
    std = panel_figure(s, EQ, events=ev)
    xs = [pd.Timestamp(x) for x in _badges(std)]
    assert len(xs) == 10
    span = s.window[1] - s.window[0]
    assert all(b - a >= span * 22 / 900 * 0.999 for a, b in zip(xs, xs[1:]))
