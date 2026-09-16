"""Capacity maths: available capacity at an instant, step changes, exact step series, recent-change classification, formatting helpers.

Lifted verbatim from REMIT 1.0 app.py @ 3c075a5 by tools/lift_from_v1.py.
Pure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).
"""
from __future__ import annotations

import pandas as pd

from .constants import DEFAULT_UNIT, SITES


FRESH_MINUTES = 15

def capacity_at(
    df: pd.DataFrame, site: str, cat: str, t: pd.Timestamp, tech: float
) -> float:
    """Effective available capacity at instant `t`, taking the conservative
    minimum across overlapping events."""
    active = df[
        (df["__site__"] == site)
        & (df["__category__"] == cat)
        & (df["__eventStart__"] <= t)
        & (df["__eventEnd__"].isna() | (df["__eventEnd__"] > t))
    ]
    if active.empty:
        return tech
    avails = active["__availCapacity__"].dropna()
    if not avails.empty:
        return float(avails.min())
    unavail_sum = active["__unavailCapacity__"].fillna(0).sum()
    return max(0.0, float(tech) - float(unavail_sum))

def compute_capacity_changes(
    df_op: pd.DataFrame,
    tech_lookup: dict[tuple[str, str], float],
    categories: list[str],
    lookahead_days: int = 7,
    threshold: float = 0.001,
    now: pd.Timestamp | None = None,
) -> list[dict]:
    """Find every step change in effective available capacity within window.

    threshold is a float-noise epsilon only: every real REMIT-driven step is
    reported, however small."""
    if now is None:
        raise ValueError("now must be supplied (core never reads the wall clock)")
    horizon = now + pd.Timedelta(days=lookahead_days)
    changes: list[dict] = []

    for site in SITES:
        for cat in categories:
            tech = tech_lookup.get((site, cat))
            if tech is None:
                continue
            sub = df_op[(df_op["__site__"] == site) & (df_op["__category__"] == cat)]
            if sub.empty:
                continue

            # Candidate transition moments = event starts AND event ends in window
            starts = sub[
                (sub["__eventStart__"] > now)
                & (sub["__eventStart__"] <= horizon)
            ][["__eventStart__"]].rename(columns={"__eventStart__": "t"})
            ends = sub[
                sub["__eventEnd__"].notna()
                & (sub["__eventEnd__"] > now)
                & (sub["__eventEnd__"] <= horizon)
            ][["__eventEnd__"]].rename(columns={"__eventEnd__": "t"})
            moments = pd.concat([starts, ends]).sort_values("t").drop_duplicates()

            if moments.empty:
                continue

            prev_avail = capacity_at(df_op, site, cat, now, tech)
            for t in moments["t"]:
                # Sample just after the transition
                t_after = t + pd.Timedelta(seconds=1)
                new_avail = capacity_at(df_op, site, cat, t_after, tech)
                if abs(new_avail - prev_avail) >= threshold:
                    # Find the dominant event driving the change at this moment
                    driver_starts = sub[sub["__eventStart__"] == t]
                    driver_ends = sub[sub["__eventEnd__"] == t]
                    driver = (
                        driver_starts.iloc[0]
                        if not driver_starts.empty
                        else (driver_ends.iloc[0] if not driver_ends.empty else None)
                    )
                    changes.append(
                        {
                            "site": site,
                            "category": cat,
                            "when": t,
                            "from": prev_avail,
                            "to": new_avail,
                            "tech": tech,
                            "is_start": not driver_starts.empty,
                            "driver": driver,
                        }
                    )
                    prev_avail = new_avail
    changes.sort(key=lambda c: c["when"])
    return changes

