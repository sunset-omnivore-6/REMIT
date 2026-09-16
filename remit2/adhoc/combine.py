"""Combined availability: published REMITs + ad-hoc adjustments.

Rule (per site s, direction d, nameplate T, instant t) — DECIDED with the
product owner, do not reinterpret:

    R(t)     = capacity_at(df_op, s, d, t, T)            # 1.0 REMIT semantics, unchanged
    A(t)     = non-cancelled ad-hocs at (s,d) active at t
    cov(a,t) = a.covered_by_thread set AND that thread active in df_op at t
    Ulost(t) = ∪ units of uncovered unit_out records      # SET UNION: a unit is lost once
    U(t)     = Σ gwhd_lost over Ulost(t)
    Cap(t)   = min resulting_avail over uncovered rate_cap records (∞ if none)
    Avail(t) = clamp(min(R − U, Cap), 0, T)

Pure pandas/dataclasses. `now` is always injected.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from ..core.capacity import capacity_at, short_thread
from .model import AdhocRecord, EquipmentConfig, Register

LANE_PLANNED = "Planned REMIT"
LANE_UNPLANNED = "Unplanned REMIT"
LANE_ADHOC = "Ad-hoc"
LANES = (LANE_PLANNED, LANE_UNPLANNED, LANE_ADHOC)
EPS = 1e-6


@dataclass
class Driver:
    source: str                     # "remit" | "adhoc"
    id: str                         # thread id or A-xxxx
    label: str
    reduction: float | None         # GWh/d this driver takes away (nominal)
    binding: bool                   # does it set the level at this instant?
    planned: bool | None = None     # remit only
    units: list[str] = field(default_factory=list)
    note: str = ""                  # "covered by …", "overlapping, not binding"

    @property
    def lane(self) -> str:
        if self.source == "adhoc":
            return LANE_ADHOC
        return LANE_PLANNED if self.planned else LANE_UNPLANNED


@dataclass
class State:
    available: float
    tech: float
    remit_avail: float              # R(t)
    unit_loss: float                # U(t)
    cap: float | None               # Cap(t) or None
    lost_units: list[str]
    drivers: list[Driver]

    @property
    def pct(self) -> float:
        return 100.0 * self.available / self.tech if self.tech else float("nan")

    def flags(self) -> dict[str, bool]:
        return {
            "remit_planned": any(d.binding and d.source == "remit" and d.planned for d in self.drivers),
            "remit_unplanned": any(d.binding and d.source == "remit" and not d.planned for d in self.drivers),
            "adhoc": any(d.binding and d.source == "adhoc" for d in self.drivers),
        }

    def binding_ids(self, lane: str) -> list[str]:
        return [d.id for d in self.drivers if d.binding and d.lane == lane]


@dataclass
class Segment:
    start: pd.Timestamp
    end: pd.Timestamp
    state: State
    delta_prev: float = 0.0

    @property
    def available(self) -> float:
        return self.state.available


@dataclass
class Lane:
    lane: str
    start: pd.Timestamp
    end: pd.Timestamp
    ids: list[str]
    label: str


@dataclass
class PanelSeries:
    site: str
    direction: str
    tech: float
    window: tuple[pd.Timestamp, pd.Timestamp]
    now: pd.Timestamp
    segments: list[Segment]
    points: pd.DataFrame            # columns: date, available (held values; hover grid)
    lanes: list[Lane]

    def segment_at(self, t: pd.Timestamp) -> Segment | None:
        for s in self.segments:
            if s.start <= t < s.end:
                return s
        return self.segments[-1] if self.segments and t >= self.segments[-1].end else None


# ---------------------------------------------------------------------------
# REMIT side
# ---------------------------------------------------------------------------

def _thread_col(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if "thread" in str(c).lower():
            return c
    return None


def _active_remits(df_op: pd.DataFrame, site: str, direction: str, t: pd.Timestamp) -> pd.DataFrame:
    if df_op.empty:
        return df_op
    return df_op[
        (df_op["__site__"] == site)
        & (df_op["__category__"] == direction)
        & (df_op["__eventStart__"] <= t)
        & (df_op["__eventEnd__"].isna() | (df_op["__eventEnd__"] > t))
    ]


def thread_active_at(df_op: pd.DataFrame, thread_id: str, t: pd.Timestamp) -> bool:
    col = _thread_col(df_op)
    if col is None or df_op.empty:
        return False
    rows = df_op[df_op[col].astype(str) == str(thread_id)]
    if rows.empty:
        return False
    return bool(((rows["__eventStart__"] <= t) & (rows["__eventEnd__"].isna() | (rows["__eventEnd__"] > t))).any())


def remit_state_at(df_op: pd.DataFrame, site: str, direction: str, t: pd.Timestamp, tech: float) -> tuple[float, list[Driver]]:
    """R(t) with 1.0 semantics, plus the notices that drive it."""
    active = _active_remits(df_op, site, direction, t)
    r_avail = float(capacity_at(df_op, site, direction, t, tech))
    drivers: list[Driver] = []
    if active.empty:
        return r_avail, drivers
    col = _thread_col(active)
    stated = active["__availCapacity__"].dropna()
    use_stated = not stated.empty
    m = float(stated.min()) if use_stated else None
    for _, r in active.iterrows():
        tid = str(r[col]) if col else "?"
        av, un = r["__availCapacity__"], r["__unavailCapacity__"]
        planned = str(r["__planned__"]) == "Planned"
        if use_stated:
            binding = pd.notna(av) and abs(float(av) - m) <= EPS
            reduction = (tech - float(av)) if pd.notna(av) else (float(un) if pd.notna(un) else None)
        else:
            reduction = float(un) if pd.notna(un) else 0.0
            binding = reduction > EPS
        drivers.append(Driver(
            "remit", tid, f"REMIT {short_thread(tid)} · {'Planned' if planned else 'Unplanned'}",
            reduction, bool(binding), planned=planned,
            note="" if binding else "overlapping, not binding",
        ))
    return r_avail, drivers


# ---------------------------------------------------------------------------
# Ad-hoc side + combination
# ---------------------------------------------------------------------------

def _unit_labels(equipment: EquipmentConfig, site: str, direction: str, units: list[str]) -> str:
    cfg = equipment.get(site, direction)
    lab = {u.id: u.label for u in cfg.units}
    return ", ".join(lab.get(u, u) for u in units)


def combined_state_at(
    df_op: pd.DataFrame,
    register: Register,
    equipment: EquipmentConfig,
    site: str,
    direction: str,
    t: pd.Timestamp,
    exclude_ids: set[str] | None = None,
    extra: list[AdhocRecord] | None = None,
) -> State:
    """Avail(t) with full driver attribution. `exclude_ids`/`extra` let the
    threshold check evaluate a candidate record before it is saved."""
    cfg = equipment.get(site, direction)
    tech = cfg.nameplate_gwhd
    r_avail, drivers = remit_state_at(df_op, site, direction, t, tech)

    records = [r for r in register.for_site_direction(site, direction) if not exclude_ids or r.id not in exclude_ids]
    records += [r for r in (extra or []) if r.site == site and r.direction == direction]

    lost: set[str] = set()
    cap = math.inf
    contributing: list[AdhocRecord] = []
    covered: list[Driver] = []
    for a in records:
        if not a.active_at(t):
            continue
        if a.covered_by_thread and thread_active_at(df_op, a.covered_by_thread, t):
            covered.append(Driver(
                "adhoc", a.id or "(new)", _adhoc_label(a, equipment), None, False, units=list(a.units),
                note=f"covered by REMIT {short_thread(a.covered_by_thread)}",
            ))
            continue
        if a.kind == "unit_out":
            lost |= set(a.units)
            contributing.append(a)
        elif a.kind == "rate_cap" and a.resulting_avail_gwhd is not None:
            cap = min(cap, float(a.resulting_avail_gwhd))
            contributing.append(a)

    unit_loss = equipment.gwhd_lost(site, direction, lost) if lost else 0.0
    ru = r_avail - unit_loss
    avail = min(ru, cap)
    avail = max(0.0, min(float(avail), tech))
    cap_binding = cap < ru - EPS

    for a in contributing:
        if a.kind == "unit_out":
            binding = (not cap_binding) and unit_loss > EPS
            reduction = equipment.gwhd_lost(site, direction, a.units)
        else:
            binding = cap_binding and abs(float(a.resulting_avail_gwhd) - cap) <= EPS
            reduction = max(0.0, ru - float(a.resulting_avail_gwhd))
        drivers.append(Driver(
            "adhoc", a.id or "(new)", _adhoc_label(a, equipment), reduction, bool(binding),
            units=list(a.units), note="" if binding else "overlapping, not binding",
        ))
    drivers += covered
    return State(avail, tech, r_avail, unit_loss, None if math.isinf(cap) else cap, sorted(lost), drivers)


def _adhoc_label(a: AdhocRecord, equipment: EquipmentConfig) -> str:
    ident = a.id or "new ad-hoc"
    if a.kind == "unit_out":
        return f"{ident}: {_unit_labels(equipment, a.site, a.direction, a.units)} out"
    if a.kind == "rate_cap":
        return f"{ident}: rate capped at {float(a.resulting_avail_gwhd):g} GWh/d"
    return ident


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def _breakpoints(df_op, register, site, direction, start, end, now) -> list[pd.Timestamp]:
    bps = {start, end}
    if start < now < end:
        bps.add(now)
    if not df_op.empty:
        sub = df_op[(df_op["__site__"] == site) & (df_op["__category__"] == direction)]
        for col in ("__eventStart__", "__eventEnd__"):
            for v in sub[col].dropna():
                if start < v < end:
                    bps.add(pd.Timestamp(v))
    for a in register.for_site_direction(site, direction):
        if not a.counts_in_maths():
            continue
        for v in (a.start_ts, a.end_ts):
            if v is not None and start < v < end:
                bps.add(v)
        if a.covered_by_thread and not df_op.empty:
            col = _thread_col(df_op)
            if col:
                rows = df_op[df_op[col].astype(str) == str(a.covered_by_thread)]
                for v in rows["__eventEnd__"].dropna():
                    if start < v < end:
                        bps.add(pd.Timestamp(v))
    return sorted(bps)


def compute_combined_series(
    df_op: pd.DataFrame,
    register: Register,
    equipment: EquipmentConfig,
    site: str,
    direction: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    now: pd.Timestamp,
    fill_step: pd.Timedelta | None = None,
    max_points: int = 1200,
) -> PanelSeries:
    """Exact step function of combined availability over [start, end), with
    per-segment cause attribution and merged cause lanes."""
    cfg = equipment.get(site, direction)
    tech = cfg.nameplate_gwhd
    bps = _breakpoints(df_op, register, site, direction, start, end, now)
    if fill_step is None:
        fill_step = max(pd.Timedelta(hours=1), (end - start) / max_points)

    segments: list[Segment] = []
    prev = None
    for a, b in zip(bps, bps[1:]):
        state = combined_state_at(df_op, register, equipment, site, direction, a + (b - a) / 2)
        seg = Segment(a, b, state, 0.0 if prev is None else state.available - prev.available)
        segments.append(seg)
        prev = state

    # Hover grid: held values, step edges exact.
    pts: list[tuple[pd.Timestamp, float]] = []
    for seg in segments:
        pts.append((seg.start, seg.available))
        t = seg.start + fill_step
        while t < seg.end:
            pts.append((t, seg.available))
            t += fill_step
    if segments:
        pts.append((segments[-1].end, segments[-1].available))
    points = pd.DataFrame(pts, columns=["date", "available"])

    # Lanes: merge consecutive segments with the same binding ids per lane.
    lanes: list[Lane] = []
    for lane in LANES:
        open_: Lane | None = None
        for seg in segments:
            ids = seg.state.binding_ids(lane)
            if ids:
                if open_ is not None and open_.ids == ids and open_.end == seg.start:
                    open_.end = seg.end
                else:
                    if open_ is not None:
                        lanes.append(open_)
                    labels = [d.label for d in seg.state.drivers if d.binding and d.lane == lane]
                    open_ = Lane(lane, seg.start, seg.end, list(ids), "; ".join(labels))
            elif open_ is not None:
                lanes.append(open_)
                open_ = None
        if open_ is not None:
            lanes.append(open_)
    return PanelSeries(site, direction, tech, (start, end), now, segments, points, lanes)


# ---------------------------------------------------------------------------
# Threshold check
# ---------------------------------------------------------------------------

@dataclass
class ThresholdResult:
    quarter: str
    threshold: float
    impact_gwhd: float
    aggregate_after_gwhd: float
    exceeds: bool
    baseline_avail: float
    resulting_avail: float


def threshold_check(candidate: AdhocRecord, register: Register, equipment: EquipmentConfig,
                    df_op: pd.DataFrame, now: pd.Timestamp) -> ThresholdResult:
    """Would this ad-hoc (alone, or together with the other unpublished ad-hocs
    at its start instant) exceed the REMIT publication threshold?"""
    from ..core.timeutil import quarter_of
    t0 = candidate.start_ts
    thr = equipment.threshold_for(t0)
    excl = {candidate.id} if candidate.id else set()
    before = combined_state_at(df_op, register, equipment, candidate.site, candidate.direction, t0, exclude_ids=excl)
    after = combined_state_at(df_op, register, equipment, candidate.site, candidate.direction, t0,
                              exclude_ids=excl, extra=[candidate])
    if candidate.kind == "unit_out":
        impact = equipment.gwhd_lost(candidate.site, candidate.direction, candidate.units)
    else:
        impact = max(0.0, before.available - float(candidate.resulting_avail_gwhd or 0.0))
    aggregate_after = max(0.0, after.remit_avail - after.available)   # all unpublished reduction
    return ThresholdResult(quarter_of(t0), thr, impact, aggregate_after,
                           impact > thr or aggregate_after > thr, before.available, after.available)
