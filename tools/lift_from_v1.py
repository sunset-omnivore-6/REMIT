"""Lift the pure data layer of REMIT 1.0 (app.py) into remit2/core.

Copies function/constant source verbatim via `ast`, then applies ONLY the
documented shims:
  1. `_remit_session` -> `make_session()` (no @st.cache_resource)
  2. `_get_page_with_retry` -> `get_page_with_retry(session, params, reprime)`
  3. `fetch_remit` undecorated, session/reprime injected, snapshot path param
plus: `now` injected into compute_capacity_changes / compute_recent_changes,
UI colours dropped from compute_recent_changes, `_capacity_at` -> `capacity_at`.

Usage: python tools/lift_from_v1.py /path/to/REMIT/app.py
"""
from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/REMIT/app.py")
OUT = Path(__file__).resolve().parents[1] / "remit2" / "core"
src = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(src)
lines = src.splitlines(keepends=True)


def seg(name: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            start = node.lineno - 1
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            return "".join(lines[start:node.end_lineno])
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return "".join(lines[node.lineno - 1:node.end_lineno])
    raise KeyError(name)


def sub1(text: str, pattern: str, repl: str, n: int = 1, flags=0) -> str:
    new, count = re.subn(pattern, repl, text, flags=flags)
    assert count == n, f"{pattern!r}: expected {n} substitutions, got {count}"
    return new


try:
    commit = subprocess.check_output(["git", "-C", str(SRC.parent), "rev-parse", "--short", "HEAD"], text=True).strip()
except Exception:
    commit = "unknown"
BANNER = f'"""{{doc}}\n\nLifted verbatim from REMIT 1.0 app.py @ {commit} by tools/lift_from_v1.py.\nPure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).\n"""\nfrom __future__ import annotations\n\n'


def write(name: str, doc: str, imports: str, parts: list[str]) -> None:
    body = BANNER.replace("{doc}", doc) + imports.rstrip() + "\n\n\n" + "\n\n".join(p.rstrip() for p in parts) + "\n"
    (OUT / name).write_text(body, encoding="utf-8")
    print(f"wrote core/{name}: {len(parts)} objects")


# ---- constants.py ----------------------------------------------------------
write(
    "constants.py",
    "SSE API, WAF-retry, nameplate and unit constants.",
    "import pandas as pd",
    [seg(n) for n in [
        "API_URL", "LANDING_URL", "SITES", "CATEGORIES", "PAGE_SIZE", "FAR_FUTURE",
        "RETRYABLE_STATUSES", "MAX_FETCH_RETRIES", "RETRY_BACKOFF_SECONDS", "HEADERS",
        "_IMPERSONATE_TARGET",
        "TECH_CAPACITY_FALLBACK", "DEFAULT_UNIT", "_UNIT_FACTOR", "_unit_factor",
        "SITE_DISPLAY", "site_label",
    ]],
)

# ---- fetch.py ---------------------------------------------------------------
save = seg("_save_snapshot")
save = sub1(save, r"def _save_snapshot\(raw_df: pd\.DataFrame, fetched_at: pd\.Timestamp\) -> None:",
            "def save_snapshot(raw_df: pd.DataFrame, fetched_at: pd.Timestamp, path: str) -> None:")
save = sub1(save, r"SNAPSHOT_PATH", "path", n=2)
load = seg("_load_snapshot")
load = sub1(load, r"def _load_snapshot\(\) -> tuple\[pd\.DataFrame \| None, pd\.Timestamp \| None\]:",
            "def load_snapshot(path: str) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:")
load = sub1(load, r"SNAPSHOT_PATH", "path")

session = seg("_remit_session")
session = sub1(session, r"@st\.cache_resource\(show_spinner=False\)\n", "")
session = sub1(session, r"def _remit_session\(\):", "def make_session():")

retry = seg("_get_page_with_retry")
retry = sub1(retry, r"def _get_page_with_retry\(session, params: dict\):",
             "def get_page_with_retry(session, params: dict, reprime: Callable[[], object]):")
retry = sub1(retry, r"_remit_session\.clear\(\)[^\n]*\n(\s*)session = _remit_session\(\)[^\n]*",
             r"session = reprime()  # drop stale WAF cookies, re-prime via the landing page", n=2)

pages = seg("_fetch_remit_via_session")
pages = sub1(pages, r"def _fetch_remit_via_session\(revisions: str\) -> pd\.DataFrame:",
             "def fetch_pages(session, reprime: Callable[[], object], revisions: str) -> pd.DataFrame:")
pages = sub1(pages, r"\n    session = _remit_session\(\)\n", "\n")
pages = sub1(pages, r"_get_page_with_retry\(session, params\)", "get_page_with_retry(session, params, reprime)")

fetch_remit = '''def fetch_remit(
    session,
    reprime: Callable[[], object],
    revisions: str = "Latest",
    snapshot_path: str | None = None,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Fetch + paginate the SSE REMIT API. Undecorated: the app layer supplies
    the (cached) session, a reprime callable and its own TTL cache.

    Returns (df, fetched_at); fetched_at is the wall-clock instant of the
    fetch — an I/O fact recorded here so freshness reporting stays honest when
    a rerun is served from cache. A successful Latest fetch is persisted to
    snapshot_path (if given) for cold-start recovery."""
    df = fetch_pages(session, reprime, revisions)
    fetched_at = pd.Timestamp.now(tz="UTC")
    if snapshot_path and revisions == "Latest" and not df.empty:
        save_snapshot(df, fetched_at, snapshot_path)
    return df, fetched_at
'''

write(
    "fetch.py",
    "SSE API fetch: Chrome-TLS impersonation, WAF-403 retry, pagination, disk snapshot.",
    '''import os
import pickle
import time
from typing import Callable

import pandas as pd
import requests

from .constants import (
    API_URL, HEADERS, LANDING_URL, MAX_FETCH_RETRIES, PAGE_SIZE,
    RETRY_BACKOFF_SECONDS, RETRYABLE_STATUSES, _IMPERSONATE_TARGET,
)

# curl_cffi speaks Chrome's actual TLS handshake (JA3/JA4) so we look like
# Chromium at the socket level — the durable fix for SSE's WAF. Falls back to
# plain `requests` if curl_cffi is not installed.
try:
    from curl_cffi import requests as _impersonate_requests
    _HAS_IMPERSONATE = True
except ImportError:  # pragma: no cover
    _impersonate_requests = None
    _HAS_IMPERSONATE = False''',
    [save, load, session, seg("_api_params"), seg("_accumulate_payload"), retry, pages, fetch_remit],
)

# ---- normalise.py -----------------------------------------------------------
# Deliberate deviation from verbatim (documented in docs/decisions.md): the API
# mixes fractional and whole-second ISO timestamps; without format="ISO8601"
# pandas infers the format from the first row and silently coerces the rest
# to NaT (notices vanish). Fixed here and ported back to 1.0.
norm = seg("normalise")
norm = sub1(norm, r'out\[col\], errors="coerce", utc=True\n',
            'out[col], errors="coerce", utc=True, format="ISO8601"\n')
write(
    "normalise.py",
    "Column detection (tolerant of API key variants) and normalisation to __field__ columns.",
    "import re\n\nimport pandas as pd\n\nfrom .constants import _unit_factor",
    [seg(n) for n in ["_norm", "detect_columns", "_category_from_event", "_site_from_asset"]] + [norm],
)

# ---- operational.py ---------------------------------------------------------
write(
    "operational.py",
    "Operational dataset: status handling (Dismissed / Inactive clamp), latest-revision dedup, active/upcoming slices.",
    "import pandas as pd\n\nfrom .constants import SITES, TECH_CAPACITY_FALLBACK",
    [seg(n) for n in ["active_now", "upcoming", "status_flags", "build_operational",
                      "site_category_headline", "tech_capacity_lookup"]],
)

# ---- capacity.py ------------------------------------------------------------
cap_at = seg("_capacity_at")
cap_at = sub1(cap_at, r"def _capacity_at\(", "def capacity_at(")

changes = seg("compute_capacity_changes")
changes = sub1(changes, r"    threshold: float = 0\.001,\n\) -> list\[dict\]:",
               "    threshold: float = 0.001,\n    now: pd.Timestamp | None = None,\n) -> list[dict]:")
changes = sub1(changes, r'\n    now = pd\.Timestamp\.now\(tz="UTC"\)\n',
               '\n    if now is None:\n        raise ValueError("now must be supplied (core never reads the wall clock)")\n')
changes = sub1(changes, r"_capacity_at\(", "capacity_at(", n=2)

series = seg("compute_capacity_series")
series = sub1(series, r"_capacity_at\(", "capacity_at(", n=2)

recent = seg("compute_recent_changes")
recent = sub1(recent, r"    df: pd\.DataFrame, cmap: dict\[str, str \| None\], lookback_hours: int = 24\n\) -> list\[dict\]:",
              "    df: pd.DataFrame,\n    cmap: dict[str, str | None],\n    lookback_hours: int = 24,\n    now: pd.Timestamp | None = None,\n) -> list[dict]:")
recent = sub1(recent, r'\n    now = pd\.Timestamp\.now\(tz="UTC"\)\n',
              '\n    if now is None:\n        raise ValueError("now must be supplied (core never reads the wall clock)")\n')
recent = sub1(recent, r'kind, kind_color = ("[A-Za-z]+"), COLOR\[[^\]]+\]', r"kind = \1", n=5)
recent = sub1(recent, r'\n\s*"kind_color": kind_color,', "")

write(
    "capacity.py",
    "Capacity maths: available capacity at an instant, step changes, exact step series, recent-change classification, formatting helpers.",
    "import pandas as pd\n\nfrom .constants import DEFAULT_UNIT, SITES",
    [seg("FRESH_MINUTES"), cap_at, changes, series, recent, seg("short_thread"), seg("fmt_dt"), seg("fmt_qty")],
)
print("source commit:", commit)
