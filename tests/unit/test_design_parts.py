"""Design review rev A: lost capacity split by cause, the attribution fix,
and the numbered changes that tie the chart to the Coming up list."""
from pathlib import Path

import pytest

from remit2.adhoc.combine import LANE_ADHOC, LANE_PLANNED, LANE_UNPLANNED, combined_state_at, compute_combined_series, lost_parts
from remit2.adhoc.model import EquipmentConfig, Register, new_record
from remit2.adhoc.narrate import change_events
from tests.helpers import D, H, NOW, build_df_op, mk_remit

EQ = EquipmentConfig.load(Path(__file__).resolve().parents[2] / "config/equipment.default.json")


def reg_with(*recs):
    reg = Register()
    for r in recs:
        reg.create(r, "t@sse.com", NOW - D)
    return reg


def comp(units, start=NOW - 2 * H, end=None):
    return new_record("Atwick", "Injection", "unit_out", start, "test notes", units=units, end=end)


def test_overlapping_causes_are_both_shown():
    """Planned REMIT to 15 plus one comp ad-hoc: 15.0 planned + 7.5 ad-hoc, stacked."""
    df_op = build_df_op([mk_remit("ATW_1402", "Atwick", "Injection", NOW - D, NOW + D, avail=15.0, unavail=15.0, planned=True)])
    s = combined_state_at(df_op, reg_with(comp(["COMP3"])), EQ, "Atwick", "Injection", NOW)
    parts = lost_parts(s)
    assert [(p.lane, round(p.amount, 1)) for p in parts] == [(LANE_PLANNED, 15.0), (LANE_ADHOC, 7.5)]
    assert s.available == pytest.approx(7.5)


def test_unplanned_wins_the_remit_part_when_both_bind():
    df_op = build_df_op([mk_remit("A", "Atwick", "Injection", NOW - D, NOW + D, avail=15.0, unavail=15.0, planned=True),
                         mk_remit("B", "Atwick", "Injection", NOW - D, NOW + D, avail=15.0, unavail=15.0, planned=False)])
    parts = lost_parts(combined_state_at(df_op, Register(), EQ, "Atwick", "Injection", NOW))
    assert [p.lane for p in parts] == [LANE_UNPLANNED]


def test_full_capacity_has_no_parts():
    assert lost_parts(combined_state_at(build_df_op([]), Register(), EQ, "Atwick", "Injection", NOW)) == []


def test_adhoc_not_blamed_when_remit_already_at_zero():
    """Found in the design review: a REMIT holding the level at 0 must not
    have an overlapping ad-hoc flagged as the cause."""
    df_op = build_df_op([mk_remit("Z", "Atwick", "Injection", NOW - D, NOW + D, avail=0.0, unavail=30.0)])
    s = combined_state_at(df_op, reg_with(comp(["COMP3"])), EQ, "Atwick", "Injection", NOW)
    assert s.available == 0.0
    assert not any(d.binding for d in s.drivers if d.source == "adhoc")
    assert [p.lane for p in lost_parts(s)] == [LANE_PLANNED]


def test_numbered_changes_with_reasons():
    df_op = build_df_op([mk_remit("ATW_000000000000001402", "Atwick", "Injection", NOW + D, NOW + 3 * D, avail=15.0, unavail=15.0, planned=True)])
    reg = reg_with(comp(["COMP3"], end=NOW + 5 * D))
    series = compute_combined_series(df_op, reg, EQ, "Atwick", "Injection", NOW - D, NOW + 10 * D, NOW)
    ev = change_events(series, EQ)
    assert [e.n for e in ev] == [1, 2, 3]
    assert [round(e.available, 1) for e in ev] == [7.5, 22.5, 30.0]
    assert ev[0].why == "Planned REMIT ATW_1402 starts"
    assert ev[1].why == "Planned REMIT ATW_1402 ends"
    assert ev[2].why == "Ad-hoc A-0001 (Comp 3) ends"
