"""Golden cases for the combine rule, attribution, lanes, threshold, narration."""
from pathlib import Path

import pandas as pd
import pytest

from remit2.adhoc.combine import LANE_ADHOC, LANE_PLANNED, LANE_UNPLANNED, combined_state_at, compute_combined_series, threshold_check
from remit2.adhoc.model import EquipmentConfig, Register, new_record
from remit2.adhoc.narrate import narrate_panel, plant_terms
from remit2.core.timeutil import to_local, to_utc
from tests.helpers import D, H, NOW, build_df_op, mk_remit

EQ = EquipmentConfig.load(Path(__file__).resolve().parents[2] / "config/equipment.default.json")
ATW_I, ATW_W, ALD_W = ("Atwick", "Injection"), ("Atwick", "Withdrawal"), ("Aldbrough", "Withdrawal")


def reg_with(*recs, actor="t@sse.com"):
    reg = Register()
    for r in recs:
        reg.create(r, actor, NOW - D)
    return reg


def unit_out(site, direction, units, start=NOW - 2 * H, end=None, covered=None):
    return new_record(site, direction, "unit_out", start, "test notes", units=units, end=end, covered_by_thread=covered)


def rate_cap(site, direction, resulting, start=NOW - 2 * H, end=None):
    return new_record(site, direction, "rate_cap", start, "test notes", resulting_avail_gwhd=resulting, end=end)


def avail(df_op, reg, key, t=NOW):
    return combined_state_at(df_op, reg, EQ, *key, t).available


# --- levels ------------------------------------------------------------------

def test_nothing_gives_nameplate():
    df_op = build_df_op([])
    assert avail(df_op, Register(), ATW_I) == 30.0
    assert avail(df_op, Register(), ALD_W) == 287.78


def test_remit_only_uses_stated_available():
    df_op = build_df_op([mk_remit("ALD_1", "Aldbrough", "Withdrawal", NOW - D, NOW + D, avail=100.0, unavail=187.78)])
    assert avail(df_op, Register(), ALD_W) == 100.0
    assert avail(df_op, Register(), ALD_W, NOW + 2 * D) == 287.78


def test_two_comps_out():
    assert avail(build_df_op([]), reg_with(unit_out(*ATW_I, ["COMP2", "COMP3"])), ATW_I) == 15.0


def test_unit_out_is_additive_to_remit():
    df_op = build_df_op([mk_remit("ATW_9", "Atwick", "Injection", NOW - D, NOW + D, avail=20.0, unavail=10.0)])
    assert avail(df_op, reg_with(unit_out(*ATW_I, ["COMP2", "COMP3"])), ATW_I) == 5.0


def test_covered_by_thread_is_excluded_until_thread_ends():
    df_op = build_df_op([mk_remit("ATW_9", "Atwick", "Injection", NOW - D, NOW + D, avail=20.0, unavail=10.0)])
    reg = reg_with(unit_out(*ATW_I, ["COMP2", "COMP3"], covered="ATW_9"))
    assert avail(df_op, reg, ATW_I) == 20.0                      # covered: display-only
    assert avail(df_op, reg, ATW_I, NOW + 2 * D) == 15.0         # thread ended: additive again
    st = combined_state_at(df_op, reg, EQ, *ATW_I, NOW)
    cov = [d for d in st.drivers if d.source == "adhoc"][0]
    assert not cov.binding and "covered by REMIT" in cov.note


def test_rate_cap_is_minimum_type():
    df_op = build_df_op([mk_remit("ATW_9", "Atwick", "Injection", NOW - D, NOW + D, avail=20.0, unavail=10.0)])
    assert avail(df_op, reg_with(rate_cap(*ATW_I, 10.0)), ATW_I) == 10.0
    assert avail(df_op, reg_with(rate_cap(*ATW_I, 25.0)), ATW_I) == 20.0


