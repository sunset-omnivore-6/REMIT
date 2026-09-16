"""Text twins: the one-sentence narrative for a panel (screen-reader path and
fastest human read) and Plant-view wording. Pure."""
from __future__ import annotations

import pandas as pd

from ..core.timeutil import fmt_local
from .combine import PanelSeries, Segment, State
from .model import EquipmentConfig


def _q(v: float) -> str:
    return f"{v:.1f}"


def plant_terms(state: State, equipment: EquipmentConfig, site: str, direction: str) -> str:
    """Availability in equipment terms. Ad-hoc units are named exactly;
    REMIT reductions are GWh/d-only, so they are converted to the nearest
    whole-unit equivalent and marked '≈'."""
    cfg = equipment.get(site, direction)
    labels = {u.id: u.label for u in cfg.units}
    parts: list[str] = []
    remit_reduction = max(0.0, state.tech - state.remit_avail)
    uniform = cfg.unit_noun and len({u.gwhd_lost for u in cfg.units}) == 1 and cfg.units
    if uniform:
        per = cfg.units[0].gwhd_lost
        n = len(cfg.units)
        adhoc_out = len(state.lost_units)
        remit_equiv = int(round(remit_reduction / per)) if per else 0
        avail_units = max(0, n - adhoc_out - remit_equiv)
        noun = cfg.unit_noun + ("s" if n != 1 else "")          # "1 of 4 comps"
        parts.append(f"{avail_units} of {n} {noun} available")
        if adhoc_out:
            parts.append(", ".join(labels.get(u, u) for u in state.lost_units) + " out (ad-hoc)")
        if remit_equiv:
            parts.append(f"≈ {remit_equiv} {cfg.unit_noun}{'s' if remit_equiv != 1 else ''} out (REMIT)")
    else:
        if state.lost_units:
            parts.append(", ".join(labels.get(u, u) for u in state.lost_units) + " out (ad-hoc)")
        if remit_reduction > 1e-6:
            match = [u for u in cfg.units if abs(u.gwhd_lost - remit_reduction) <= 0.15 * u.gwhd_lost]
            if match:
                parts.append(f"≈ {match[0].label}-sized outage (REMIT)")
            else:
                parts.append(f"REMIT −{_q(remit_reduction)} GWh/d")
        if not parts:
            parts.append("all plant available")
    if state.cap is not None and state.available <= state.cap + 1e-6 and state.cap < state.remit_avail - state.unit_loss - 1e-6:
        parts.append(f"rate capped at {_q(state.cap)} GWh/d")
    return " · ".join(parts)


def _cause(seg: Segment) -> str:
    ids = [d.label for d in seg.state.drivers if d.binding]
    if ids:
        return f" ({'; '.join(ids)})"
    return " (outage ends)" if seg.delta_prev > 0 else ""


def narrate_panel(series: PanelSeries, equipment: EquipmentConfig, mode: str = "values") -> str:
    now = series.now
    cur = series.segment_at(now)
    if cur is None:
        return "No data for this window."
    tech = series.tech
    if mode == "plant" and equipment.get(series.site, series.direction).plant_view:
        pt = plant_terms(cur.state, equipment, series.site, series.direction)
        head = pt[:1].upper() + pt[1:] + " now"
        head += f" ({_q(cur.available)} of {tech:g} GWh/d)."
    else:
        head = f"{_q(cur.available)} of {tech:g} GWh/d available now ({cur.state.pct:.0f}%)."
    future = [s for s in series.segments if s.start > now and abs(s.delta_prev) > 1e-6]
    if not future:
        days = (series.window[1] - now).days
        return f"{head} No changes in the next {days} days."
    nxt = future[0]
    verb = "Drops" if nxt.delta_prev < 0 else "Rises"
    sent = f"{head} {verb} to {_q(nxt.available)} at {fmt_local(nxt.start)}{_cause(nxt)}."
    if len(future) > 1:
        after = future[1]
        if abs(after.available - tech) < 1e-6:
            sent += f" Back to {tech:g} at {fmt_local(after.start)}."
        else:
            sent += f" Then {_q(after.available)} at {fmt_local(after.start)}{_cause(after)}."
    return sent
