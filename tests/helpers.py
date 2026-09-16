"""Fixture builders shared by the unit tests."""
from __future__ import annotations

import pandas as pd

from remit2.core.normalise import detect_columns, normalise
from remit2.core.operational import build_operational

NOW = pd.Timestamp("2026-09-16T12:00:00Z")
H = pd.Timedelta(hours=1)
D = pd.Timedelta(days=1)
CATS = ["Withdrawal", "Injection", "Storage"]


def mk_remit(thread, site, cat, start, stop, *, avail=None, unavail=None, planned=True,
             status="Active", pub=None, rev=1, tech=None):
    tech = tech if tech is not None else {("Atwick", "Injection"): 30.0, ("Atwick", "Withdrawal"): 130.0,
                                          ("Aldbrough", "Injection"): 293.33, ("Aldbrough", "Withdrawal"): 287.78}[(site, cat)]
    return {
        "threadId": thread, "revisionNumber": rev, "generationUnitName": f"{site} Gas Storage",
        "eventStatus": status, "typeOfUnavailability": "Planned" if planned else "Unplanned",
        "typeOfEvent": f"{cat} unavailability",
        "publicationDateTime": (pub if pub is not None else start - H).strftime("%Y-%m-%dT%H:%M:%S.123Z"),
        "eventStart": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "eventStop": None if stop is None else stop.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unitOfMeasurement": "GWh/d", "unavailableCapacity": unavail, "availableCapacity": avail,
        "technicalCapacity": tech, "reasonForUnavailability": "test", "remarks": "",
        "balancingZone": "GB", "marketParticipant": "SSE", "marketParticipantCode": "X",
        "generationUnitEicCode": "EIC",
    }


COLUMNS = list(mk_remit("T", "Atwick", "Injection", NOW, NOW + H).keys())


def build_df_op(rows: list[dict]) -> pd.DataFrame:
    """Operational frame from raw rows. An empty list yields a correctly typed
    empty frame (built from a dummy row then emptied), because normalise()
    returns an untouched frame when given no rows."""
    dummy = not rows
    raw = pd.DataFrame(rows or [mk_remit("DUMMY", "Atwick", "Injection", NOW, NOW + H)], columns=COLUMNS)
    cmap = detect_columns(raw)
    df = normalise(raw, cmap)
    df_op = build_operational(df, cmap, CATS)
    return df_op.iloc[0:0] if dummy else df_op
