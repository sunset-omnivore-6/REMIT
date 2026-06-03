"""Rolling history of dial values, sampled on every successful refresh.

Powers the dial sparklines (and any future deltas / "this is the 5th
unplanned outage this month" context). Storing the COMPUTED dial values
rather than raw snapshots keeps the file small — ~250 bytes per sample,
~70KB per day at the 5-minute refresh cadence.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_PATH = DATA_DIR / "dial_history.jsonl"
HISTORY_MAX_DAYS = 30  # hard cap; trimmed on append

# Hard-coded nameplate tech maxima — must match web/aggregate.js
# TECH_CAPACITY exactly. Source of truth is app.py:79-85.
SITES = ("Aldbrough", "Atwick")
CATEGORIES = ("Withdrawal", "Injection", "Storage")
TECH_CAPACITY: dict[str, dict[str, float]] = {
    "Aldbrough": {"Withdrawal": 287.78, "Injection": 293.33, "Storage": 3.3},
    "Atwick":    {"Withdrawal": 130.0,  "Injection": 30.0,   "Storage": 3.47},
}


def _categorise(type_of_event: Any) -> str | None:
    if not type_of_event:
        return None
    head = str(type_of_event).strip().split()
    if not head:
        return None
    first = head[0]
    return first if first in CATEGORIES else None


def _parse_ts_ms(s: Any) -> int | None:
    if not s:
        return None
    try:
        text = str(s)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _is_dismissed(r: dict) -> bool:
    return "dismiss" in (r.get("event_status") or "").lower()


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def compute_dial_values(normalised_rows: list[dict], at_ms: int | None = None) -> dict[str, float]:
    """Compute available capacity for every (site, category) at instant at_ms.

    Mirrors web/aggregate.js:computeSiteCategoryStatus exactly:
      - Filter to non-Dismissed rows for this (site, category) active at at_ms
      - If any reportedAvailable values present: take MIN
      - Otherwise: max(0, tech - SUM(unavailable))
      - If no active rows: tech_max
    """
    if at_ms is None:
        at_ms = int(time.time() * 1000)

    out: dict[str, float] = {}
    for site, cats in TECH_CAPACITY.items():
        site_lower = site.lower()
        for category, tech_max in cats.items():
            active = []
            for r in normalised_rows:
                if _is_dismissed(r):
                    continue
                if (r.get("asset") or "").lower() != site_lower:
                    continue
                if _categorise(r.get("type_of_event")) != category:
                    continue
                start_ms = _parse_ts_ms(r.get("event_start"))
                stop_ms = _parse_ts_ms(r.get("event_stop"))
                if start_ms is None or stop_ms is None:
                    continue
                if not (start_ms <= at_ms < stop_ms):
                    continue
                active.append(r)

            if not active:
                out[f"{site}.{category}"] = float(tech_max)
                continue

            avails = [
                v for r in active
                if (v := _as_float(r.get("available_capacity"))) is not None
            ]
            if avails:
                out[f"{site}.{category}"] = float(min(avails))
                continue

            unavail_sum = sum(
                v for r in active
                if (v := _as_float(r.get("unavailable_capacity"))) is not None
            )
            out[f"{site}.{category}"] = max(0.0, float(tech_max) - unavail_sum)

    return out


def append_sample(normalised_rows: list[dict], fetched_at: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    values = compute_dial_values(normalised_rows)
    sample = {"t": fetched_at, "values": values}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample) + "\n")
    _trim()


def _trim() -> None:
    """Drop samples older than HISTORY_MAX_DAYS. Cheap rewrite — the file
    is small (~70KB/day) so a full read+filter+write is fine."""
    if not HISTORY_PATH.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_MAX_DAYS)
    kept: list[str] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                t = _parse_iso(json.loads(stripped).get("t", ""))
                if t and t >= cutoff:
                    kept.append(line)
            except (json.JSONDecodeError, ValueError):
                continue
    HISTORY_PATH.write_text("".join(kept), encoding="utf-8")


def _parse_iso(text: str) -> datetime | None:
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def read_samples(hours: int = 24) -> list[dict]:
    """Return samples from the last N hours, oldest first."""
    if not HISTORY_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: list[dict] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                sample = json.loads(stripped)
                t = _parse_iso(sample.get("t", ""))
                if t and t >= cutoff:
                    out.append(sample)
            except (json.JSONDecodeError, ValueError):
                continue
    out.sort(key=lambda s: s.get("t", ""))
    return out
