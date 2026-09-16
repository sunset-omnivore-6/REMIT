"""Column detection (tolerant of API key variants) and normalisation to __field__ columns.

Lifted verbatim from REMIT 1.0 app.py @ 3c075a5 by tools/lift_from_v1.py.
Pure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).
"""
from __future__ import annotations

import re

import pandas as pd

from .constants import _unit_factor


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Map logical fields → actual column name in df, tolerating naming variants."""
    norm_map = {_norm(c): c for c in df.columns}

    def find(*candidates: str) -> str | None:
        # exact match first
        for cand in candidates:
            if _norm(cand) in norm_map:
                return norm_map[_norm(cand)]
        # substring fallback
        for cand in candidates:
            cn = _norm(cand)
            for k, v in norm_map.items():
                if cn and cn in k:
                    return v
        return None

    return {
        "asset": find("assetName", "asset", "unitName", "facilityName",
                      "facility", "affectedAssetName", "storageFacility"),
        "unitEic": find("unitEicCode", "unitEic", "eicCode", "assetEic"),
        "eventStart": find(
            "eventStartDateTime", "eventStartTime", "eventStart",
            "outageStart", "startTime", "startDateTime", "startDate",
            "unavailabilityStart", "fromDate", "fromDateTime",
            "from", "begin", "beginDateTime",
        ),
        "eventEnd": find(
            "eventStopDateTime", "eventStopTime", "eventStop",
            "eventEndDateTime", "eventEndTime", "eventEnd",
            "outageEnd", "outageStop", "endTime", "endDateTime", "endDate",
            "stopTime", "stopDateTime", "stopDate",
            "unavailabilityEnd", "toDate", "toDateTime",
            "expectedEnd", "expectedEndDate", "to",
        ),
        "publication": find("publicationDateTime", "publicationDate",
                            "publishedDate", "publishDateTime", "published"),
        "status": find("eventStatus", "status", "state"),
        "typeOfEvent": find("typeOfEvent", "eventType", "unavailabilityCategory"),
        "typeOfUnavailability": find("typeOfUnavailability",
                                     "unavailabilityType", "natureOfUnavailability",
                                     "planningStatus", "planned"),
        "techCapacity": find("technicalCapacity"),
        "availCapacity": find("availableCapacity"),
        "unavailCapacity": find("unavailableCapacity"),
        "unit": find("unitOfMeasurement", "unitOfMeasure", "uom"),
        "reason": find("reasonForTheUnavailability", "reasonForUnavailability",
                       "reason", "cause"),
        "remarks": find("remarks", "comments", "notes", "description"),
        "threadId": find("threadId", "thread"),
        "revisionNumber": find("revisionNumber", "revision", "version"),
        "messageId": find("messageId", "id"),
    }

def _category_from_event(val: object) -> str | None:
    s = str(val).lower()
    if "withdraw" in s:
        return "Withdrawal"
    if "inject" in s:
        return "Injection"
    if "storage" in s:
        return "Storage"
    return None

def _site_from_asset(val: object) -> str | None:
    s = str(val).lower()
    if "atwick" in s:
        return "Atwick"
    if "aldbrough" in s or "aldborough" in s:
        return "Aldbrough"
    return None

def normalise(df: pd.DataFrame, cmap: dict[str, str | None]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    # Asset → Site
    asset_col = cmap["asset"]
    if asset_col is None:
        # Fall back to scanning every column for the site name
        out["__site__"] = None
        for c in out.columns:
            sites = out[c].astype(str).map(_site_from_asset)
            out["__site__"] = out["__site__"].fillna(sites)
    else:
        out["__site__"] = out[asset_col].map(_site_from_asset)

    # Category
    ev_col = cmap["typeOfEvent"]
    if ev_col is not None:
        out["__category__"] = out[ev_col].map(_category_from_event)
    else:
        out["__category__"] = None

    # Dates — always store as a datetime-typed Series so comparisons work
    # even when the source column wasn't detected.
    nat_series = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
    for logical in ("eventStart", "eventEnd", "publication"):
        col = cmap[logical]
        if col is not None:
            # Pin to one resolution: pandas 3 infers s/us/ns per column from
            # the strings (the API mixes fractional and whole seconds), and
            # then refuses cross-resolution assignments between columns.
            out[f"__{logical}__"] = pd.to_datetime(
                out[col], errors="coerce", utc=True, format="ISO8601"
            ).dt.as_unit("ns")
        else:
            out[f"__{logical}__"] = nat_series.copy()

    # Numeric capacities
    for logical in ("techCapacity", "availCapacity", "unavailCapacity"):
        col = cmap[logical]
        out[f"__{logical}__"] = (
            pd.to_numeric(out[col], errors="coerce") if col is not None else pd.NA
        )

    # Unit normalisation: scale capacities to the category's canonical unit
    # (flows GWh/d, storage TWh) using the row's unitOfMeasurement, so the
    # hard-coded nameplate capacities and the API values are always compared
    # in the same unit. Unrecognised units are flagged, never guessed.
    unit_col = cmap["unit"]
    if unit_col is not None:
        raw_unit = out[unit_col].astype(str).map(
            lambda u: re.sub(r"\s+", "", u).lower()
        )
    else:
        raw_unit = pd.Series("", index=out.index)
    factor = pd.Series(
        [_unit_factor(c, u) for c, u in zip(out["__category__"], raw_unit)],
        index=out.index,
        dtype="float64",
    )
    out["__unitUnknown__"] = factor.isna()
    factor = factor.fillna(1.0)
    for logical in ("techCapacity", "availCapacity", "unavailCapacity"):
        out[f"__{logical}__"] = (
            pd.to_numeric(out[f"__{logical}__"], errors="coerce") * factor
        )

    # Status
    status_col = cmap["status"]
    out["__status__"] = out[status_col].astype(str) if status_col else "Active"

    # Planned / Unplanned
    plan_col = cmap["typeOfUnavailability"]
    if plan_col is not None:
        s = out[plan_col].astype(str).str.lower()
        out["__planned__"] = s.map(
            lambda x: "Unplanned" if "unplan" in x else ("Planned" if "plan" in x else "Unknown")
        )
    else:
        out["__planned__"] = "Unknown"

    return out
