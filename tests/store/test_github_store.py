"""GitHubStore against a scripted in-memory fake of the Contents API."""
import base64
import json

import pandas as pd
import pytest

from remit2.adhoc.model import Register, new_record
from remit2.adhoc.store import GitHubStore, LocalFileStore, StoreUnavailable, VersionConflict, REGISTER_PATH

NOW = pd.Timestamp("2026-09-16T12:00:00Z")


class FakeGitHubClient:
    def __init__(self):
        self.files: dict[str, tuple[str, str]] = {}      # path -> (text, sha)
        self.fail_next: list[str] = []                    # queue of "get"/"put" failures
        self.conflict_next = 0
        self.n = 0
        self.log: list[str] = []

    def _sha(self, text):
        self.n += 1
        return f"sha{self.n}-{abs(hash(text)) % 10000}"

    def get(self, path, etag=None):
        if self.fail_next and self.fail_next[0] == "get":
            self.fail_next.pop(0); raise StoreUnavailable("boom")
        if path not in self.files:
            return 404, None, None
        text, sha = self.files[path]
        if etag == sha:
            return 304, None, sha
        return 200, {"sha": sha, "content": base64.b64encode(text.encode()).decode()}, sha

    def put(self, path, content, message, sha):
        self.log.append(message)
        if self.fail_next and self.fail_next[0] == "put":
            self.fail_next.pop(0); raise StoreUnavailable("boom")
        if self.conflict_next:
            self.conflict_next -= 1; raise VersionConflict("sha mismatch")
        cur = self.files.get(path)
        if cur and cur[1] != sha:
            raise VersionConflict("sha mismatch")
        text = content.decode()
        new = self._sha(text)
        self.files[path] = (text, new)
        return {"content": {"sha": new}}


@pytest.fixture
def store(tmp_path):
    GitHubStore._cache.clear()
    fake = FakeGitHubClient()
    return GitHubStore(fake, snapshot_dir=tmp_path, backoff=(0, 0, 0)), fake


def _create(reg):
    reg.create(new_record("Atwick", "Injection", "unit_out", NOW - pd.Timedelta(hours=1), "test notes", units=["COMP2"]),
               "t@sse.com", NOW)


def test_empty_repo_then_create_and_reload(store):
    s, fake = store
    assert s.load().status == "ok" and s.load().register.records == []
    loaded = s.mutate(_create, "t@sse.com", "A-0001 create")
    assert loaded.register.records[0].id == "A-0001" and loaded.version
    assert fake.log[0] == "A-0001 create by t@sse.com"
    GitHubStore._cache.clear()
    assert s.load().register.records[0].units == ["COMP2"]
    assert any(p.startswith("adhoc_history_") for p in fake.files)          # JSONL mirror written


def test_etag_304_extends_cache(store):
    s, fake = store
    s.mutate(_create, "t@sse.com", "create")
    s.load(max_age_s=0)                       # forces conditional GET -> 304 path
    assert s.load().status == "ok"


def test_conflict_reapplies_once_then_raises(store):
    s, fake = store
    s.mutate(_create, "t@sse.com", "create")
    fake.conflict_next = 1
    s.mutate(lambda r: r.update("A-0001", {"notes": "edited notes"}, "u@sse.com", NOW, "why"), "u@sse.com", "edit")
    assert s.load(0).register.records[0].notes == "edited notes"
    fake.conflict_next = 2
    with pytest.raises(VersionConflict):
        s.mutate(lambda r: r.update("A-0001", {"notes": "again"}, "u@sse.com", NOW, "why"), "u@sse.com", "edit")


def test_unreachable_falls_back(store, tmp_path):
    s, fake = store
    s.mutate(_create, "t@sse.com", "create")
    fake.fail_next = ["get", "get", "get"]
    l = s.load(max_age_s=0)
    assert l.status == "stale" and l.register.records[0].id == "A-0001"
    GitHubStore._cache.clear()
    fake.fail_next = ["get", "get", "get"]
    l = s.load(max_age_s=0)
    assert l.status == "snapshot" and l.register.records[0].id == "A-0001"
    s2 = GitHubStore(fake, snapshot_dir=tmp_path / "other", backoff=(0, 0, 0))
    GitHubStore._cache.clear()
    fake.fail_next = ["get", "get", "get"]
    assert s2.load(max_age_s=0).status == "unavailable"


def test_put_failure_raises_unavailable(store):
    s, fake = store
    fake.fail_next = ["put", "put", "put"]
    with pytest.raises(StoreUnavailable):
        s.mutate(_create, "t@sse.com", "create")


def test_draft_id_idempotent(store):
    s, _ = store
    rec = new_record("Atwick", "Injection", "unit_out", NOW, "test notes", units=["COMP1"], draft_id="d1")
    s.mutate(lambda r: r.create(rec, "t", NOW), "t", "c")
    s.mutate(lambda r: r.create(rec, "t", NOW), "t", "c")
    assert len(s.load(0).register.records) == 1


def test_local_store_roundtrip(tmp_path):
    s = LocalFileStore(tmp_path)
    assert s.load().register.records == []
    s.mutate(_create, "t@sse.com", "create")
    assert s.load().register.records[0].id == "A-0001"
    assert (tmp_path / REGISTER_PATH).exists()
