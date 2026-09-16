"""Time helpers: everything is stored/computed in UTC (ns), entered and shown
in Europe/London with the zone named. Pure — no Streamlit."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

LONDON = ZoneInfo("Europe/London")
UTC = "UTC"


def parse_iso(value) -> pd.Timestamp:
    """ISO-8601 string (or Timestamp) -> tz-aware UTC Timestamp at ns resolution.
    Naive input is taken as UTC. Raises on unparseable input."""
    ts = pd.Timestamp(value)
    if ts is pd.NaT:
        raise ValueError(f"not a timestamp: {value!r}")
    if ts.tz is None:
        ts = ts.tz_localize(UTC)
    return ts.tz_convert(UTC).as_unit("ns")


def to_utc(local_naive: datetime | pd.Timestamp) -> pd.Timestamp:
    """A naive Europe/London wall time (as entered by ops) -> UTC ns Timestamp.
    Ambiguous autumn-fallback times take the first (BST) occurrence; times in
    the spring-forward gap shift forward."""
    ts = pd.Timestamp(local_naive)
    if ts.tz is not None:
        return ts.tz_convert(UTC).as_unit("ns")
    return ts.tz_localize(LONDON, ambiguous=True, nonexistent="shift_forward").tz_convert(UTC).as_unit("ns")


def to_local(ts: pd.Timestamp) -> pd.Timestamp:
    return parse_iso(ts).tz_convert(LONDON)


def fmt_local(ts, with_year: bool = False) -> str:
    """'Thu 18 Sep 06:00 BST' (or with year) — always names the zone."""
    if ts is None or pd.isna(ts):
        return "—"
    loc = to_local(ts)
    return loc.strftime("%a %d %b %Y %H:%M %Z" if with_year else "%a %d %b %H:%M %Z")


def iso_utc(ts: pd.Timestamp) -> str:
    """Canonical storage form: 'YYYY-MM-DDTHH:MM:SSZ'."""
    return parse_iso(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def quarter_of(ts: pd.Timestamp) -> str:
    """Calendar quarter of the LOCAL date: 'Q1'..'Q4' (Q1 = Jan–Mar)."""
    m = to_local(ts).month
    return f"Q{(m - 1) // 3 + 1}"


def floor_minutes(ts: pd.Timestamp, minutes: int = 15) -> pd.Timestamp:
    loc = to_local(ts)
    floored = loc.floor(f"{minutes}min")
    return floored.tz_convert(UTC).as_unit("ns")
