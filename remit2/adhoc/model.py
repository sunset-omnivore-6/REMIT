"""Ad-hoc adjustment records, register container, equipment config.

Pure dataclasses + JSON (no pydantic: avoids compiled-wheel risk on the
Cloud's Python 3.14). Nothing here reads the wall clock: `now` is passed in.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from ..core.timeutil import iso_utc, parse_iso, quarter_of

SCHEMA_VERSION = 1
Site = Literal["Atwick", "Aldbrough"]
Direction = Literal["Injection", "Withdrawal"]
Kind = Literal["unit_out", "rate_cap", "constraint"]
KINDS_IMPLEMENTED = ("unit_out", "rate_cap")   # "constraint" reserved for the future


# ---------------------------------------------------------------------------
# Equipment config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EquipmentUnit:
    id: str
    label: str
    gwhd_lost: float
    placeholder: bool = False


@dataclass(frozen=True)
class SiteDirectionConfig:
    nameplate_gwhd: float
    units: tuple[EquipmentUnit, ...]
    menu: tuple[str, ...] = ("units", "rate_cap")
    plant_view: bool = False
    unit_noun: str | None = None


@dataclass(frozen=True)
class EquipmentConfig:
    thresholds: dict[str, float]            # {"Q1": 27.5, "Q2": 55.5, ...}
    stale_after_days: int
    display: dict[str, str]                 # site -> display name
    table: dict[tuple[str, str], SiteDirectionConfig]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EquipmentConfig":
        table: dict[tuple[str, str], SiteDirectionConfig] = {}
        display: dict[str, str] = {}
        for site, sd in d["sites"].items():
            display[site] = sd.get("display", site)
            for direction in ("Injection", "Withdrawal"):
                if direction not in sd:
                    continue
                c = sd[direction]
                table[(site, direction)] = SiteDirectionConfig(
                    nameplate_gwhd=float(c["nameplate_gwhd"]),
                    units=tuple(
                        EquipmentUnit(u["id"], u["label"], float(u["gwhd_lost"]), bool(u.get("placeholder", False)))
                        for u in c.get("units", [])
                    ),
                    menu=tuple(c.get("menu", ("units", "rate_cap"))),
                    plant_view=bool(c.get("plant_view", False)),
                    unit_noun=c.get("unit_noun"),
                )
        return cls(
            thresholds={k: float(v) for k, v in d["remit_threshold_gwhd"].items()},
            stale_after_days=int(d.get("stale_after_days", 7)),
            display=display,
            table=table,
        )

    @classmethod
    def load(cls, path: str | Path) -> "EquipmentConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def get(self, site: str, direction: str) -> SiteDirectionConfig:
        return self.table[(site, direction)]

    def unit(self, site: str, direction: str, unit_id: str) -> EquipmentUnit:
        for u in self.get(site, direction).units:
            if u.id == unit_id:
                return u
        raise KeyError(f"unknown unit {unit_id!r} for {site}/{direction}")

    def gwhd_lost(self, site: str, direction: str, unit_ids: list[str] | set[str]) -> float:
        return float(sum(self.unit(site, direction, u).gwhd_lost for u in set(unit_ids)))

    def threshold_for(self, ts: pd.Timestamp) -> float:
        """REMIT publication threshold applying to an event starting at ts
        (quarter of the local start date)."""
        return self.thresholds[quarter_of(ts)]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class HistoryEvent:
    seq: int
    ts: str
    actor: str
    action: Literal["create", "update", "close", "cancel", "reopen"]
    changes: dict[str, list[Any]] = field(default_factory=dict)   # field -> [old, new]
    reason: str | None = None


@dataclass
class AdhocRecord:
    id: str
    draft_id: str
    site: str
    direction: str
    kind: str
    units: list[str]
    resulting_avail_gwhd: float | None
    start: str                       # ISO UTC
    end: str | None                  # None = until further notice
    notes: str
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    expected_return: str | None = None
    covered_by_thread: str | None = None
    constraint: dict[str, Any] | None = None
    closed_reason: Literal["ended", "cancelled"] | None = None
    closed_at: str | None = None
    closed_by: str | None = None
    history: list[HistoryEvent] = field(default_factory=list)

    # -- derived (never stored) ------------------------------------------
    @property
    def start_ts(self) -> pd.Timestamp:
        return parse_iso(self.start)

    @property
    def end_ts(self) -> pd.Timestamp | None:
        return None if self.end is None else parse_iso(self.end)

    def status(self, now: pd.Timestamp) -> str:
        if self.closed_reason == "cancelled":
            return "cancelled"
        if self.end is not None and self.end_ts <= now:
            return "ended"
        if self.start_ts > now:
            return "planned"
        return "active"

    def is_stale(self, now: pd.Timestamp, stale_after_days: int) -> bool:
        if self.status(now) != "active" or self.end is not None:
            return False
        touched = max(parse_iso(self.updated_at), self.start_ts)
        return (now - touched) > timedelta(days=stale_after_days)

    def is_overdue(self, now: pd.Timestamp) -> bool:
        return (
            self.status(now) == "active"
            and self.expected_return is not None
            and parse_iso(self.expected_return) < now
        )

    def counts_in_maths(self) -> bool:
        return self.closed_reason != "cancelled" and self.kind in KINDS_IMPLEMENTED

    def active_at(self, t: pd.Timestamp) -> bool:
        if not self.counts_in_maths():
            return False
        if self.start_ts > t:
            return False
        return self.end is None or t < self.end_ts

    def impact_gwhd(self, equipment: EquipmentConfig, baseline_avail: float | None = None) -> float | None:
        """Nominal reduction this record represents: Σ unit losses, or
        baseline − resulting for a rate cap (None if baseline unknown)."""
        if self.kind == "unit_out":
            return equipment.gwhd_lost(self.site, self.direction, self.units)
        if self.kind == "rate_cap" and baseline_avail is not None and self.resulting_avail_gwhd is not None:
            return max(0.0, float(baseline_avail) - float(self.resulting_avail_gwhd))
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AdhocRecord":
        d = dict(d)
        d["history"] = [HistoryEvent(**h) for h in d.get("history", [])]
        return cls(**d)


@dataclass
class Register:
    schema_version: int = SCHEMA_VERSION
    meta: dict[str, Any] = field(default_factory=lambda: {"next_id": 1, "next_seq": 1, "updated_at": None, "updated_by": None})
    records: list[AdhocRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "meta": self.meta, "records": [r.to_dict() for r in self.records]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Register":
        if d.get("schema_version", 1) != SCHEMA_VERSION:
            raise ValueError(f"unsupported register schema_version {d.get('schema_version')}")
        return cls(schema_version=SCHEMA_VERSION, meta=dict(d.get("meta", {})),
                   records=[AdhocRecord.from_dict(r) for r in d.get("records", [])])

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Register":
        return cls.from_dict(json.loads(text))

    def get(self, rec_id: str) -> AdhocRecord:
        for r in self.records:
            if r.id == rec_id:
                return r
        raise KeyError(rec_id)

    def find_draft(self, draft_id: str) -> AdhocRecord | None:
        return next((r for r in self.records if r.draft_id == draft_id), None)

    def for_site_direction(self, site: str, direction: str) -> list[AdhocRecord]:
        return [r for r in self.records if r.site == site and r.direction == direction]

    def _next_seq(self) -> int:
        seq = int(self.meta.get("next_seq", 1))
        self.meta["next_seq"] = seq + 1
        return seq

    def _stamp(self, actor: str, now: pd.Timestamp) -> None:
        self.meta["updated_at"] = iso_utc(now)
        self.meta["updated_by"] = actor

    # -- mutations (all return the record; all append history) --------------
    def create(self, rec: AdhocRecord, actor: str, now: pd.Timestamp) -> AdhocRecord:
        existing = self.find_draft(rec.draft_id)
        if existing is not None:          # idempotent double-submit
            return existing
        n = int(self.meta.get("next_id", 1))
        rec.id = f"A-{n:04d}"
        self.meta["next_id"] = n + 1
        rec.created_by = rec.updated_by = actor
        rec.created_at = rec.updated_at = iso_utc(now)
        rec.history = [HistoryEvent(self._next_seq(), iso_utc(now), actor, "create")]
        self.records.append(rec)
        self._stamp(actor, now)
        return rec

    def update(self, rec_id: str, changes: dict[str, Any], actor: str, now: pd.Timestamp, reason: str,
               action: str = "update") -> AdhocRecord:
        rec = self.get(rec_id)
        diff: dict[str, list[Any]] = {}
        for k, v in changes.items():
            old = getattr(rec, k)
            if old != v:
                diff[k] = [old, v]
                setattr(rec, k, v)
        if not diff:
            return rec
        rec.updated_by, rec.updated_at = actor, iso_utc(now)
        rec.history.append(HistoryEvent(self._next_seq(), iso_utc(now), actor, action, diff, reason))
        self._stamp(actor, now)
        return rec

    def close(self, rec_id: str, actor: str, now: pd.Timestamp, reason: str, at: pd.Timestamp | None = None) -> AdhocRecord:
        at = now if at is None else at
        return self.update(rec_id, {"end": iso_utc(at), "closed_reason": "ended", "closed_at": iso_utc(now),
                                    "closed_by": actor}, actor, now, reason, action="close")

    def cancel(self, rec_id: str, actor: str, now: pd.Timestamp, reason: str) -> AdhocRecord:
        return self.update(rec_id, {"closed_reason": "cancelled", "closed_at": iso_utc(now), "closed_by": actor},
                           actor, now, reason, action="cancel")

    def reopen(self, rec_id: str, actor: str, now: pd.Timestamp, reason: str) -> AdhocRecord:
        return self.update(rec_id, {"end": None, "closed_reason": None, "closed_at": None, "closed_by": None},
                           actor, now, reason, action="reopen")


def new_record(site: str, direction: str, kind: str, start: pd.Timestamp, notes: str, *,
               units: list[str] | None = None, resulting_avail_gwhd: float | None = None,
               end: pd.Timestamp | None = None, expected_return: pd.Timestamp | None = None,
               covered_by_thread: str | None = None, draft_id: str | None = None) -> AdhocRecord:
    """Unsaved record; id/audit fields are filled by Register.create()."""
    return AdhocRecord(
        id="", draft_id=draft_id or str(uuid.uuid4()), site=site, direction=direction, kind=kind,
        units=list(units or []), resulting_avail_gwhd=resulting_avail_gwhd,
        start=iso_utc(start), end=None if end is None else iso_utc(end), notes=notes,
        created_by="", created_at="", updated_by="", updated_at="",
        expected_return=None if expected_return is None else iso_utc(expected_return),
        covered_by_thread=covered_by_thread,
    )


def validate_record(rec: AdhocRecord, equipment: EquipmentConfig, now: pd.Timestamp) -> list[str]:
    """Plain-language problems (empty list = valid)."""
    errs: list[str] = []
    if (rec.site, rec.direction) not in equipment.table:
        return [f"Unknown site/direction {rec.site}/{rec.direction}."]
    cfg = equipment.get(rec.site, rec.direction)
    if rec.kind not in KINDS_IMPLEMENTED:
        errs.append("Constraints are not available yet.")
    if rec.kind == "unit_out":
        known = {u.id for u in cfg.units}
        if not rec.units:
            errs.append("Select at least one unit.")
        bad = [u for u in rec.units if u not in known]
        if bad:
            errs.append(f"Unknown unit(s): {', '.join(bad)}.")
        if len(set(rec.units)) != len(rec.units):
            errs.append("A unit is listed twice.")
    if rec.kind == "rate_cap":
        v = rec.resulting_avail_gwhd
        if v is None or not (0 <= float(v) < cfg.nameplate_gwhd):
            errs.append(f"Resulting available must be between 0 and {cfg.nameplate_gwhd:g} GWh/d (below nameplate).")
    try:
        start = rec.start_ts
    except Exception:
        return errs + ["Start time is not valid."]
    if rec.end is not None:
        try:
            if rec.end_ts <= start:
                errs.append("End must be after start.")
        except Exception:
            errs.append("End time is not valid.")
    if rec.expected_return is not None:
        try:
            if parse_iso(rec.expected_return) < start:
                errs.append("Expected return cannot be before start.")
        except Exception:
            errs.append("Expected return is not valid.")
    if start < now - timedelta(days=30) or start > now + timedelta(days=365):
        errs.append("Start must be within 30 days back and 365 days ahead.")
    if len((rec.notes or "").strip()) < 5:
        errs.append("Notes are required (at least 5 characters).")
    return errs
