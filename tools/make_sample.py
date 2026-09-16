"""Synthetic but API-shaped REMIT sample (the sandbox cannot reach SSE).

Keys are the verified live JSON keys. Dates are anchored on NOW so the
sample exercises: active planned/unplanned outages at both sites, a future
planned outage, a revised thread, an Inactive natural end, an Inactive
retirement (stop still in the future -> clamped), a Dismissed thread, an
overlap at one site/direction, a storage notice, and mixed fractional /
whole-second timestamps (the pandas-3 resolution trap).
"""
import json
from pathlib import Path

import pandas as pd

NOW = pd.Timestamp("2026-09-16T12:00:00Z")
H = pd.Timedelta(hours=1)
D = pd.Timedelta(days=1)


def iso(ts, frac=False):
    if ts is None:
        return None
    s = ts.strftime("%Y-%m-%dT%H:%M:%S")
    return s + (".1234567Z" if frac else "Z")


def row(thread, rev, site, kind, cat, status, pub, start, stop, unavail, avail, tech, reason, frac=True):
    return {
        "threadId": thread, "revisionNumber": rev,
        "generationUnitName": f"{site} Gas Storage",
        "eventStatus": status, "typeOfUnavailability": kind,
        "typeOfEvent": f"{cat} unavailability",
        "publicationDateTime": iso(pub, frac), "eventStart": iso(start), "eventStop": iso(stop),
        "unitOfMeasurement": "TWh" if cat == "Storage" else "GWh/d",
        "unavailableCapacity": unavail, "availableCapacity": avail, "technicalCapacity": tech,
        "reasonForUnavailability": reason, "remarks": "",
        "balancingZone": "GB", "marketParticipant": "SSE Hornsea Ltd",
        "marketParticipantCode": "SSEH", "generationUnitEicCode": "21W000000000000X",
    }


rows = [
    # Hornsea withdrawal: unplanned, active now (Vortisep-sized) for 2 days
    row("ATW_000000000000000001401", 1, "Atwick", "Unplanned", "Withdrawal", "Active",
        NOW - 5 * H, NOW - 5 * H, NOW + 2 * D, 30.0, 100.0, 130.0, "Unplanned Outage"),
    # Hornsea injection: planned, revised (rev 2 moved stop later), starts tomorrow 09:00
    row("ATW_000000000000000001402", 1, "Atwick", "Planned", "Injection", "Active",
        NOW - 30 * H, NOW + 21 * H, NOW + 4 * D, 15.0, 15.0, 30.0, "Planned Outage — 2 comps", frac=False),
    row("ATW_000000000000000001402", 2, "Atwick", "Planned", "Injection", "Active",
        NOW - 3 * H, NOW + 21 * H, NOW + 5 * D, 15.0, 15.0, 30.0, "Planned Outage — 2 comps"),
    # Hornsea injection: RETIRED (Inactive, stop still future) -> clamp at its publication
    row("00001126", 4, "Atwick", "Planned", "Injection", "Inactive",
        NOW - 1 * H, NOW - 4 * H, NOW + 6 * D, 30.0, 0.0, 30.0, "Planned Outage — superseded by 1402"),
    # Hornsea injection: natural end (Inactive, stop before publication), 10 days ago
    row("ATW_000000000000000001282", 3, "Atwick", "Planned", "Injection", "Inactive",
        NOW - 10 * D + 4 * H, NOW - 10 * D, NOW - 10 * D + 4 * H - pd.Timedelta(minutes=3), 30.0, 0.0, 30.0, "Planned Outage"),
    # Aldbrough withdrawal: planned, future (in 3 days, 12 h), 143.89 unavailable (one train)
    row("ALD_000000000000000001303", 1, "Aldbrough", "Planned", "Withdrawal", "Active",
        NOW - 2 * D, NOW + 3 * D, NOW + 3 * D + 12 * H, 143.89, 143.89, 287.78, "Planned Outage — Train 2 maintenance"),
    # Aldbrough injection: unplanned, active, overlapping with a second notice (min governs)
    row("ALD_000000000000000001304", 1, "Aldbrough", "Unplanned", "Injection", "Active",
        NOW - 20 * H, NOW - 20 * H, NOW + 1 * D, 74.44, 218.89, 293.33, "Unplanned Outage"),
    row("ALD_000000000000000001305", 1, "Aldbrough", "Planned", "Injection", "Active",
        NOW - 8 * H, NOW - 6 * H, NOW + 10 * H, 97.78, 195.55, 293.33, "Planned Outage — Comp 1", frac=False),
    # Aldbrough withdrawal: DISMISSED thread (must contribute nothing)
    row("ALD_000000000000000001306", 2, "Aldbrough", "Planned", "Withdrawal", "Dismissed",
        NOW - 1 * D, NOW + 1 * D, NOW + 2 * D, 287.78, 0.0, 287.78, "Duplicate publication"),
    # Aldbrough storage notice (out of hero scope)
    row("ALD_000000000000000001307", 1, "Aldbrough", "Planned", "Storage", "Active",
        NOW - 3 * D, NOW - 3 * D, NOW + 30 * D, 0.55, 2.75, 3.3, "Planned Outage — cavern"),
    # Hornsea withdrawal: past ended outage 6 days ago (history in the back-window)
    row("ATW_000000000000000001390", 1, "Atwick", "Unplanned", "Withdrawal", "Active",
        NOW - 6 * D, NOW - 6 * D, NOW - 5 * D, 130.0, 0.0, 130.0, "Unplanned Outage — trip"),
]
out = Path(__file__).resolve().parents[1] / "data" / "samples" / "remit_sample.json"
out.write_text(json.dumps({"now": iso(NOW), "items": rows}, indent=1), encoding="utf-8")
print(f"wrote {out} ({len(rows)} rows)")
