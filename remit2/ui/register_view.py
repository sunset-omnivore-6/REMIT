"""The ad-hoc register (design review sheet 05): one row per entry with a
readable status (word + symbol), entries needing review first, and the
actions on the row itself. Ended / cancelled entries are hidden behind a toggle."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from ..adhoc.model import EquipmentConfig, Register
from ..core.capacity import short_thread
from ..core.constants import site_label
from ..core.timeutil import fmt_local
from . import forms
from .hero import day_label, time_label

COLS = [0.62, 1.55, 0.55, 1.75, 1.45, 0.8, 1.9]


def _needs_review(r, equipment: EquipmentConfig, now: pd.Timestamp) -> bool:
    return r.status(now) in ("active", "planned") and (r.is_stale(now, equipment.stale_after_days) or r.is_overdue(now))


def review_count(register: Register, equipment: EquipmentConfig, now: pd.Timestamp) -> int:
    return sum(1 for r in register.records if _needs_review(r, equipment, now))


def _status_html(r, equipment: EquipmentConfig, now: pd.Timestamp) -> str:
    st_ = r.status(now)
    if _needs_review(r, equipment, now):
        why = "overdue" if r.is_overdue(now) else f"{(now - r.start_ts).days} days open"
        return f"<span class='r2-st r2-st--review'><i></i>Review · {why}</span>"
    return f"<span class='r2-st r2-st--{st_}'><i></i>{st_.capitalize()}</span>"


def _what(r, equipment: EquipmentConfig) -> str:
    if r.kind == "unit_out":
        labels = {u.id: u.label for u in equipment.get(r.site, r.direction).units}
        what = ", ".join(labels.get(u, u) for u in r.units)
    else:
        what = f"capped at {r.resulting_avail_gwhd:g} GWh/d"
    if r.covered_by_thread:
        what += f" · covered by {short_thread(r.covered_by_thread)}"
    return what


def _when(r) -> str:
    s = f"{day_label(r.start_ts)} {time_label(r.start_ts)} →<br>"
    s += "until further notice" if r.end is None else f"{day_label(r.end_ts)} {time_label(r.end_ts)}"
    if r.end is None and r.expected_return:
        er = pd.Timestamp(r.expected_return)
        s += f"<br><span class='muted'>expected back {day_label(er)} {time_label(er)}</span>"
    return s


def _cell(html_: str) -> None:
    st.markdown(f"<div class='r2-td'>{html_}</div>", unsafe_allow_html=True)


def render_register(register: Register, equipment: EquipmentConfig, now: pd.Timestamp, actor: str, editor: bool,
                    store_ok: bool) -> None:
    live = [r for r in register.records if r.status(now) in ("active", "planned")]
    past = [r for r in register.records if r.status(now) in ("ended", "cancelled")]
    show_past = st.toggle(f"Show ended and cancelled ({len(past)})", value=False, key="rv_show_past",
                          help="Past entries are kept for the record but hidden by default")
    recs = live + (past if show_past else [])
    order = {"active": 1, "planned": 2, "ended": 3, "cancelled": 4}
    recs.sort(key=lambda r: (0 if _needs_review(r, equipment, now) else order[r.status(now)], r.start))
    if not recs:
        st.caption("No live ad-hoc adjustments." + (f" {len(past)} ended or cancelled hidden." if past else ""))
        return
    with st.container(key="rvhead"):
        head = st.columns(COLS, vertical_alignment="bottom")
        for c, h in zip(head, ["ID", "What’s out", "GWh/d", "When (UK)", "Status", "Entered by", ""]):
            c.markdown(f"<div class='r2-th'>{h}</div>", unsafe_allow_html=True)
    can = editor and store_ok
    for r in recs:
        status = r.status(now)
        imp = r.impact_gwhd(equipment)
        with st.container(key=f"rvrow-{r.id}"):
            c = st.columns(COLS, vertical_alignment="top")
            with c[0]:
                _cell(f"<b>{r.id}</b>")
            with c[1]:
                _cell(f"{site_label(r.site)} · {r.direction}<br><span class='muted'>{html.escape(_what(r, equipment))}</span>")
            with c[2]:
                _cell(f"−{imp:.1f}" if imp is not None else "—")
            with c[3]:
                _cell(_when(r))
            with c[4]:
                _cell(_status_html(r, equipment, now))
            with c[5]:
                _cell(html.escape(r.created_by.split("@")[0]))
            with c[6]:
                a, b, x, h = st.columns(4, gap="small")
                with a:
                    if st.button("Edit", key=f"rv_edit_{r.id}", type="tertiary", disabled=not can or status == "cancelled"):
                        st.session_state["r2_dialog_open"] = True
                        st.session_state["ef__reset"] = True
                        forms.edit_adhoc_dialog(r, equipment, actor)
                with b:
                    if st.button("Close", key=f"rv_close_{r.id}", type="tertiary", disabled=not can or status in ("ended", "cancelled")):
                        st.session_state["r2_dialog_open"] = True
                        st.session_state["cf__reset"] = True
                        forms.close_adhoc_dialog(r, actor)
                with x:
                    if st.button("Cancel", key=f"rv_cancel_{r.id}", type="tertiary", disabled=not can or status == "cancelled"):
                        st.session_state["r2_dialog_open"] = True
                        st.session_state["xf__reset"] = True
                        forms.cancel_adhoc_dialog(r, actor)
                with h:
                    if st.button("History", key=f"rv_hist_{r.id}", type="tertiary"):
                        st.session_state["rv_hist"] = None if st.session_state.get("rv_hist") == r.id else r.id
            if st.session_state.get("rv_hist") == r.id:
                lines = [f"<div class='r2-td'><b>Notes</b> · {html.escape(r.notes)}</div>"]
                for ev in r.history:
                    ch = "; ".join(f"{k}: {v[0]!r} → {v[1]!r}" for k, v in (ev.changes or {}).items())
                    lines.append(f"<div class='r2-td'><b>{ev.action}</b> <span class='muted'>{fmt_local(ev.ts)} · {html.escape(ev.actor)}</span>"
                                 f"{' · ' + html.escape(ch) if ch else ''}{' · ' + html.escape(ev.reason) if ev.reason else ''}</div>")
                st.markdown("".join(lines), unsafe_allow_html=True)
    if not editor:
        st.caption("View only — ask an editor to add, change or close ad-hocs.")