def test_clamps():
    df_op = build_df_op([mk_remit("ATW_9", "Atwick", "Injection", NOW - D, NOW + D, avail=10.0, unavail=20.0)])
    assert avail(df_op, reg_with(unit_out(*ATW_I, ["COMP1", "COMP2"])), ATW_I) == 0.0       # 10 − 15 -> 0
    assert avail(build_df_op([]), reg_with(rate_cap(*ATW_I, 40.0)), ATW_I) == 30.0            # cap above nameplate -> nameplate


def test_same_unit_named_twice_counts_once():
    reg = reg_with(unit_out(*ATW_I, ["COMP2"]), unit_out(*ATW_I, ["COMP2", "COMP3"]))
    assert avail(build_df_op([]), reg, ATW_I) == 15.0


def test_open_ended_cancelled_and_closed():
    reg = reg_with(unit_out(*ATW_I, ["COMP1"]))
    assert avail(build_df_op([]), reg, ATW_I, NOW + 300 * D) == 22.5          # until further notice
    rid = reg.records[0].id
    reg.close(rid, "t@sse.com", NOW + H, "back")
    assert avail(build_df_op([]), reg, ATW_I, NOW + 2 * H) == 30.0            # ends at closed_at
    assert avail(build_df_op([]), reg, ATW_I, NOW) == 22.5                    # before close still counts
    reg2 = reg_with(unit_out(*ATW_I, ["COMP1"]))
    reg2.cancel(reg2.records[0].id, "t@sse.com", NOW, "dup")
    assert avail(build_df_op([]), reg2, ATW_I) == 30.0                        # cancelled ignored


def test_stale_and_overdue_flags():
    r = unit_out(*ATW_I, ["COMP1"], start=NOW - 10 * D)
    reg = Register(); reg.create(r, "t@sse.com", NOW - 10 * D)
    assert r.is_stale(NOW, EQ.stale_after_days) and not r.is_stale(NOW - 5 * D, EQ.stale_after_days)
    r.expected_return = (NOW - H).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert r.is_overdue(NOW)


# --- attribution, lanes, series ---------------------------------------------

def test_drivers_and_lane_flags():
    df_op = build_df_op([
        mk_remit("ATW_P", "Atwick", "Withdrawal", NOW - D, NOW + D, avail=100.0, unavail=30.0, planned=True),
        mk_remit("ATW_U", "Atwick", "Withdrawal", NOW - H, NOW + 3 * D, avail=110.0, unavail=20.0, planned=False),
    ])
    reg = reg_with(unit_out(*ATW_W, ["VORTISEP"]))
    st = combined_state_at(df_op, reg, EQ, *ATW_W, NOW)
    assert st.available == 70.0                                   # min stated 100 − 30 (Vortisep)
    f = st.flags()
    assert f == {"remit_planned": True, "remit_unplanned": False, "adhoc": True}
    nb = [d for d in st.drivers if d.id == "ATW_U"][0]
    assert not nb.binding and nb.note == "overlapping, not binding"


def test_series_segments_lanes_and_breakpoints():
    df_op = build_df_op([mk_remit("ATW_P", "Atwick", "Injection", NOW + 21 * H, NOW + 4 * D, avail=15.0, unavail=15.0)])
    reg = reg_with(unit_out(*ATW_I, ["COMP1"], start=NOW + 2 * D, end=NOW + 3 * D))
    s = compute_combined_series(df_op, reg, EQ, *ATW_I, NOW - D, NOW + 7 * D, NOW)
    starts = [seg.start for seg in s.segments]
    assert NOW in starts and NOW + 21 * H in starts and NOW + 2 * D in starts and NOW + 3 * D in starts
    assert s.segment_at(NOW).available == 30.0
    assert s.segment_at(NOW + 22 * H).available == 15.0
    assert s.segment_at(NOW + 2 * D + H).available == 7.5            # 15 − 7.5
    assert s.segment_at(NOW + 5 * D).available == 30.0
    lanes = {(l.lane, l.start, l.end) for l in s.lanes}
    assert (LANE_PLANNED, NOW + 21 * H, NOW + 4 * D) in lanes
    assert (LANE_ADHOC, NOW + 2 * D, NOW + 3 * D) in lanes
    assert not any(l.lane == LANE_UNPLANNED for l in s.lanes)
    assert list(s.points.columns) == ["date", "available"]


