"""Golden-value tests for the remit_availability engine.

These fixtures encode the adjudicated reference cases from the migration
brief — if any test fails, the engine has REGRESSED against the validated
invariants. Run with: python -m pytest test_remit_availability.py
(or: python test_remit_availability.py)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from remit_availability import EXPECTED_KEYS, compute_availability

# SY2025 (1 May 2025 -> 30 Apr 2026) is fully in the past => deterministic
# 365-day window regardless of when the tests run.
SY = 2025
CAPS = {"Aldbrough": 262.0, "Atwick": 100.0}
N_DAYS = 365

# During BST, local midnight = 23:00Z the previous calendar day. Fixtures use
# 23:00Z boundaries so event edges land exactly on local midnights.


def mk_rev(
    thread,
    rev,
    pub,
    start,
    stop,
    avail,
    status="Active",
    site="Aldbrough",
):
    return {
        "threadId": thread,
        "revisionNumber": rev,
        "generationUnitName": f"{site} Gas Storage",
        "eventStatus": status,
        "typeOfUnavailability": "Planned",
        "typeOfEvent": "Withdrawal unavailability",
        "publicationDateTime": pub,
        "eventStart": start,
        "eventStop": stop,
        "unitOfMeasurement": "GWh/d",
        "unavailableCapacity": 999.0,  # never used; poison value guards rule 4
        "availableCapacity": avail,
        "technicalCapacity": 888.0,  # never used; poison value
        "reasonForUnavailability": "test",
        "remarks": "",
        "balancingZone": "UK",
        "marketParticipant": "SSE",
        "marketParticipantCode": "X",
        "generationUnitEicCode": "EIC",
    }


def run(rows, caps=CAPS, sy=SY):
    df = pd.DataFrame(rows, columns=EXPECTED_KEYS)
    return compute_availability(df, sy, caps)


def val(out, date_label, col):
    return out.loc[out["Date"] == date_label, col].iloc[0]


ALD = "Aldbrough avail GWh/d"
ATW = "Atwick avail GWh/d"


def test_flat_profiling_guard():
    # avail 62 -> revised to 44 two days later: day 1-2 use 62 (revision-locked),
    # days from the publication use 44. Capacity is never backdated.
    out = run([
        mk_rev("T1", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T23:00:00Z", 62.0),
        mk_rev("T1", 2, "2025-06-02T23:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T23:00:00Z", 44.0),
    ])
    assert val(out, "01-Jun", ALD) == 62.0
    assert val(out, "02-Jun", ALD) == 62.0
    assert val(out, "03-Jun", ALD) == 44.0
    assert val(out, "10-Jun", ALD) == 44.0
    assert pd.isna(val(out, "11-Jun", ALD))


def test_retroactive_window():
    # rev 1 typo'd start (April), corrected 16 minutes later to June (outside
    # this SY window): the latest revision's window applies retroactively, so
    # the April days show full availability (blank at cap).
    out = run([
        mk_rev("T2", 1, "2026-04-17T00:00:00Z", "2026-04-18T00:00:00Z",
               "2026-04-29T00:00:00Z", 0.0),
        mk_rev("T2", 2, "2026-04-17T00:16:00Z", "2026-06-18T00:00:00Z",
               "2026-06-29T00:00:00Z", 0.0),
    ])
    for d in range(18, 29):
        assert pd.isna(val(out, f"{d:02d}-Apr", ALD)), f"{d}-Apr not at cap"
    assert out["Aldbrough midrev flag"].sum() == 0
    assert out["Aldbrough posthumous flag"].sum() == 0


def test_dismissed_latest_never_ran():
    # Latest revision Dismissed (published AFTER its start) => thread skipped
    # entirely — no phantom dark hour.
    out = run([
        mk_rev("T3", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T23:00:00Z", 0.0),
        mk_rev("T3", 2, "2025-06-01T00:13:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T23:00:00Z", 0.0, status="Dismissed"),
    ])
    assert out[ALD].isna().all()

    # ...but a thread with an intermediate Dismissed revision and a live
    # latest revision resurrects and counts.
    out2 = run([
        mk_rev("T4", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-02T23:00:00Z", 0.0),
        mk_rev("T4", 2, "2025-05-30T01:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-02T23:00:00Z", 0.0, status="Dismissed"),
        mk_rev("T4", 3, "2025-05-30T02:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-02T23:00:00Z", 0.0, status="Active"),
    ])
    assert val(out2, "01-Jun", ALD) == 0.0
    assert val(out2, "02-Jun", ALD) == 0.0


def test_early_termination():
    # rev 2 moves the stop earlier: minutes after the actual stop are
    # available (latest window governs), pre-publication capacity unaffected.
    out = run([
        mk_rev("T5", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T23:00:00Z", 100.0),
        mk_rev("T5", 2, "2025-06-04T23:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-05T23:00:00Z", 100.0),
    ])
    for d in ("01-Jun", "02-Jun", "03-Jun", "04-Jun", "05-Jun"):
        assert val(out, d, ALD) == 100.0
    for d in ("06-Jun", "07-Jun", "10-Jun"):
        assert pd.isna(val(out, d, ALD))
    # The stop change published mid-event flags midrev on the publication's
    # local date (5 Jun local).
    assert val(out, "05-Jun", "Aldbrough midrev flag") == 1


def test_overlap_minimum():
    # Two simultaneous remits: avail 220.8 and 0 => level 0 (tightest
    # constraint governs; availabilities are never summed/subtracted).
    out = run([
        mk_rev("T6", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-03T23:00:00Z", 220.8),
        mk_rev("T7", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-03T23:00:00Z", 0.0),
    ])
    for d in ("01-Jun", "02-Jun", "03-Jun"):
        assert val(out, d, ALD) == 0.0
    # Full outage plus a partial: the full outage governs.
    out2 = run([
        mk_rev("T8", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-03T23:00:00Z", 0.0),
        mk_rev("T9", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-03T23:00:00Z", 150.0),
    ])
    assert val(out2, "02-Jun", ALD) == 0.0


def test_blank_avail_and_missing_stop():
    # Blank availableCapacity = 0 ("no available capacity", not "unknown");
    # missing eventStop = indefinitely active (to the window end).
    out = run([
        mk_rev("T10", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               None, np.nan),
    ])
    assert val(out, "01-Jun", ALD) == 0.0
    assert val(out, "30-Apr", ALD) == 0.0  # last day of the SY window


def test_at_cap_blanking_dtype_and_rows():
    out = run([
        mk_rev("T11", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-02T23:00:00Z", 50.0),
    ])
    assert len(out) == N_DAYS  # rows never shift
    assert out[ALD].dtype == np.float64  # NaN blanking keeps the column float
    assert out[ATW].dtype == np.float64
    assert out[ALD].notna().sum() == 2  # only the two outage days carry values
    assert out[ATW].isna().all()  # untouched site fully blank at cap


def test_dst_boundary():
    # A remit stopping 04:00Z in June ends 05:00 local (BST); the stop day has
    # exactly 5 local hours of outage. Day attribution follows local midnight.
    out = run([
        mk_rev("T12", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-10T04:00:00Z", 0.0, site="Atwick"),
    ])
    assert val(out, "09-Jun", ATW) == 0.0  # fully dark
    # 10 Jun: 300 min at 0 + 1140 min at cap(100) => 1140*100/1440 = 79.17
    assert val(out, "10-Jun", ATW) == 79.17
    assert pd.isna(val(out, "11-Jun", ATW))


def test_posthumous_flag():
    # Revision published AFTER the previous stop: flags the STOP's local date
    # (6 Jun local for a 23:00Z 5 Jun stop) and changes no numbers.
    out = run([
        mk_rev("T13", 1, "2025-05-30T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-05T23:00:00Z", 50.0),
        mk_rev("T13", 2, "2025-06-20T00:00:00Z", "2025-05-31T23:00:00Z",
               "2025-06-05T23:00:00Z", 40.0),
    ])
    for d in ("01-Jun", "05-Jun"):
        assert val(out, d, ALD) == 50.0  # numbers unchanged by the late rev
    assert val(out, "06-Jun", "Aldbrough posthumous flag") == 1
    assert out["Aldbrough midrev flag"].sum() == 0


if __name__ == "__main__":
    import sys

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failed else 0)
