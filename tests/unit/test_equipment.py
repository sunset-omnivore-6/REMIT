from pathlib import Path

from remit2.adhoc.model import EquipmentConfig
from remit2.core.constants import TECH_CAPACITY_FALLBACK
import pandas as pd

CFG = EquipmentConfig.load(Path(__file__).resolve().parents[2] / "config/equipment.default.json")


def test_nameplates_match_core():
    for (site, direction), c in CFG.table.items():
        assert c.nameplate_gwhd == TECH_CAPACITY_FALLBACK[(site, direction)], (site, direction)


def test_unit_ids_unique_and_menus_match_spec():
    spec = {
        ("Atwick", "Injection"): ["Comp 1", "Comp 2", "Comp 3", "Comp 4"],
        ("Atwick", "Withdrawal"): ["Vortisep", "Phase 6"],
        ("Aldbrough", "Injection"): ["Comp 1", "Comp 2", "Comp 3"],
        ("Aldbrough", "Withdrawal"): ["Train 1", "Train 2"],
    }
    for key, labels in spec.items():
        c = CFG.get(*key)
        assert [u.label for u in c.units] == labels, key
        assert len({u.id for u in c.units}) == len(c.units)
        assert c.menu == ("units", "rate_cap")
    assert CFG.get("Atwick", "Injection").plant_view and CFG.get("Atwick", "Withdrawal").plant_view
    assert not CFG.get("Aldbrough", "Injection").plant_view and not CFG.get("Aldbrough", "Withdrawal").plant_view


def test_agreed_values():
    assert CFG.gwhd_lost("Atwick", "Injection", ["COMP1"]) == 7.5
    assert CFG.gwhd_lost("Atwick", "Withdrawal", ["VORTISEP"]) == 30.0
    assert CFG.gwhd_lost("Atwick", "Withdrawal", ["PHASE6"]) == 100.0
    assert all(not u.placeholder for k in (("Atwick", "Injection"), ("Atwick", "Withdrawal")) for u in CFG.get(*k).units)
    assert all(u.placeholder for k in (("Aldbrough", "Injection"), ("Aldbrough", "Withdrawal")) for u in CFG.get(*k).units)


def test_threshold_by_quarter():
    assert CFG.threshold_for(pd.Timestamp("2026-02-10T12:00Z")) == 27.5   # Q1
    assert CFG.threshold_for(pd.Timestamp("2026-03-31T23:30Z")) == 55.5   # local 1 Apr BST -> Q2
    assert CFG.threshold_for(pd.Timestamp("2026-11-10T12:00Z")) == 55.5   # Q4
