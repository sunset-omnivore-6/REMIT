"""Operational dataset: status handling (Dismissed / Inactive clamp), latest-revision dedup, active/upcoming slices.

Lifted verbatim from REMIT 1.0 app.py @ 3c075a5 by tools/lift_from_v1.py.
Pure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).
"""
from __future__ import annotations

import pandas as pd

from .constants import SITES, TECH_CAPACITY_FALLBACK


def active_now(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["__eventStart__"] <= now) & (
        df["__eventEnd__"].isna() | (df["__eventEnd__"] >= now)
    )
    return df[mask]

def upcoming(df: pd.DataFrame, now: pd.Timestamp, horizon_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    horizon = now + pd.Timedelta(days=horizon_days)
    mask = (df["__eventStart__"] > now) & (df["__eventStart__"] <= horizon)
    return df[mask].sort_values("__eventStart__")

def status_flags(status: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(dismissed, inactive) boolean masks from an eventStatus series."""
    s = status.astype(str).str.lower()
    return s.str.contains("dismiss", na=False), s.str.contains("inactive", na=False)

def build_operational(
    df: pd.DataFrame, cmap: dict[str, str | None], categories: list[str]
) -> pd.DataFrame:
    """Operational dataset: known site + category, not Dismissed, latest
    revision per thread — with 'Inactive' notices in force only until the
    revision that retired them was published.

    SSE retires a notice by publishing a revision whose eventStatus is
    'Inactive' (not 'Dismissed'), and uses the same status when an outage
    simply ends. The two are told apart by timing: an outage that ended
    naturally already has its stop at/before that publication (clamping is a
    no-op), whereas a notice retired or superseded early still carries a
    future stop. Pulling that stop back to the retirement instant releases
    the capacity in every operational view (wheels, active outages, upcoming
    changes, timeline, calendar, conflicts) while the reconstructed past still
    shows the period the notice genuinely ran. The original stop is kept in
    `df` (Recent changes / All data) untouched.
    """
    dismissed, _ = status_flags(df["__status__"])
    out = df[
        df["__site__"].isin(SITES)
        & ~dismissed
        & df["__category__"].isin(categories)
    ].copy()
    if out.empty:
        return out

    _, inactive = status_flags(out["__status__"])
    clamp = inactive & out["__publication__"].notna()
    if clamp.any():
        end = out["__eventEnd__"]
        pub = out["__publication__"]
        # Keep the stop where it is already at/before the retirement; pull it
        # back to the retirement instant otherwise (NaT stop -> retirement).
        # Whole-column replacement (not .loc into a slice) so a resolution
        # mismatch can never trigger pandas 3's upcast TypeError.
        out["__eventEnd__"] = end.where(~clamp | (end <= pub), pub)

    # Safety net: keep only the latest revision per thread. The API already
    # does this via revisionsReturned=Latest, so this is a no-op on normal
    # data. Rows without a thread id are left untouched (never collapsed).
    thr = cmap.get("threadId")
    rev = cmap.get("revisionNumber")
    if thr and rev and thr in out.columns:
        valid = out[thr].notna() & (out[thr].astype(str).str.strip() != "")
        if valid.any():
            deduped = (
                out[valid]
                .assign(__rev__=pd.to_numeric(out.loc[valid, rev], errors="coerce").fillna(-1))
                .sort_values("__rev__")
                .drop_duplicates(subset=[thr], keep="last")
                .drop(columns="__rev__")
            )
            out = pd.concat([deduped, out[~valid]]).sort_index()
    return out

def site_category_headline(
    df_active: pd.DataFrame,
    df_all_site: pd.DataFrame,
    site: str,
    category: str,
) -> tuple[float, float, float, bool, int]:
    """Return (tech, available, unavailable, has_unplanned, n_events).

    Technical capacity is sourced in order of preference:
      1. hard-coded nameplate value (TECH_CAPACITY_FALLBACK) — authoritative
      2. max from currently-active events for this (site, cat)
      3. max from any (latest-revision) event for this (site, cat)
    """
    sub = df_active[
        (df_active["__site__"] == site) & (df_active["__category__"] == category)
    ]
    tech = TECH_CAPACITY_FALLBACK.get((site, category), float("nan"))
    if pd.isna(tech):
        tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
    if pd.isna(tech):
        all_sub = df_all_site[df_all_site["__category__"] == category]
        tech = all_sub["__techCapacity__"].dropna().max() if not all_sub.empty else float("nan")

    if sub.empty:
        return (float(tech), float("nan"), 0.0, False, 0)

    available = sub["__availCapacity__"].dropna().min()
    unavailable = sub["__unavailCapacity__"].dropna().sum()
    # Fallback (mirrors _capacity_at): if active events report no
    # availableCapacity, derive it from tech - SUM(unavailable) so the wheel can
    # never read full while an outage is active. No-op when availableCapacity is
    # present (the normal case), so it changes nothing under normal data.
    if pd.isna(available) and pd.notna(tech):
        available = max(0.0, float(tech) - float(unavailable))
    has_unplanned = (sub["__planned__"] == "Unplanned").any()
    return (
        float(tech) if pd.notna(tech) else float("nan"),
        float(available) if pd.notna(available) else float("nan"),
        float(unavailable),
        bool(has_unplanned),
        len(sub),
    )

def tech_capacity_lookup(
    df: pd.DataFrame, categories: list[str]
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for site in SITES:
        for cat in categories:
            # Nameplate values are authoritative when known.
            if (site, cat) in TECH_CAPACITY_FALLBACK:
                out[(site, cat)] = TECH_CAPACITY_FALLBACK[(site, cat)]
                continue
            sub = df[(df["__site__"] == site) & (df["__category__"] == cat)]
            tech = sub["__techCapacity__"].dropna().max() if not sub.empty else float("nan")
            if pd.notna(tech) and tech > 0:
                out[(site, cat)] = float(tech)
    return out
