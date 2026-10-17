"""Storage capacity (TWh): REMITs plus ad-hoc cavern outages, Plant terms,
threshold and validation. Same combine rule as the rates."""
from pathlib import Path

import pytest

from remit2.adhoc.combine import LANE_ADHOC, LANE_PLANNED, combined_state_at, lost_parts, threshold_check
from remit2.adhoc.model import EquipmentConfig, Register, new_record, validate_record
from remit2.adhoc.narrate import plant_terms
from tests.helpers import D, H, NOW, build_df_op, mk_remit

EQ = EquipmentConfig.load(Path(__file__).resolve().parents[2] / "config/equipment.default.json")
CAV = 3.3 / 8


def cavern(units, start=NOW - 2 * H, end=None, covered=None):
    return new_record("Aldbrough", "Storage", "unit_out", start, "cavern test", units=units, end=end, covered_by_thread=covered)


def reg_with(*recs):
    reg = Register()
    for r in recs:
        reg.create(r, "t@sse.com", NOW - D)
    return reg


def storage_remit(avail=2.75, unavail=0.55):
    return build_df_op([mk_remit("ALD_1307", "Aldbrough", "Storage", NOW - D, NOW + 5 * D, avail=avail, unavail=unavail, tech=3.3)])


def test_storage_full_and_remit_only():
    assert combined_state_at(build_df_op([]), Register(), EQ, "Aldbrough", "Storage", NOW).available == pytest.approx(3.3)
    assert combined_state_at(storage_remit(), Register(), EQ, "Aldbrough", "Storage", NOW).available == pytest.approx(2.75)


def test_cavern_adhoc_is_additive_and_split_by_cause():
    s = combined_state_at(storage_remit(), reg_with(cavern(["CAV5"])), EQ, "Aldbrough", "Storage", NOW)
    assert s.available == pytest.approx(2.75 - CAV)
    assert [(p.lane, round(p.amount, 4)) for p in lost_parts(s)] == [(LANE_PLANNED, 0.55), (LANE_ADHOC, round(CAV, 4))]


def test_cavern_covered_by_remit_is_not_counted():
    s = combined_state_at(storage_remit(), reg_with(cavern(["CAV5"], covered="ALD_1307")), EQ, "Aldbrough", "Storage", NOW)
    assert s.available == pytest.approx(2.75)


def test_cavern_does_not_touch_rates():
    reg = reg_with(cavern(["CAV1", "CAV2"]))
    for direction, T in (("Withdrawal", 287.78), ("Injection", 293.33)):
        assert combined_state_at(build_df_op([]), reg, EQ, "Aldbrough", direction, NOW).available == pytest.approx(T)


def test_plant_terms_in_caverns():
    s = combined_state_at(storage_remit(), reg_with(cavern(["CAV5"])), EQ, "Aldbrough", "Storage", NOW)
    assert plant_terms(s, EQ, "Aldbrough", "Storage") == "6 of 8 caverns available · Cavern 5 out (ad-hoc) · ≈ 1 cavern out (REMIT)"


def test_any_unpublished_cavern_triggers_threshold():
    thr = threshold_check(cavern(["CAV3"], start=NOW + H), Register(), EQ, build_df_op([]), NOW)
    assert thr.exceeds and thr.quarter == "storage" and thr.threshold == 0.001
    assert thr.impact_gwhd == pytest.approx(CAV)


def test_storage_accepts_units_only():
    rate = new_record("Aldbrough", "Storage", "rate_cap", NOW, "rate test", resulting_avail_gwhd=2.0)
    assert any("not available for storage" in e for e in validate_record(rate, EQ, NOW))
    assert validate_record(cavern(["CAV1"]), EQ, NOW) == []