def compute_capacity_series(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    tech_lookup: dict[tuple[str, str], float],
    categories: list[str],
) -> pd.DataFrame:
    """Exact step-function of available capacity per (site, category).

    Capacity only changes at an event start or end, so the step edges sit
    exactly on those breakpoints (a 2-hour outage shows as a precise 2-hour
    dip at any zoom). Each flat segment is then filled with intermediate hover
    points (see fill_step) so the tooltip can read the value at any instant,
    not only at step changes.
    """
    records = []
    # Dense hover grid: each flat segment is filled with intermediate points
    # carrying the segment's held value, so the tooltip can snap to (almost)
    # any instant — not just step boundaries — while the step shape is
    # unchanged (the repeated value renders flat). Hourly for normal horizons;
    # coarsened for very long windows to bound the point count.
    fill_step = max(pd.Timedelta(hours=1), (end - start) / 3000)
    for site in SITES:
        for cat in categories:
            tech = tech_lookup.get((site, cat))
            if tech is None:
                continue
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            sub = sub.dropna(subset=["__eventStart__"])

            # Breakpoints = window edges + every event start/end inside it
            bps: set[pd.Timestamp] = {start, end}
            for _, r in sub.iterrows():
                s = r["__eventStart__"]
                e = r["__eventEnd__"]
                if start <= s <= end:
                    bps.add(s)
                if pd.notna(e) and start <= e <= end:
                    bps.add(e)
            ordered = sorted(bps)

            # For each segment [bp_i, bp_i+1) evaluate capacity at its midpoint;
            # emit the value at the segment's left edge. line_shape="hv" then
            # draws a flat step. A trailing point closes the last segment.
            for i in range(len(ordered) - 1):
                seg_start = ordered[i]
                seg_end = ordered[i + 1]
                mid = seg_start + (seg_end - seg_start) / 2
                avail = capacity_at(df, site, cat, mid, tech)
                # Exact step start.
                records.append(
                    {
                        "date": seg_start,
                        "site": site,
                        "category": cat,
                        "available": avail,
                        "technical": tech,
                    }
                )
                # Intermediate hover points carrying the held value.
                t = seg_start + fill_step
                while t < seg_end:
                    records.append(
                        {
                            "date": t,
                            "site": site,
                            "category": cat,
                            "available": avail,
                            "technical": tech,
                        }
                    )
                    t += fill_step
            if len(ordered) >= 2:
                last_mid = ordered[-2] + (ordered[-1] - ordered[-2]) / 2
                records.append(
                    {
                        "date": ordered[-1],
                        "site": site,
                        "category": cat,
                        "available": capacity_at(df, site, cat, last_mid, tech),
                        "technical": tech,
                    }
                )
    return pd.DataFrame(records)

def compute_recent_changes(
    df: pd.DataFrame,
    cmap: dict[str, str | None],
    lookback_hours: int = 24,
    now: pd.Timestamp | None = None,
) -> list[dict]:
    """REMITs created, revised, ended or dismissed within the lookback window.

    Works from latest-revision data: every revision carries a fresh
    publication timestamp, so a publication inside the window means the
    notice changed since then. `df` (not `df_op`) is used so dismissed
    REMITs are visible here.
    """
    if now is None:
        raise ValueError("now must be supplied (core never reads the wall clock)")
    cutoff = now - pd.Timedelta(hours=lookback_hours)
    rev_col = cmap.get("revisionNumber")

    recent = df[
        df["__site__"].isin(SITES)
        & df["__publication__"].notna()
        & (df["__publication__"] >= cutoff)
    ]
    items: list[dict] = []
    for _, row in recent.iterrows():
        status = str(row["__status__"]).lower()
        end = row["__eventEnd__"]
        rev = row[rev_col] if rev_col else None
        try:
            rev_num = int(float(rev)) if rev is not None and pd.notna(rev) else 1
        except (ValueError, TypeError):
            rev_num = 1

        if "dismiss" in status:
            kind = "Dismissed"
        elif "inactive" in status and (pd.isna(end) or end > now):
            # Marked Inactive before its stop time: retired / superseded.
            # Capacity is released from the publication instant.
            kind = "Retired"
        elif pd.notna(end) and end < now:
            kind = "Ended"
        elif rev_num > 1:
            kind = "Revised"
        else:
            kind = "New"

        items.append(
            {
                "site": row["__site__"],
                "category": row["__category__"] or "—",
                "kind": kind,
                "publication": row["__publication__"],
                "rev_num": rev_num,
                "row": row,
            }
        )
    items.sort(key=lambda x: x["publication"], reverse=True)
    return items

def short_thread(thread) -> str:
    """Strip a REMIT thread id's zero-padding for display:
    'ALD_000000000000000001261' -> 'ALD_1261', '00000079' -> '79'."""
    t = str(thread or "").strip()
    if not t:
        return t
    if "_" in t:
        prefix, num = t.rsplit("_", 1)
        return f"{prefix}_{num.lstrip('0') or '0'}"
    return t.lstrip("0") or "0"

def fmt_dt(dt) -> str:
    if pd.isna(dt):
        return "—"
    return dt.strftime("%d %b %Y, %H:%M")

def fmt_qty(v, category: str) -> str:
    """Capacity value at per-category precision: TWh to 2 dp, flows to 1 dp."""
    if v is None or pd.isna(v):
        return "—"
    dp = 2 if DEFAULT_UNIT.get(category) == "TWh" else 1
    return f"{float(v):.{dp}f}"
