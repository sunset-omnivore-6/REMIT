"""Revision-aware daily withdrawal-availability engine.

Pure pandas/numpy — no Streamlit imports, unit-testable stand-alone.

For each local calendar day of a storage year (1 May -> 30 Apr, capped at
today, complete days only) this computes the mean available withdrawal
capacity per site, reconstructed from SSE REMIT publications
revision-by-revision. The rules implemented here are VALIDATED INVARIANTS,
proven day-by-day against two storage years of adjudicated reference data —
do not simplify, "improve", or reinterpret them:

1. Dismissed-latest = never ran: a thread whose latest revision (by
   publication time) is Dismissed contributes nothing, regardless of when
   the dismissal was published. Threads with Dismissed *intermediate*
   revisions but a live latest revision are kept (they resurrect).
2. WHEN it ran comes from the latest revision's eventStart/eventStop and
   applies retroactively (start/stop values are corrections of fact).
3. WHAT capacity applied is revision-locked: each active minute uses the
   newest revision published at or before that minute; capacity changes are
   forward-only from publication, never backdated.
4. Overlapping remits: the level is the MINIMUM of the applicable available
   capacities (each capped at site max) — never summed or subtracted.
   unavailableCapacity / technicalCapacity are never used in the maths.
5. Daily value = mean of the 1-minute series over the local day's minutes;
   days with no active remit sit at the site max.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOCAL = "Europe/London"

# JSON keys of the SSE gasuof API, verified live. Asserted on every load so a
# schema change fails loudly instead of silently dropping columns.
EXPECTED_KEYS = [
    "threadId",
    "revisionNumber",
    "generationUnitName",
    "eventStatus",
    "typeOfUnavailability",
    "typeOfEvent",
    "publicationDateTime",
    "eventStart",
    "eventStop",
    "unitOfMeasurement",
    "unavailableCapacity",
    "availableCapacity",
    "technicalCapacity",
    "reasonForUnavailability",
    "remarks",
    "balancingZone",
    "marketParticipant",
    "marketParticipantCode",
    "generationUnitEicCode",
]


def assert_schema(df: pd.DataFrame) -> None:
    """Fail loudly if the API schema drifted from EXPECTED_KEYS."""
    missing = [k for k in EXPECTED_KEYS if k not in df.columns]
    if missing:
        raise ValueError(
            "SSE REMIT API schema changed — missing expected keys: "
            + ", ".join(missing)
        )


def storage_year_window(storage_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[1 May SY, 1 May SY+1) in local time, end capped at today's local
    midnight so only complete days are included."""
    y_start = pd.Timestamp(f"{storage_year}-05-01").tz_localize(LOCAL)
    y_end = min(
        pd.Timestamp(f"{storage_year + 1}-05-01").tz_localize(LOCAL),
        pd.Timestamp.now(tz=LOCAL).normalize(),
    )
    return y_start, y_end


def compute_availability(
    df_revisions: pd.DataFrame,
    storage_year: int,
    caps: dict[str, float],
) -> pd.DataFrame:
    """Daily mean available withdrawal capacity per site for a storage year.

    df_revisions: raw API rows, EVERY revision (revisionsReturned=All),
    columns exactly as EXPECTED_KEYS. caps: {"Aldbrough": .., "Atwick": ..}
    site max capacities in GWh/d (also the site-name match keys and the
    output column order).

    Returns the display table: Date (DD-Mon), then per site avail GWh/d
    (2 dp, NaN where the day equals the cap so the column stays float),
    midrev flag and posthumous flag (integer counts, 0 = clean).
    """
    assert_schema(df_revisions)

    y_start, y_end = storage_year_window(storage_year)
    if y_end <= y_start:
        raise ValueError(
            f"Storage year {storage_year} has no complete days yet."
        )
    y_end_utc = y_end.tz_convert("UTC")

    r = df_revisions[df_revisions["typeOfEvent"] == "Withdrawal unavailability"].copy()
    # Timestamps mix fractional and non-fractional seconds — ISO8601 mode is
    # required; a fixed format string crashes.
    r["publicationDateTime"] = pd.to_datetime(
        r["publicationDateTime"], format="ISO8601", utc=True
    )
    r["eventStart"] = pd.to_datetime(r["eventStart"], format="ISO8601", utc=True)
    # Missing stop = indefinitely active (runs to the analysis window end).
    r["eventStop"] = pd.to_datetime(
        r["eventStop"], format="ISO8601", utc=True
    ).fillna(y_end_utc)
    # Blank availableCapacity means "no available capacity", not "unknown".
    r["availableCapacity"] = pd.to_numeric(
        r["availableCapacity"], errors="coerce"
    ).fillna(0)

    minutes = pd.date_range(y_start, y_end, freq="min", inclusive="left")
    day = minutes.tz_convert(LOCAL).date
    mins_utc = minutes.values
    out = pd.DataFrame(index=pd.Index(sorted(set(day)), name="Day"))

    for site, cap in caps.items():
        sub = r[r["generationUnitName"].str.contains(site, case=False, na=False)]
        # Float init is deliberate: an int cap makes later float assignment
        # warn/error on dtype.
        avail = pd.Series(float(cap), index=minutes)
        midrev = pd.Series(0, index=out.index)
        posth = pd.Series(0, index=out.index)

        for _tid, g in sub.groupby("threadId"):
            g = g.sort_values("publicationDateTime")
            last = g.iloc[-1]
            if str(last["eventStatus"]).lower() == "dismissed":
                continue  # dismissed-latest = never ran
            # Window: the latest revision's start/stop, applied retroactively.
            act = (mins_utc >= last["eventStart"].to_datetime64()) & (
                mins_utc < last["eventStop"].to_datetime64()
            )
            # Capacity: revision-locked — newest revision published at or
            # before each minute; minutes before the first publication use
            # revision 1's value. Forward-only, never backdated.
            idx = np.clip(
                np.searchsorted(
                    g["publicationDateTime"].values, mins_utc, side="right"
                )
                - 1,
                0,
                len(g) - 1,
            )
            vals = np.minimum(g["availableCapacity"].values[idx], cap)
            # Overlapping remits: tightest constraint governs.
            avail[act] = np.minimum(avail[act], vals[act])

            # Flags: compare each revision to its immediate predecessor.
            for i in range(1, len(g)):
                prev, cur = g.iloc[i - 1], g.iloc[i]
                changed = (
                    cur["availableCapacity"] != prev["availableCapacity"]
                    or cur["eventStop"] != prev["eventStop"]
                )
                pub = cur["publicationDateTime"]
                if pub > prev["eventStop"]:
                    # Posthumous: anchored to the remit's stop local date
                    # (the publication may fall outside the window). Changes
                    # no numbers — no future minutes remain — only flags.
                    d = prev["eventStop"].tz_convert(LOCAL).date()
                    if d in posth.index:
                        posth[d] += 1
                elif changed and pub >= cur["eventStart"]:
                    d = pub.tz_convert(LOCAL).date()
                    if d in midrev.index:
                        midrev[d] += 1

        out[f"{site} avail GWh/d"] = avail.groupby(day).mean().round(2)
        out[f"{site} midrev flag"] = midrev
        out[f"{site} posthumous flag"] = posth

    out.insert(0, "Date", [d.strftime("%d-%b") for d in out.index])
    for site, cap in caps.items():
        col = f"{site} avail GWh/d"
        # At-cap days go blank via NaN — NEVER "" (a mixed float/str object
        # column crashes Arrow serialisation) — so the column stays float and
        # rows never shift.
        out[col] = out[col].where(out[col].round(2) < round(cap, 2))
    return out.reset_index(drop=True)
