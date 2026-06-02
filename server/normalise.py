"""Map raw SSE API rows to the canonical fields the UI uses.

The API field names have drifted over time and may differ across pages.
We do a defensive case-insensitive match per row, so a key rename on
SSE's side won't silently zero out a column.
"""

from __future__ import annotations

from typing import Any

# Canonical field -> ordered list of source-field aliases (case-insensitive).
# First match wins.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "thread_id": ("threadId", "threadID", "thread_id"),
    "revision_number": ("revisionNumber", "revision"),
    "asset": ("affectedAssetOrUnit", "affectedAsset", "asset", "assetOrUnit"),
    "event_status": ("eventStatus", "status"),
    "type_of_unavailability": ("typeOfUnavailability", "unavailabilityType"),
    "type_of_event": ("typeOfEvent", "eventType"),
    "publication_dt": ("publicationDateTime", "publishedDateTime", "publishDate"),
    "event_start": ("eventStart", "startDateTime", "outageStart"),
    "event_stop": ("eventStop", "endDateTime", "outageEnd", "eventEnd"),
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

# Locations we care about (matched case-insensitively against asset/location).
SSE_STORAGE_SITES = ("Aldbrough", "Atwick")


def _get_field(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    # Build lowercase lookup once per row would be faster, but row count
    # is small and this is clearer.
    lower = {k.lower(): k for k in row.keys()}
    for alias in aliases:
        actual = lower.get(alias.lower())
        if actual is not None:
            return row[actual]
    return None


def normalise_row(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        out[canonical] = _get_field(raw, aliases)
    return out


def normalise_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalise_row(r) for r in raw_rows]


def filter_to_sse_storage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep rows whose asset or location matches an SSE storage site."""
    wanted = tuple(s.lower() for s in SSE_STORAGE_SITES)
    out = []
    for r in rows:
        asset = (r.get("asset") or "")
        location = (r.get("location") or "")
        haystack = f"{asset} {location}".lower()
        if any(site in haystack for site in wanted):
            out.append(r)
    return out
