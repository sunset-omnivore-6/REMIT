"""SSE API, WAF-retry, nameplate and unit constants.

Lifted verbatim from REMIT 1.0 app.py @ 3c075a5 by tools/lift_from_v1.py.
Pure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).
"""
from __future__ import annotations

import pandas as pd


API_URL = "https://thermaloutages.sse.com/api/v1/outages/gasuof"

LANDING_URL = "https://thermaloutages.sse.com/gas-uof"

SITES = ["Aldbrough", "Atwick"]

CATEGORIES = ["Withdrawal", "Injection", "Storage"]

PAGE_SIZE = 100

FAR_FUTURE = pd.Timestamp("2099-01-01", tz="UTC")

RETRYABLE_STATUSES = frozenset({403, 408, 429, 500, 502, 503, 504})

MAX_FETCH_RETRIES = 4               # total attempts (1 try + 3 retries)

RETRY_BACKOFF_SECONDS = (1, 3, 6)   # waited before retries 2, 3, 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
    ),
    # Mirror the live browser request exactly. In particular: no Origin header
    # (browsers omit it on same-origin GETs — sending it is a Python tell that
    # SSE's WAF flags) and Accept: */* rather than the axios default.
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://thermaloutages.sse.com/gas-uof",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Sec-CH-UA": (
        '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"'
    ),
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Priority": "u=1, i",
}

_IMPERSONATE_TARGET = "chrome131"

TECH_CAPACITY_FALLBACK: dict[tuple[str, str], float] = {
    ("Aldbrough", "Withdrawal"): 287.78,  # GWh/d
    ("Aldbrough", "Injection"): 293.33,   # GWh/d
    ("Aldbrough", "Storage"): 3.3,        # TWh
    ("Atwick", "Withdrawal"): 130.0,      # GWh/d
    ("Atwick", "Injection"): 30.0,        # GWh/d
    ("Atwick", "Storage"): 3.47,          # TWh
}

DEFAULT_UNIT: dict[str, str] = {
    "Withdrawal": "GWh/d",
    "Injection": "GWh/d",
    "Storage": "TWh",
}

_UNIT_FACTOR: dict[tuple[str, str], float] = {
    ("Withdrawal", "gwh/d"): 1.0,
    ("Withdrawal", "gwh/day"): 1.0,
    ("Withdrawal", "mwh/d"): 1e-3,
    ("Withdrawal", "twh/d"): 1e3,
    ("Injection", "gwh/d"): 1.0,
    ("Injection", "gwh/day"): 1.0,
    ("Injection", "mwh/d"): 1e-3,
    ("Injection", "twh/d"): 1e3,
    ("Storage", "twh"): 1.0,
    ("Storage", "gwh"): 1e-3,
    ("Storage", "mwh"): 1e-6,
}

def _unit_factor(category: object, unit: str) -> float:
    """Factor converting `unit` to the canonical unit for `category`.

    1.0 when the unit is blank (assume canonical) or the category is unknown;
    NaN when the unit is present but unrecognised for the category."""
    if category not in DEFAULT_UNIT:
        return 1.0
    if not unit or unit in ("nan", "none", "-"):
        return 1.0
    return _UNIT_FACTOR.get((category, unit), float("nan"))

SITE_DISPLAY = {"Aldbrough": "Aldbrough", "Atwick": "Hornsea"}

def site_label(site: str) -> str:
    return SITE_DISPLAY.get(site, site)
