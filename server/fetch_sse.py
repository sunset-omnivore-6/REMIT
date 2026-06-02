"""
Fetch REMIT / UoF data from SSE's thermal outages API.

Single source of truth for the SSE scrape. Replicates the exact browser
request the user captured from devtools, and returns rows + a structured
diagnostics blob so the UI can show what happened on every attempt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    HAS_CURL_CFFI = False

import requests as plain_requests


API_URL = "https://thermaloutages.sse.com/api/v1/outages/gasuof"
LANDING_URL = "https://thermaloutages.sse.com/gas-uof"

# Headers copied verbatim from the user's captured browser request.
# Order and casing match Chrome's actual wire output as closely as
# Python's HTTP libs allow.
BROWSER_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "dnt": "1",
    "priority": "u=1, i",
    "referer": LANDING_URL,
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

# curl_cffi target. chrome131 is the latest stable preset shipped with
# curl_cffi 0.7+. If SSE starts blocking it, try chrome124 or chrome120.
IMPERSONATE_TARGET = "chrome131"

# Default page size matches what the captured request used (50). The API
# supports larger pages (the old code used 100); kept at 50 to mimic the
# browser exactly.
DEFAULT_PAGE_SIZE = 50
MAX_PAGES = 200  # hard ceiling so a runaway API can't loop forever


@dataclass
class FetchAttempt:
    """One transport attempt within a single fetch_remit() call."""

    transport: str  # "curl_cffi:chrome131" or "requests"
    status_code: int | None = None
    duration_ms: int | None = None
    response_size: int | None = None
    error: str | None = None
    # WAF / proxy headers worth surfacing
    waf_headers: dict[str, str] = field(default_factory=dict)
    body_snippet: str | None = None


@dataclass
class FetchResult:
    """Returned from fetch_remit() — wraps rows + everything diagnostic."""

    rows: list[dict[str, Any]]
    success: bool
    fetched_at: str  # ISO8601 UTC
    pages_fetched: int
    total_records_reported: int | None
    attempts: list[FetchAttempt]
    error: str | None = None

    def to_log_entry(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "success": self.success,
            "pages_fetched": self.pages_fetched,
            "total_records_reported": self.total_records_reported,
            "row_count": len(self.rows),
            "error": self.error,
            "attempts": [asdict(a) for a in self.attempts],
        }


# Headers we capture from the response for diagnostics. These are the
# ones a CDN / WAF typically uses to signal a block.
_WAF_HEADER_NAMES = (
    "x-deny-reason",
    "x-azure-ref",
    "x-cache",
    "cf-ray",
    "cf-mitigated",
    "server",
    "x-ms-middleware-request-id",
    "x-amzn-waf-action",
)


def _build_params(page_number: int, page_size: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """Match the captured request payload exactly."""
    return {
        "pageNumber": page_number,
        "pageSize": page_size,
        "sortDirection": "DESC",
        "sortBy": "PublicationDateTime",
        "revisionsReturned": "Latest",
        "outageDateMatch": "CONTAINED",
    }


def _extract_waf_headers(headers) -> dict[str, str]:
    out = {}
    for name in _WAF_HEADER_NAMES:
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if value:
            out[name] = str(value)
    return out


def _prime_session(session) -> None:
    """Hit the landing page first so the session picks up any WAF cookies.

    Silent on failure — if priming itself is blocked, the API call below
    will produce the real diagnostic.
    """
    try:
        session.get(LANDING_URL, timeout=20, headers=BROWSER_HEADERS)
    except Exception:
        pass


def _fetch_page_curl_cffi(session, params: dict[str, Any]) -> tuple[Any, FetchAttempt]:
    attempt = FetchAttempt(transport=f"curl_cffi:{IMPERSONATE_TARGET}")
    started = time.monotonic()
    try:
        resp = session.get(
            API_URL,
            params=params,
            headers=BROWSER_HEADERS,
            timeout=30,
            impersonate=IMPERSONATE_TARGET,
        )
    except Exception as exc:
        attempt.duration_ms = int((time.monotonic() - started) * 1000)
        attempt.error = f"{type(exc).__name__}: {exc}"
        return None, attempt

    attempt.duration_ms = int((time.monotonic() - started) * 1000)
    attempt.status_code = resp.status_code
    attempt.response_size = len(resp.content)
    attempt.waf_headers = _extract_waf_headers(resp.headers)

    if resp.status_code != 200:
        attempt.body_snippet = resp.text[:500] if resp.text else None
        return None, attempt

    try:
        payload = resp.json()
    except Exception as exc:
        attempt.error = f"JSON decode failed: {exc}"
        attempt.body_snippet = resp.text[:500] if resp.text else None
        return None, attempt

    return payload, attempt


def _fetch_page_plain_requests(session, params: dict[str, Any]) -> tuple[Any, FetchAttempt]:
    attempt = FetchAttempt(transport="requests")
    started = time.monotonic()
    try:
        resp = session.get(
            API_URL,
            params=params,
            headers=BROWSER_HEADERS,
            timeout=30,
        )
    except Exception as exc:
        attempt.duration_ms = int((time.monotonic() - started) * 1000)
        attempt.error = f"{type(exc).__name__}: {exc}"
        return None, attempt

    attempt.duration_ms = int((time.monotonic() - started) * 1000)
    attempt.status_code = resp.status_code
    attempt.response_size = len(resp.content)
    attempt.waf_headers = _extract_waf_headers(resp.headers)

    if resp.status_code != 200:
        attempt.body_snippet = resp.text[:500] if resp.text else None
        return None, attempt

    try:
        payload = resp.json()
    except Exception as exc:
        attempt.error = f"JSON decode failed: {exc}"
        attempt.body_snippet = resp.text[:500] if resp.text else None
        return None, attempt

    return payload, attempt


def _extract_rows_and_total(payload: Any) -> tuple[list[dict], int | None]:
    """The API wraps rows in one of several keys depending on version.

    Defensively unwrap so a schema rename doesn't silently zero us out.
    """
    if isinstance(payload, list):
        return payload, None

    if not isinstance(payload, dict):
        return [], None

    total = None
    for key in ("totalCount", "total", "totalRecords"):
        if key in payload and isinstance(payload[key], int):
            total = payload[key]
            break

    for key in ("items", "results", "data", "outages", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value, total

    return [], total


def fetch_remit(page_size: int = DEFAULT_PAGE_SIZE) -> FetchResult:
    """Pull every page of REMIT data, paginating until exhausted.

    Returns a FetchResult whether or not it succeeded — caller decides
    what to do with a failed result (typically: keep showing cached data
    and surface the diagnostics in a banner).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    attempts: list[FetchAttempt] = []
    all_rows: list[dict] = []
    total_reported: int | None = None
    pages_done = 0

    # Pick the strongest transport available. curl_cffi spoofs Chrome's
    # TLS fingerprint, which is what SSE's WAF is most likely keying on.
    if HAS_CURL_CFFI:
        session = curl_requests.Session()
        fetch_page = _fetch_page_curl_cffi
    else:
        session = plain_requests.Session()
        fetch_page = _fetch_page_plain_requests

    _prime_session(session)

    try:
        for page in range(1, MAX_PAGES + 1):
            params = _build_params(page_number=page, page_size=page_size)
            payload, attempt = fetch_page(session, params)
            attempts.append(attempt)

            if payload is None:
                return FetchResult(
                    rows=all_rows,
                    success=False,
                    fetched_at=fetched_at,
                    pages_fetched=pages_done,
                    total_records_reported=total_reported,
                    attempts=attempts,
                    error=attempt.error or f"HTTP {attempt.status_code} on page {page}",
                )

            rows, total = _extract_rows_and_total(payload)
            if total is not None:
                total_reported = total

            all_rows.extend(rows)
            pages_done = page

            # Stop when this page is short — means we've drained the dataset.
            if len(rows) < page_size:
                break
            # Or when we've collected as many as the API said exist.
            if total_reported is not None and len(all_rows) >= total_reported:
                break
        else:
            # MAX_PAGES exhausted without termination — flag it but keep what we have.
            return FetchResult(
                rows=all_rows,
                success=True,
                fetched_at=fetched_at,
                pages_fetched=pages_done,
                total_records_reported=total_reported,
                attempts=attempts,
                error=f"Reached MAX_PAGES={MAX_PAGES} without exhausting dataset",
            )
    finally:
        try:
            session.close()
        except Exception:
            pass

    return FetchResult(
        rows=all_rows,
        success=True,
        fetched_at=fetched_at,
        pages_fetched=pages_done,
        total_records_reported=total_reported,
        attempts=attempts,
    )


if __name__ == "__main__":
    # Smoke test — run this module directly to confirm the scrape works.
    import json
    import sys

    result = fetch_remit()
    print(f"success={result.success}")
    print(f"pages_fetched={result.pages_fetched}")
    print(f"rows={len(result.rows)}  total_reported={result.total_records_reported}")
    print(f"attempts={len(result.attempts)}")
    for i, a in enumerate(result.attempts[-3:], 1):
        print(f"  [{i}] {a.transport} status={a.status_code} dur={a.duration_ms}ms err={a.error}")
        if a.waf_headers:
            print(f"      waf={a.waf_headers}")
    if result.rows:
        print("\nfirst row keys:", list(result.rows[0].keys())[:15])
    sys.exit(0 if result.success else 1)
