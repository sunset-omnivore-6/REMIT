"""On-disk cache for the last successful REMIT pull.

Persisting to disk (not memory) means restarts don't lose the last-good
snapshot — important because the UI shows stale data when the live fetch
fails, and the user might restart the app between failures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = DATA_DIR / "last_good.json"
LOG_PATH = DATA_DIR / "fetch_log.jsonl"
LOG_MAX_LINES = 5000  # cap; trimmed on append


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_snapshot(rows: list[dict[str, Any]], fetched_at: str) -> None:
    _ensure_dir()
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"fetched_at": fetched_at, "rows": rows}, f)
    tmp.replace(SNAPSHOT_PATH)


def load_snapshot() -> dict[str, Any] | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = data.get("fetched_at")
    rows = data.get("rows")
    if not fetched_at or not isinstance(rows, list):
        return None
    return {
        "fetched_at": fetched_at,
        "rows": rows,
        "age_seconds": _age_seconds(fetched_at),
    }


def append_log(entry: dict[str, Any]) -> None:
    _ensure_dir()
    line = json.dumps(entry, default=str)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    _trim_log()


def read_log(limit: int = 100) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    out: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _trim_log() -> None:
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    if len(lines) <= LOG_MAX_LINES:
        return
    keep = lines[-LOG_MAX_LINES:]
    with LOG_PATH.open("w", encoding="utf-8") as f:
        f.writelines(keep)


def _age_seconds(iso: str) -> int | None:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - dt).total_seconds())
