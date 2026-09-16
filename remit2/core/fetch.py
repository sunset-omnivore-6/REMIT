"""SSE API fetch: Chrome-TLS impersonation, WAF-403 retry, pagination, disk snapshot.

Lifted verbatim from REMIT 1.0 app.py @ 3c075a5 by tools/lift_from_v1.py.
Pure pandas — no Streamlit imports (enforced by tests/unit/test_no_streamlit_in_core.py).
"""
from __future__ import annotations

import os
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
    _HAS_IMPERSONATE = False


def save_snapshot(raw_df: pd.DataFrame, fetched_at: pd.Timestamp, path: str) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump({"raw": raw_df, "at": fetched_at}, fh)
        os.replace(tmp, path)
    except Exception:
        pass

def load_snapshot(path: str) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:
    try:
        with open(path, "rb") as fh:
            snap = pickle.load(fh)
        raw_df, at = snap.get("raw"), snap.get("at")
        if isinstance(raw_df, pd.DataFrame) and not raw_df.empty:
            return raw_df, at
    except Exception:
        pass
    return None, None

def make_session():
    """A primed session for the SSE API. Uses curl_cffi to impersonate
    Chrome's TLS handshake when available (the only defence against WAFs
    that fingerprint at JA3/JA4 rather than headers), and falls back to
    `requests` otherwise. The landing-page GET seeds any cookies the edge
    sets so subsequent API calls carry them."""
    if _HAS_IMPERSONATE:
        s = _impersonate_requests.Session(impersonate=_IMPERSONATE_TARGET)
    else:
        s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(LANDING_URL, timeout=30)
    except Exception:
        # Priming is best-effort; the API call below will surface a real error.
        pass
    return s

def _api_params(page: int, revisions: str) -> dict:
    return {
        "pageNumber": page,
        "pageSize": PAGE_SIZE,
        "sortDirection": "DESC",
        "sortBy": "PublicationDateTime",
        "revisionsReturned": revisions,
        "outageDateMatch": "CONTAINED",
    }

def _accumulate_payload(payload, rows: list[dict]) -> tuple[int, int | None]:
    """Common pagination handling: append items to rows, return (n_items,
    totalCount-or-None)."""
    if isinstance(payload, dict):
        items = (
            payload.get("items")
            or payload.get("data")
            or payload.get("results")
            or []
        )
        total = payload.get("totalCount") or payload.get("total")
    else:
        items = payload
        total = None
    if items:
        rows.extend(items)
    return len(items), total

def get_page_with_retry(session, params: dict, reprime: Callable[[], object]):
    """GET one API page, retrying through SSE's intermittent WAF rejections.

    Returns (payload, session) — session is returned because a retry may
    re-prime it (fresh WAF cookies). Raises RuntimeError with a rich
    diagnostic only after every attempt is exhausted.
    """
    last_resp = None
    for attempt in range(MAX_FETCH_RETRIES):
        try:
            resp = session.get(API_URL, params=params, timeout=30)
        except Exception as exc:
            # Transport-level failure (DNS / connect / timeout) — common on the
            # very first request right after a cold start / wake. Retry.
            if attempt == MAX_FETCH_RETRIES - 1:
                raise RuntimeError(
                    f"SSE request failed: {type(exc).__name__}: {exc}"
                ) from exc
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
            session = reprime()  # drop stale WAF cookies, re-prime via the landing page
            continue

        last_resp = resp
        if resp.status_code == 200:
            return resp.json(), session

        # Transient WAF status with attempts remaining: back off, re-prime, retry.
        if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_FETCH_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
            session = reprime()  # drop stale WAF cookies, re-prime via the landing page
            continue

        break  # non-retryable status, or retries exhausted

    resp = last_resp
    transport = (
        f"curl_cffi/{_IMPERSONATE_TARGET}" if _HAS_IMPERSONATE
        else "requests (no TLS impersonation)"
    )
    deny = resp.headers.get("x-deny-reason", "(none)")
    server = resp.headers.get("server", "(unknown)")
    try:
        body_snippet = " ".join(resp.text[:300].split())
    except Exception:
        body_snippet = "(body unreadable)"
    raise RuntimeError(
        f"SSE returned {resp.status_code} after {MAX_FETCH_RETRIES} attempts. "
        f"Transport: {transport}. x-deny-reason: {deny}. Server: {server}. "
        f"Body[:300]: {body_snippet}"
    )

def fetch_pages(session, reprime: Callable[[], object], revisions: str) -> pd.DataFrame:
    """Fetch every page via curl_cffi (Chrome TLS impersonation) or plain
    requests, retrying through SSE's intermittent WAF 403s."""
    rows: list[dict] = []
    page = 1
    while True:
        params = _api_params(page, revisions)
        payload, session = get_page_with_retry(session, params, reprime)
        n_items, total = _accumulate_payload(payload, rows)
        if not n_items:
            break
        if total is not None and len(rows) >= total:
            break
        if n_items < PAGE_SIZE:
            break
        page += 1
        if page > 200:
            break

    return pd.json_normalize(rows)

def fetch_remit(
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
