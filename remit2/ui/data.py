"""The ONLY module that wraps core in Streamlit caches. Also the fixture and
degraded-mode logic (last-good snapshot, banners)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from ..adhoc.combine import PanelSeries, compute_combined_series
from ..adhoc.model import EquipmentConfig, Register
from ..adhoc.store import GitHubClient, GitHubStore, LocalFileStore, Loaded
from ..core import fetch as core_fetch
from ..core.constants import CATEGORIES
from ..core.normalise import detect_columns, normalise
from ..core.operational import build_operational

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = os.path.join(tempfile.gettempdir(), "remit2_last_good_snapshot.pkl")
FIXTURE = os.environ.get("REMIT2_FIXTURE")          # path to a captured/synthetic API payload (dev, tests)
PANELS = [("Atwick", "Withdrawal"), ("Atwick", "Injection"), ("Aldbrough", "Withdrawal"), ("Aldbrough", "Injection")]


@st.cache_resource(show_spinner=False)
def _session():
    return core_fetch.make_session()


def _reprime():
    _session.clear()
    return _session()


@st.cache_data(ttl=300, show_spinner="Fetching REMIT data…")
def fetch_latest() -> tuple[pd.DataFrame, pd.Timestamp]:
    """Latest revisions from SSE (or the fixture file when REMIT2_FIXTURE is set)."""
    if FIXTURE:
        payload = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
        items = payload["items"] if isinstance(payload, dict) else payload
        return pd.json_normalize(items), pd.Timestamp.now(tz="UTC")
    return core_fetch.fetch_remit(_session(), _reprime, "Latest", snapshot_path=SNAPSHOT_PATH)


@dataclass
class RemitData:
    raw: pd.DataFrame
    df: pd.DataFrame
    df_op: pd.DataFrame
    cmap: dict
    fetched_at: pd.Timestamp | None
    error: str | None          # live fetch problem (None = fresh)
    source: str                # "live" | "fixture" | "session" | "snapshot" | "none"


def load_remit() -> RemitData:
    """Fresh data if possible; otherwise the last good copy (session, then
    disk) behind an error message. Never raises, never st.stop()s."""
    error, source = None, "fixture" if FIXTURE else "live"
    try:
        raw, at = fetch_latest()
        if raw.empty:
            raise RuntimeError("API returned no records.")
        st.session_state["r2_last_good"] = (raw, at)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        if "r2_last_good" in st.session_state:
            raw, at = st.session_state["r2_last_good"]
            source = "session"
        else:
            raw, at = core_fetch.load_snapshot(SNAPSHOT_PATH)
            source = "snapshot" if raw is not None else "none"
    if raw is None or raw.empty:
        empty = pd.DataFrame()
        return RemitData(empty, empty, empty, {}, None, error, "none")
    cmap = detect_columns(raw)
    df = normalise(raw, cmap)
    df_op = build_operational(df, cmap, list(CATEGORIES))
    return RemitData(raw, df, df_op, cmap, at, error, source)


@st.cache_data(show_spinner=False)
def _equipment_from_file(path: str, mtime: float) -> EquipmentConfig:
    return EquipmentConfig.load(path)


def get_equipment() -> EquipmentConfig:
    p = ROOT / "config" / "equipment.default.json"
    return _equipment_from_file(str(p), p.stat().st_mtime)


def _secret(key: str, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default


@st.cache_resource(show_spinner=False)
def get_store():
    """GitHub data repo when a token is configured (unless REMIT2_STORE=local),
    otherwise a local folder (dev / tests — not persistent on the Cloud)."""
    mode = os.environ.get("REMIT2_STORE") or _secret("store")
    gh = _secret("github")
    if mode != "local" and gh and gh.get("token"):
        client = GitHubClient(gh["owner"], gh["repo"], gh["token"], gh.get("branch", "main"))
        return GitHubStore(client)
    return LocalFileStore(os.environ.get("REMIT2_LOCAL_DIR") or ROOT / "data" / "local")


def get_register(max_age_s: float = 30) -> Loaded:
    return get_store().load(max_age_s)


def get_equipment_live() -> EquipmentConfig:
    try:
        return get_store().load_equipment(get_equipment())
    except Exception:
        return get_equipment()


def get_actor() -> str:
    try:
        u = st.user
        email = u.get("email") if hasattr(u, "get") else getattr(u, "email", None)
        if email:
            return str(email)
    except Exception:
        pass
    return str(_secret("dev_actor") or os.environ.get("REMIT2_ACTOR") or "unknown user")


def is_editor(actor: str) -> bool:
    """Editors list in secrets gates add/edit/close/cancel. No list configured
    (local dev / first test runs) = everyone may edit."""
    editors = _secret("editors")
    if not editors:
        return True
    return actor.lower() in {str(e).lower() for e in editors}


@st.cache_data(show_spinner=False, max_entries=32)
def _panels(df_op: pd.DataFrame, register_json: str, equipment_key: str, start: pd.Timestamp,
            end: pd.Timestamp, now: pd.Timestamp) -> dict[tuple[str, str], PanelSeries]:
    reg = Register.from_json(register_json)
    eq = get_equipment()
    return {key: compute_combined_series(df_op, reg, eq, key[0], key[1], start, end, now) for key in PANELS}


def compute_panels(data: RemitData, register: Register, register_version: str, horizon_days: int,
                   now: pd.Timestamp) -> dict[tuple[str, str], PanelSeries]:
    back = max(1, horizon_days // 4)
    start = (now - pd.Timedelta(days=back)).floor("h")
    end = (now + pd.Timedelta(days=horizon_days)).ceil("h")
    # Cache key: data identity via fetched_at, register version, window, now floored to 5 min.
    now_key = now.floor("5min")
    return _panels(data.df_op, register.to_json(), register_version, start, end, now_key)
