"""FastAPI app — serves the dashboard and the data API."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import cache, history
from server.fetch_sse import fetch_remit
from server.normalise import (
    collect_raw_field_names,
    filter_to_sse_storage,
    normalise_rows,
)

logger = logging.getLogger("remit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

# Background-refresh cadence. The UI also lets you trigger a refresh by hand.
REFRESH_INTERVAL_SECONDS = 300  # 5 min
STALE_AFTER_SECONDS = 15 * 60   # banner switches yellow after this
FAILED_AFTER_SECONDS = 60 * 60  # banner switches red after this

app = FastAPI(title="REMIT — Local")

# In-memory mirror of the last fetch outcome (purely for /api/data speed —
# the snapshot file is the source of truth).
_last_result: dict[str, Any] = {
    "last_attempt_at": None,
    "last_attempt_success": None,
    "last_attempt_error": None,
    "last_attempt_attempts": [],
}

_refresh_lock = asyncio.Lock()


@app.on_event("startup")
async def _on_startup() -> None:
    asyncio.create_task(_background_refresher())


async def _background_refresher() -> None:
    """Poll SSE on a fixed cadence in the background.

    Even if the user keeps a browser tab open, we don't rely on the
    frontend to drive refresh — that way the snapshot stays fresh for
    the next page load too.
    """
    while True:
        try:
            await refresh_once()
        except Exception:
            logger.exception("background refresh crashed; will retry next tick")
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


async def refresh_once() -> dict[str, Any]:
    """Run one fetch attempt. Persists snapshot on success, logs always."""
    async with _refresh_lock:
        # fetch_remit is sync; run in default threadpool so we don't block the loop.
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, fetch_remit)

        cache.append_log(result.to_log_entry())

        _last_result["last_attempt_at"] = result.fetched_at
        _last_result["last_attempt_success"] = result.success
        _last_result["last_attempt_error"] = result.error
        _last_result["last_attempt_attempts"] = [
            {
                "transport": a.transport,
                "status_code": a.status_code,
                "duration_ms": a.duration_ms,
                "response_size": a.response_size,
                "error": a.error,
                "waf_headers": a.waf_headers,
                "body_snippet": a.body_snippet,
            }
            for a in result.attempts
        ]

        if result.success and result.rows:
            cache.save_snapshot(result.rows, result.fetched_at)
            # Sample the current dial values into the rolling history buffer.
            # Powers the sparklines under each dial.
            try:
                history.append_sample(normalise_rows(result.rows), result.fetched_at)
            except Exception:
                logger.exception("history sample append failed")
            logger.info("refresh ok — %d rows (%d pages)", len(result.rows), result.pages_fetched)
        else:
            logger.warning(
                "refresh failed — %s (attempts=%d)",
                result.error,
                len(result.attempts),
            )

        return {
            "success": result.success,
            "rows": len(result.rows),
            "error": result.error,
        }


def _compute_status(snapshot_age_seconds: int | None, last_success: bool | None) -> str:
    """Three-state health for the banner."""
    if snapshot_age_seconds is None:
        return "no-data"
    if last_success is False and snapshot_age_seconds > FAILED_AFTER_SECONDS:
        return "failed"
    if snapshot_age_seconds > STALE_AFTER_SECONDS or last_success is False:
        return "stale"
    return "fresh"


@app.get("/api/data")
async def api_data(
    filter_sites: bool = True,
    include_raw: bool = False,
) -> JSONResponse:
    snapshot = cache.load_snapshot()
    if snapshot is None:
        rows: list[dict[str, Any]] = []
        snapshot_fetched_at = None
        snapshot_age = None
    else:
        rows = snapshot["rows"]
        snapshot_fetched_at = snapshot["fetched_at"]
        snapshot_age = snapshot["age_seconds"]

    normalised = normalise_rows(rows)
    if filter_sites:
        normalised = filter_to_sse_storage(normalised)

    status = _compute_status(snapshot_age, _last_result["last_attempt_success"])

    payload = {
        "status": status,  # fresh | stale | failed | no-data
        "snapshot_fetched_at": snapshot_fetched_at,
        "snapshot_age_seconds": snapshot_age,
        "row_count": len(normalised),
        "rows": normalised,
        "last_attempt": _last_result,
        "now": datetime.now(timezone.utc).isoformat(),
    }
    if include_raw:
        payload["raw_rows"] = rows
    return JSONResponse(payload)


@app.post("/api/refresh")
async def api_refresh() -> JSONResponse:
    result = await refresh_once()
    return JSONResponse(result)


@app.get("/api/log")
async def api_log(limit: int = 50) -> JSONResponse:
    return JSONResponse({"entries": cache.read_log(limit=limit)})


@app.get("/api/history")
async def api_history(hours: int = 24) -> JSONResponse:
    """Rolling dial-value history for the sparklines under each dial."""
    return JSONResponse({"hours": hours, "samples": history.read_samples(hours=hours)})


@app.get("/api/debug/raw_schema")
async def api_debug_raw_schema() -> JSONResponse:
    """Show what field names the SSE API is actually returning.

    Use this when normalisation is producing empty columns — compare
    these names against FIELD_ALIASES in server/normalise.py.
    """
    snapshot = cache.load_snapshot()
    if snapshot is None:
        return JSONResponse({"error": "no snapshot yet"}, status_code=404)
    return JSONResponse(collect_raw_field_names(snapshot["rows"]))


@app.get("/api/debug/site_category")
async def api_debug_site_category(site: str = "Atwick", category: str = "Withdrawal") -> JSONResponse:
    """Dump every normalised row for one (site, category) so the chart's
    inputs can be inspected. Filters: site match on asset/threadId,
    type_of_event starts with the category word.
    """
    snapshot = cache.load_snapshot()
    if snapshot is None:
        return JSONResponse({"error": "no snapshot yet"}, status_code=404)
    normalised = normalise_rows(snapshot["rows"])
    cat_lower = category.lower()
    site_lower = site.lower()
    matches = []
    for r in normalised:
        asset = (r.get("asset") or "").lower()
        tid = (r.get("thread_id") or "").lower()
        toe = (r.get("type_of_event") or "").lower()
        # Site match: by asset name OR threadId prefix
        site_match = (
            asset == site_lower
            or tid.startswith(site_lower[:3] + "_")
        )
        if not site_match:
            continue
        if not toe.startswith(cat_lower):
            continue
        matches.append({
            "thread_id": r.get("thread_id"),
            "asset": r.get("asset"),
            "event_status": r.get("event_status"),
            "type_of_event": r.get("type_of_event"),
            "type_of_unavailability": r.get("type_of_unavailability"),
            "event_start": r.get("event_start"),
            "event_stop": r.get("event_stop"),
            "available_capacity": r.get("available_capacity"),
            "unavailable_capacity": r.get("unavailable_capacity"),
            "technical_capacity": r.get("technical_capacity"),
            "revision_number": r.get("revision_number"),
            "publication_dt": r.get("publication_dt"),
        })
    return JSONResponse({
        "site": site,
        "category": category,
        "count": len(matches),
        "rows": matches,
    })


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/")
async def index() -> FileResponse:
    # Disable HTML caching so the cache-busting build-tag inside index.html
    # is always re-read after a deploy / git pull.
    return FileResponse(WEB_DIR / "index.html", headers=_NO_CACHE_HEADERS)


class NoCacheStaticFiles(StaticFiles):
    """Static files with no-store cache headers. Combined with the build-tag
    query string on script src URLs, this guarantees that a browser refresh
    after `git pull` always loads the fresh JS/CSS — never a stale cached copy.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        for k, v in _NO_CACHE_HEADERS.items():
            resp.headers[k] = v
        return resp


app.mount("/web", NoCacheStaticFiles(directory=WEB_DIR), name="web")
