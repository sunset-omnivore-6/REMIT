"""The ad-hoc register table with row selection -> edit / close / cancel."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..adhoc.model import EquipmentConfig, Register
from ..core.constants import site_label
from ..core.timeutil import fmt_local
from . import forms


def _what(r, equipment: EquipmentConfig) -> str:
    if r.kind == "unit_out":
        labels = {u.id: u.label for u in equipment.get(r.site, r.direction).units}
        return ", ".join(labels.get(u, u) for u in r.units) + " out"
    return f"capped at {r.resulting_avail_gwhd:g} GWh/d"


def render_register(register: Register, equipment: EquipmentConfig, now: pd.Timestamp, actor: str, editor: bool,
                    store_ok: bool) -> None:
    show_cancelled = st.checkbox("Show cancelled", value=False, key="rv_show_cancelled")
    recs = [r for r in register.records if show_cancelled or r.status(now) != "cancelled"]
    recs.sort(key=lambda r: (r.status(now) not in ("active", "planned"), r.start), reverse=False)
    if not recs:
        st.caption("No ad-hoc adjustments recorded.")
        return
    rows = []
    for r in recs:
        status = r.status(now)
        flag = " ⚠ stale" if r.is_stale(now, equipment.stale_after_days) else (" ⚠ overdue" if r.is_overdue(now) else "")
        rows.append({
            "ID": r.id, "Site": site_label(r.site), "Type": r.direction, "What": _what(r, equipment),
            "Impact GWh/d": r.impact_gwhd(equipment), "Start": fmt_local(r.start),
            "End": "until further notice" if r.end is None else fmt_local(r.end),
            "Expected return": fmt_local(r.expected_return) if r.expected_return else "",
            "Status": status + flag, "Covered by": r.covered_by_thread or "", "Entered by": r.created_by,
            "Updated": fmt_local(r.updated_at) + f" by {r.updated_by}",
        })
    df = pd.DataFrame(rows)
    ev = st.dataframe(df, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
                      key="rv_table", height=min(400, 38 * (len(df) + 1) + 4))
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel:
        st.caption("Select a row to edit, close or cancel it, and to see its history.")
        return
    rec = recs[sel[0]]
    st.markdown(f"**{rec.id}** — {rec.notes}")
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    can = editor and store_ok
    with c1:
        if st.button("Edit", key=f"rv_edit_{rec.id}", disabled=not can, width="stretch"):
            st.session_state["r2_dialog_open"] = True
            st.session_state["ef__reset"] = True
            forms.edit_adhoc_dialog(rec, equipment, actor)
    with c2:
        if st.button("Close", key=f"rv_close_{rec.id}", disabled=not can or rec.status(now) in ("ended", "cancelled"), width="stretch"):
            st.session_state["r2_dialog_open"] = True
            st.session_state["cf__reset"] = True
            forms.close_adhoc_dialog(rec, actor)
    with c3:
        if st.button("Cancel entry", key=f"rv_cancel_{rec.id}", disabled=not can or rec.status(now) == "cancelled", width="stretch"):
            st.session_state["r2_dialog_open"] = True
            st.session_state["xf__reset"] = True
            forms.cancel_adhoc_dialog(rec, actor)
    with st.expander("History"):
        for h in rec.history:
            ch = "; ".join(f"{k}: {v[0]!r} → {v[1]!r}" for k, v in (h.changes or {}).items())
            st.markdown(f"<div class='r2-row'><span class='k'>{h.action}</span><span class='m'>{fmt_local(h.ts)} · {h.actor}</span>"
                        f"<span>{ch}</span><span class='m'>{h.reason or ''}</span></div>", unsafe_allow_html=True)