def test_points_budget_at_two_years():
    s = compute_combined_series(build_df_op([]), Register(), EQ, *ATW_I, NOW - 180 * D, NOW + 730 * D, NOW)
    assert len(s.points) <= 1200 + len(s.segments) + 2


# --- threshold ---------------------------------------------------------------

def test_threshold_single_and_aggregate_and_quarter():
    df_op = build_df_op([])
    small = threshold_check(unit_out(*ATW_I, ["COMP2", "COMP3"]), Register(), EQ, df_op, NOW)
    assert small.quarter == "Q3" and small.threshold == 55.5 and not small.exceeds and small.impact_gwhd == 15.0
    big = threshold_check(unit_out(*ATW_W, ["VORTISEP", "PHASE6"]), Register(), EQ, df_op, NOW)
    assert big.exceeds and big.impact_gwhd == 130.0
    feb = threshold_check(unit_out(*ATW_W, ["VORTISEP"], start=pd.Timestamp("2026-02-10T09:00Z")), Register(), EQ, df_op, NOW)
    assert feb.quarter == "Q1" and feb.threshold == 27.5 and feb.exceeds          # 30 > 27.5
    # aggregate: existing Vortisep ad-hoc (30) + new cap to 70 (reduction 30) = 60 > 55.5
    reg = reg_with(unit_out(*ATW_W, ["VORTISEP"]))
    agg = threshold_check(rate_cap(*ATW_W, 70.0), reg, EQ, df_op, NOW)
    assert agg.impact_gwhd == 30.0 and agg.aggregate_after_gwhd == 60.0 and agg.exceeds


# --- narration & plant view -------------------------------------------------

def test_narrative_values_and_plant():
    df_op = build_df_op([mk_remit("ATW_P", "Atwick", "Injection", NOW + 21 * H, NOW + 4 * D, avail=15.0, unavail=15.0)])
    reg = reg_with(unit_out(*ATW_I, ["COMP4"]))
    s = compute_combined_series(df_op, reg, EQ, *ATW_I, NOW - D, NOW + 7 * D, NOW)
    text = narrate_panel(s, EQ)
    assert text.startswith("22.5 of 30 GWh/d available now (75%). Drops to 7.5 at")
    assert "Then 22.5 at" in text and "Comp 4 out" in text       # ad-hoc is open-ended: not back to 30
    plant = narrate_panel(s, EQ, mode="plant")
    assert plant.startswith("3 of 4 comps available · Comp 4 out (ad-hoc) now")
    st_future = s.segment_at(NOW + 22 * H).state
    assert plant_terms(st_future, EQ, *ATW_I) == "1 of 4 comps available · Comp 4 out (ad-hoc) · ≈ 2 comps out (REMIT)"


def test_plant_terms_named_units_withdrawal():
    df_op = build_df_op([mk_remit("ATW_X", "Atwick", "Withdrawal", NOW - D, NOW + D, avail=30.0, unavail=100.0)])
    st = combined_state_at(df_op, Register(), EQ, *ATW_W, NOW)
    assert plant_terms(st, EQ, *ATW_W) == "≈ Phase 6-sized outage (REMIT)"


# --- DST ---------------------------------------------------------------------

def test_dst_round_trip():
    local = pd.Timestamp("2026-10-25 01:30")          # ambiguous: clocks go back at 02:00 BST
    utc = to_utc(local)
    assert utc == pd.Timestamp("2026-10-25T00:30:00Z")
    assert to_local(utc).strftime("%H:%M %Z") == "01:30 BST"
    gap = to_utc(pd.Timestamp("2026-03-29 01:30"))    # nonexistent (spring forward) -> first valid instant
    assert to_local(gap).strftime("%H:%M %Z") == "02:00 BST"
