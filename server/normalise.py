"""Map raw SSE API rows to the canonical fields the UI uses.

The API field names have drifted over time and may differ across pages.
We do a defensive case-insensitive match per row, so a key rename on
SSE's side won't silently zero out a column.
"""

from __future__ import annotations

from typing import Any

# Canonical field -> ordered list of source-field aliases (case-insensitive).
# First match wins. Substring fallback below catches anything we missed.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "thread_id": ("threadId", "threadID", "thread_id", "messageId", "mrid"),
    "revision_number": ("revisionNumber", "revision", "version"),
    "asset": (
        "affectedAssetOrUnit",
        "affectedAsset",
        "asset",
        "assetOrUnit",
        "assetName",
        "unitName",
        "facilityName",
        "siteName",
        "site",
        "facility",
        "name",
    ),
    "event_status": ("eventStatus", "status", "messageStatus"),
    "type_of_unavailability": ("typeOfUnavailability", "unavailabilityType"),
    "type_of_event": ("typeOfEvent", "eventType"),
    "publication_dt": (
        "publicationDateTime",
        "publishedDateTime",
        "publishDate",
        "publishedAt",
    ),
    "event_start": (
        "eventStart",
        "startDateTime",
        "outageStart",
        "eventStartDateTime",
        "startDate",
    ),
    "event_stop": (
        "eventStop",
        "endDateTime",
        "outageEnd",
        "eventEnd",
        "eventEndDateTime",
        "stopDate",
    ),
    "unit_of_measurement": ("unitOfMeasurement", "uom", "units"),
    "unavailable_capacity": (
        "unavailableCapacity",
        "unavailableCapacityValue",
        "capacity",
    ),
    "available_capacity": ("availableCapacity",),
    "technical_capacity": ("technicalCapacity",),
    "reason": ("reason", "remarks", "comment"),
    "location": ("location",),
    "fuel_type": ("fuelType",),
    "market_participant": ("marketParticipant", "participant"),
}

# Substring patterns used as a last-resort fallback when no exact alias
# matches. Lets us survive minor API field renames without a code change.
SUBSTRING_FALLBACKS: dict[str, tuple[str, ...]] = {
    "asset": ("asset", "unit", "facility", "site"),
    "event_start": ("start",),
    "event_stop": ("end", "stop"),
    "publication_dt": ("publish", "publication"),
}

# Locations we care about (matched case-insensitively against asset / location /
# thread_id).
SSE_STORAGE_SITES = ("Aldbrough", "Atwick")

# Map thread_id prefix → site name. The SSE API mints IDs like
# ALD_… / ATW_… per facility, so when the asset field is empty we can
# still recover the site from the thread ID.
THREAD_ID_PREFIX_SITE = {
    "ALD": "Aldbrough",
    "ATW": "Atwick",
}


def _get_field(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    lower = {k.lower(): k for k in row.keys()}
    for alias in aliases:
        actual = lower.get(alias.lower())
        if actual is not None and row[actual] not in (None, ""):
            return row[actual]
    return None


def _get_field_substring(row: dict[str, Any], patterns: tuple[str, ...]) -> Any:
    for key, value in row.items():
        kl = key.lower()
        for pat in patterns:
            if pat in kl and value not in (None, ""):
                return value
    return None


def _derive_asset_from_thread_id(thread_id: Any) -> str | None:
    if not isinstance(thread_id, str) or "_" not in thread_id:
        return None
    prefix = thread_id.split("_", 1)[0].upper()
    return THREAD_ID_PREFIX_SITE.get(prefix)


def normalise_row(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        out[canonical] = _get_field(raw, aliases)

    # Substring fallbacks for anything still empty.
    for canonical, patterns in SUBSTRING_FALLBACKS.items():
        if out.get(canonical) in (None, ""):
            out[canonical] = _get_field_substring(raw, patterns)

    # Last-resort asset recovery from thread ID prefix.
    if out.get("asset") in (None, ""):
        derived = _derive_asset_from_thread_id(out.get("thread_id"))
        if derived:
            out["asset"] = derived

    return out


def normalise_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalise_row(r) for r in raw_rows]


def filter_to_sse_storage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep rows whose asset, location, or thread_id matches a target site."""
    wanted = tuple(s.lower() for s in SSE_STORAGE_SITES)
    wanted_prefixes = tuple(p.lower() + "_" for p in THREAD_ID_PREFIX_SITE)
    out = []
    for r in rows:
        asset = r.get("asset") or ""
        location = r.get("location") or ""
        thread_id = r.get("thread_id") or ""
        haystack = f"{asset} {location}".lower()
        tid_lower = thread_id.lower()
        if any(site in haystack for site in wanted):
            out.append(r)
        elif any(tid_lower.startswith(p) for p in wanted_prefixes):
            out.append(r)
    return out


def collect_raw_field_names(raw_rows: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
    """Diagnostic helper: what keys does the API actually use?

    Returns a summary of field names seen across a sample of raw rows,
    so we can tighten FIELD_ALIASES to match reality.
    """
    seen: dict[str, int] = {}
    sample = raw_rows[: max(limit, 1)]
    for row in raw_rows:
        for k in row.keys():
            seen[k] = seen.get(k, 0) + 1
    return {
        "total_rows": len(raw_rows),
        "field_frequency": dict(sorted(seen.items(), key=lambda kv: -kv[1])),
        "sample_rows": sample,
    }
