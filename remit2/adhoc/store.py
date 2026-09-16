"""Ad-hoc register stores.

GitHubStore — the register lives as JSON files in a SEPARATE private data
repo, read/written through the GitHub Contents API (conditional GETs with
ETag; writes with the file's blob SHA as a precondition so concurrent edits
surface as VersionConflict instead of silently overwriting). Every write is a
commit whose message names the editor: the audit trail is free.

LocalFileStore — same interface on a local folder (dev / tests / no token).

Both are pure Python (no Streamlit). Degraded modes never raise from load():
they return the cached copy (stale=True), then a disk snapshot, then an empty
register flagged "unavailable". mutate() raises StoreUnavailable / VersionConflict.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol

import pandas as pd
import requests

from .model import EquipmentConfig, Register

REGISTER_PATH = "adhoc_register.json"
EQUIPMENT_PATH = "equipment.json"
HISTORY_TEMPLATE = "adhoc_history_{year}.jsonl"
COMMITTER = {"name": "remit2-app", "email": "remit2-app@users.noreply.github.com"}


class StoreUnavailable(RuntimeError):
    pass


class VersionConflict(RuntimeError):
    pass


@dataclass
class Loaded:
    register: Register
    version: str | None          # blob sha (github) / mtime (local); None = file absent
    loaded_at: pd.Timestamp
    status: str                  # "ok" | "stale" | "snapshot" | "unavailable" | "local"
    detail: str = ""


class RegisterStore(Protocol):
    name: str
    def load(self, max_age_s: float = 30) -> Loaded: ...
    def mutate(self, fn: Callable[[Register], Any], actor: str, message: str) -> Loaded: ...
    def load_equipment(self, default: EquipmentConfig) -> EquipmentConfig: ...


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

class GitHubClient:
    """Thin Contents-API wrapper. get() -> (status, json|None, etag); put() -> json."""

    def __init__(self, owner: str, repo: str, token: str, branch: str = "main", session=None, timeout: int = 20):
        self.base = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        self.branch = branch
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "remit2-app"})

    def get(self, path: str, etag: str | None = None) -> tuple[int, dict | None, str | None]:
        headers = {"If-None-Match": etag} if etag else {}
        r = self.s.get(self.base + path, params={"ref": self.branch}, headers=headers, timeout=self.timeout)
        if r.status_code in (200, 304, 404):
            return r.status_code, (r.json() if r.status_code == 200 else None), r.headers.get("ETag")
        raise StoreUnavailable(f"GitHub GET {path}: HTTP {r.status_code}")

    def put(self, path: str, content: bytes, message: str, sha: str | None) -> dict:
        body = {"message": message, "content": base64.b64encode(content).decode(), "branch": self.branch,
                "committer": COMMITTER}
        if sha:
            body["sha"] = sha
        r = self.s.put(self.base + path, json=body, timeout=self.timeout)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code in (409, 422):
            raise VersionConflict(f"GitHub PUT {path}: HTTP {r.status_code}")
        raise StoreUnavailable(f"GitHub PUT {path}: HTTP {r.status_code}")


def _decode(data: dict) -> str:
    return base64.b64decode(data["content"]).decode("utf-8")


class GitHubStore:
    name = "github"
    _lock = threading.Lock()
    _cache: dict[str, dict[str, Any]] = {}     # path -> {etag, sha, text, at}

    def __init__(self, client: GitHubClient, snapshot_dir: str | None = None, retries: int = 3,
                 backoff: tuple[float, ...] = (1, 3, 6)):
        self.c = client
        self.snapshot = Path(snapshot_dir or tempfile.gettempdir()) / "remit2_adhoc_snapshot.json"
        self.retries, self.backoff = retries, backoff

    # -- raw file access with cache -----------------------------------------
    def _fetch(self, path: str, max_age_s: float) -> dict[str, Any]:
        with self._lock:
            entry = self._cache.get(path)
            if entry and (time.time() - entry["at"]) < max_age_s:
                return entry
        last = None
        for i in range(self.retries):
            try:
                status, data, etag = self.c.get(path, entry["etag"] if entry else None)
                break
            except (StoreUnavailable, requests.RequestException) as exc:
                last = exc
                if i < self.retries - 1:
                    time.sleep(self.backoff[min(i, len(self.backoff) - 1)])
        else:
            raise StoreUnavailable(str(last))
        with self._lock:
            if status == 304 and entry:
                entry["at"] = time.time()
                return entry
            if status == 404:
                entry = {"etag": None, "sha": None, "text": None, "at": time.time()}
            else:
                entry = {"etag": etag, "sha": data["sha"], "text": _decode(data), "at": time.time()}
            self._cache[path] = entry
            return entry

    def _put(self, path: str, text: str, message: str, sha: str | None) -> str:
        last = None
        for i in range(self.retries):
            try:
                res = self.c.put(path, text.encode("utf-8"), message, sha)
                new_sha = res["content"]["sha"]
                with self._lock:
                    self._cache[path] = {"etag": None, "sha": new_sha, "text": text, "at": time.time()}
                return new_sha
            except VersionConflict:
                raise
            except (StoreUnavailable, requests.RequestException) as exc:
                last = exc
                if i < self.retries - 1:
                    time.sleep(self.backoff[min(i, len(self.backoff) - 1)])
        raise StoreUnavailable(str(last))

    # -- register -----------------------------------------------------------
    def load(self, max_age_s: float = 30) -> Loaded:
        now = pd.Timestamp.now(tz="UTC")
        try:
            e = self._fetch(REGISTER_PATH, max_age_s)
            reg = Register.from_json(e["text"]) if e["text"] else Register()
            self._save_snapshot(e["text"])
            return Loaded(reg, e["sha"], now, "ok")
        except StoreUnavailable as exc:
            with self._lock:
                e = self._cache.get(REGISTER_PATH)
            if e and e["text"] is not None:
                return Loaded(Register.from_json(e["text"]), e["sha"], now, "stale", str(exc))
            snap = self._load_snapshot()
            if snap is not None:
                return Loaded(Register.from_json(snap), None, now, "snapshot", str(exc))
            return Loaded(Register(), None, now, "unavailable", str(exc))

    def mutate(self, fn: Callable[[Register], Any], actor: str, message: str) -> Loaded:
        for attempt in range(2):
            e = self._fetch(REGISTER_PATH, max_age_s=0)
            reg = Register.from_json(e["text"]) if e["text"] else Register()
            fn(reg)
            text = reg.to_json()
            try:
                sha = self._put(REGISTER_PATH, text, f"{message} by {actor}", e["sha"])
            except VersionConflict:
                if attempt == 0:
                    continue          # reload and re-apply once
                raise
            self._save_snapshot(text)
            self._append_history(reg, actor)
            return Loaded(reg, sha, pd.Timestamp.now(tz="UTC"), "ok")
        raise VersionConflict("register changed twice during save")

    def _append_history(self, reg: Register, actor: str) -> None:
        """Best-effort append-only mirror of the newest history events."""
        try:
            year = pd.Timestamp.now(tz="UTC").year
            path = HISTORY_TEMPLATE.format(year=year)
            e = self._fetch(path, max_age_s=0)
            existing = e["text"] or ""
            seen = {json.loads(l)["seq"] for l in existing.splitlines() if l.strip()}
            lines = []
            for r in reg.records:
                for h in r.history:
                    if h.seq not in seen:
                        lines.append(json.dumps({"seq": h.seq, "ts": h.ts, "actor": h.actor, "id": r.id,
                                                 "action": h.action, "changes": h.changes, "reason": h.reason}))
            if lines:
                text = existing + ("" if existing.endswith("\n") or not existing else "\n") + "\n".join(lines) + "\n"
                self._put(path, text, f"history by {actor}", e["sha"])
        except Exception:
            pass

    def load_equipment(self, default: EquipmentConfig) -> EquipmentConfig:
        try:
            e = self._fetch(EQUIPMENT_PATH, max_age_s=300)
            if e["text"]:
                return EquipmentConfig.from_dict(json.loads(e["text"]))
        except Exception:
            pass
        return default

    def _save_snapshot(self, text: str | None) -> None:
        if not text:
            return
        try:
            tmp = str(self.snapshot) + ".tmp"
            Path(tmp).write_text(text, encoding="utf-8")
            os.replace(tmp, self.snapshot)
        except Exception:
            pass

    def _load_snapshot(self) -> str | None:
        try:
            return self.snapshot.read_text(encoding="utf-8")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Local folder
# ---------------------------------------------------------------------------

class LocalFileStore:
    name = "local"
    _lock = threading.Lock()

    def __init__(self, folder: str | Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / REGISTER_PATH

    def _read(self) -> tuple[Register, str | None]:
        if not self.path.exists():
            return Register(), None
        return Register.from_json(self.path.read_text(encoding="utf-8")), str(self.path.stat().st_mtime_ns)

    def load(self, max_age_s: float = 30) -> Loaded:
        reg, ver = self._read()
        return Loaded(reg, ver, pd.Timestamp.now(tz="UTC"), "local")

    def mutate(self, fn: Callable[[Register], Any], actor: str, message: str) -> Loaded:
        with self._lock:
            reg, _ = self._read()
            fn(reg)
            tmp = str(self.path) + ".tmp"
            Path(tmp).write_text(reg.to_json(), encoding="utf-8")
            os.replace(tmp, self.path)
            hist = self.dir / HISTORY_TEMPLATE.format(year=pd.Timestamp.now(tz="UTC").year)
            with open(hist, "a", encoding="utf-8") as fh:
                for r in reg.records:
                    for h in r.history[-1:]:
                        fh.write(json.dumps({"seq": h.seq, "ts": h.ts, "actor": h.actor, "id": r.id,
                                             "action": h.action, "message": message}) + "\n")
        return Loaded(reg, str(self.path.stat().st_mtime_ns), pd.Timestamp.now(tz="UTC"), "local")

    def load_equipment(self, default: EquipmentConfig) -> EquipmentConfig:
        p = self.dir / EQUIPMENT_PATH
        if p.exists():
            return EquipmentConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
        return default
