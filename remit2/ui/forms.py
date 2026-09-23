"""Ad-hoc dialogs: new, edit, close, cancel. Progressive disclosure (not
st.form) so each step reacts to the previous one."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time as dtime

import pandas as pd
import streamlit as st

from ..adhoc.combine import combined_state_at, threshold_check
from ..adhoc.model import AdhocRecord, EquipmentConfig, Register, new_record, validate_record
from ..adhoc.store import StoreUnavailable, VersionConflict
from ..core.capacity import short_thread
from ..core.constants import site_label
from ..core.timeutil import LONDON, fmt_local, iso_utc, parse_iso, to_utc
from . import data as d

SITES_UI = {"Hornsea": "Atwick", "Aldbrough": "Aldbrough"}
DIRECTIONS = ["Injection", "Withdrawal"]


def _now_local_rounded() -> datetime:
    t = pd.Timestamp.now(tz=LONDON).floor("15min")
    return t.to_pydatetime().replace(tzinfo=None)


def _when(prefix: str, default: datetime, label: str) -> pd.Timestamp:
    c1, c2 = st.columns(2)
    with c1:
        day = st.date_input(f"{label} date", value=default.date(), key=f"{prefix}_date", format="DD/MM/YYYY")
    with c2:
        tm = st.time_input(f"{label} time (UK)", value=default.time(), key=f"{prefix}_time", step=900)
    return to_utc(datetime.combine(day, tm))


def _overlapping_threads(df_op: pd.DataFrame, site: str, direction: str, start: pd.Timestamp, end: pd.Timestamp | None) -> list[tuple[str, str]]:
    if df_op.empty:
        return []
    col = next((c for c in df_op.columns if "thread" in str(c).lower()), None)
    if not col:
        return []
    sub = df_op[(df_op["__site__"] == site) & (df_op["__category__"] == direction)]
    out = []
    for _, r in sub.iterrows():
        s, e = r["__eventStart__"], r["__eventEnd__"]
        if pd.isna(s):
            continue
        if (end is None or s < end) and (pd.isna(e) or e > start):
            av = r["__availCapacity__"]
            out.append((str(r[col]), f"{short_thread(r[col])} · {r['__planned__']} · {fmt_local(s)} → {fmt_local(e)}"
                        + (f" · available {float(av):g}" if pd.notna(av) else "")))
    return out


def _finish(flash: str) -> None:
    st.session_state["r2_flash"] = flash
    st.session_state["r2_dialog_open"] = False
    st.cache_data.clear()
    st.rerun()


def _store_error(exc: Exception) -> None:
    if isinstance(exc, VersionConflict):
        st.error("Someone else changed the register while you were editing — please close this and try again.")
    elif isinstance(exc, StoreUnavailable):
        st.error("The register store can't be reached right now — nothing was saved. Try again in a minute.")
    else:
        st.error("Couldn't save — please try again.")


@st.dialog("New ad-hoc adjustment", width="large")
def new_adhoc_dialog(equipment: EquipmentConfig, register: Register, df_op: pd.DataFrame, actor: str) -> None:
    if st.session_state.pop("af_reset", False):
        for k in [k for k in st.session_state if k.startswith("af_")]:
            del st.session_state[k]
        st.session_state["af_draft"] = str(uuid.uuid4())
    st.session_state.setdefault("af_draft", str(uuid.uuid4()))
    now = pd.Timestamp.now(tz="UTC")

    c1, c2 = st.columns(2)
    with c1:
        site_ui = st.segmented_control("Site", list(SITES_UI), key="af_site", default="Hornsea") or "Hornsea"
    with c2:
        direction = st.segmented_control("Type", DIRECTIONS, key="af_dir", default="Injection") or "Injection"
    site = SITES_UI[site_ui]
    cfg = equipment.get(site, direction)
    st.session_state.setdefault("af_kind", "Units out")
    kind_ui = st.session_state["af_kind"]
    units: list[str] = []
    resulting: float | None = None
    if kind_ui == "Units out":
        # Equipment as tiles: each shows what the unit is worth; the selection is dotted like the ad-hoc shading.
        labels = {unit_tile_label(u): u.id for u in cfg.units}
        picked = st.pills("What’s out", list(labels), selection_mode="multi", key="af_units") or []
        units = [labels[l] for l in picked]
        if any(u.placeholder for u in cfg.units):
            st.caption("⚠ Placeholder unit values for this site — confirm before relying on the numbers.")
    else:
        resulting = st.number_input("Resulting available capacity (GWh/d)", min_value=0.0,
                                    max_value=float(cfg.nameplate_gwhd), value=float(cfg.nameplate_gwhd), step=0.5,
                                    key="af_rate", help="Enter what will be AVAILABLE, not the reduction")
    if st.button("Rate change instead" if kind_ui == "Units out" else "Units out instead", type="tertiary", key="af_kind_btn"):
        st.session_state["af_kind"] = "Rate change" if kind_ui == "Units out" else "Units out"
        st.rerun(scope="fragment")

    st.markdown("**When**")
    start = _when("af_start", _now_local_rounded(), "Start")
    ends = st.radio("Ends", ["Until further notice", "At a set time"], horizontal=True, key="af_ends")
    end = None
    exp = None
    if ends == "At a set time":
        end = _when("af_end", _now_local_rounded() + pd.Timedelta(days=1), "End")
    else:
        if st.checkbox("Add an expected return (for tracking only — the entry stays active until it is closed)", key="af_hasexp"):
            exp = _when("af_exp", _now_local_rounded() + pd.Timedelta(days=1), "Expected return")

    threads = _overlapping_threads(df_op, site, direction, start, end)
    cov_label = st.selectbox("Already covered by a published REMIT?", ["None — not published"] + [t[1] for t in threads],
                             key="af_cov", help="If a live REMIT already includes this, the entry is shown but not added to the maths")
    covered = next((t[0] for t in threads if t[1] == cov_label), None)
    notes = st.text_area("Notes (required)", key="af_notes", placeholder="What happened / why, and anything the team should know")

    rec = new_record(site, direction, "unit_out" if kind_ui == "Units out" else "rate_cap", start, notes or "",
                     units=units, resulting_avail_gwhd=resulting, end=end, expected_return=exp,
                     covered_by_thread=covered, draft_id=st.session_state["af_draft"])
    errors = validate_record(rec, equipment, now)
    ack_ok = True
    if not errors:
        thr = threshold_check(rec, register, equipment, df_op, now)
        _preview(rec, thr, register, equipment, df_op, now)
        dup = [r for r in register.for_site_direction(site, direction) if r.kind == "unit_out" and set(r.units) & set(units)
               and r.status(now) in ("active", "planned")]
        if dup:
            st.info(f"Note: {', '.join(r.id for r in dup)} already lists one of these units for an overlapping period.")
        if thr.exceeds:
            st.warning("This exceeds the REMIT publication threshold — it should probably be published as a REMIT, not entered as an ad-hoc.")
            ack_ok = st.checkbox("I understand this may need a REMIT publication", key="af_ack")
    else:
        for e in errors:
            st.caption(f"• {e}")

    _, c2, c1 = st.columns([3, 1, 1.2])
    with c1:
        if st.button("Save ad-hoc", type="primary", disabled=st.session_state.get("af_saving", False), width="stretch"):
            if errors:
                st.error("Please fix: " + " ".join(errors))
            elif not ack_ok:
                st.error("Tick the acknowledgement above to save an entry over the REMIT threshold.")
            else:
                st.session_state["af_saving"] = True
            try:
                if not errors and ack_ok:
                    _save_new(rec, actor, now)
            except Exception as exc:  # noqa: BLE001
                st.session_state["af_saving"] = False
                _store_error(exc)
    with c2:
        if st.button("Cancel", width="stretch"):
            st.session_state["r2_dialog_open"] = False
            st.rerun()


def unit_tile_label(u) -> str:
    return f"{u.label} · {u.gwhd_lost:g} GWh/d"


def _preview(rec: AdhocRecord, thr, register: Register, equipment: EquipmentConfig, df_op: pd.DataFrame,
             now: pd.Timestamp) -> None:
    """See the effect before saving: the site/direction chart with the new entry
    included, the resulting levels in words, and the threshold as a measured bar."""
    from ..adhoc.combine import compute_combined_series
    from .hero import day_label, panel_figure, time_label
    trial = Register(schema_version=register.schema_version, meta=dict(register.meta), records=list(register.records) + [rec])
    horizon = int(st.session_state.get("r2_horizon_days", 30))
    start = (now - pd.Timedelta(days=max(1, horizon // 4))).floor("h")
    end = (now + pd.Timedelta(days=horizon)).ceil("h")
    if rec.end_ts is not None and rec.end_ts + pd.Timedelta(days=2) > end:
        end = (rec.end_ts + pd.Timedelta(days=2)).ceil("h")
    series = compute_combined_series(df_op, trial, equipment, rec.site, rec.direction, start, end, now)
    with st.container(key=f"af_prev_{rec.site.lower()}"):
        st.markdown(f"<div class='r2-prevhd'><span>Effect on {site_label(rec.site)} {rec.direction.lower()}</span>"
                    f"<span>preview</span></div>", unsafe_allow_html=True)
        st.plotly_chart(panel_figure(series, equipment, mini=True, show_x=False, max_events=3), width="stretch",
                        config={"displayModeBar": False, "responsive": True}, key="af_prev_fig")
        t0 = rec.start_ts
        window = [s for s in series.segments if s.end > t0 and (rec.end_ts is None or s.start < rec.end_ts)]
        low = min(window, key=lambda s: s.available) if window else None
        bits = [f"<b>{thr.resulting_avail:.1f}</b> at start (was {thr.baseline_avail:.1f})"]
        if low is not None and low.available < thr.resulting_avail - 1e-6:
            when = max(low.start, t0)
            bits.append(f"lowest <b>{low.available:.1f}</b> from {day_label(when)} {time_label(when)}")
        if rec.end_ts is not None:
            back = series.segment_at(rec.end_ts)
            if back is not None:
                bits.append(f"<b>{back.available:.1f}</b> again from {day_label(rec.end_ts)} {time_label(rec.end_ts)}")
        pct = min(100.0, 100.0 * thr.aggregate_after_gwhd / thr.threshold) if thr.threshold else 100.0
        over = "r2-thr--over" if thr.exceeds else ""
        st.markdown(
            f"<p class='r2-prevtxt'>{' · '.join(bits)}</p>"
            f"<div class='r2-thr {over}'><div class='bar'><span style='width:{pct:.1f}%'></span></div>"
            f"<span>Unpublished reduction <b>{thr.aggregate_after_gwhd:.1f} of {thr.threshold:g} GWh/d</b> · "
            f"{'above' if thr.exceeds else 'below'} the {thr.quarter} REMIT threshold</span></div>", unsafe_allow_html=True)


def _save_new(rec: AdhocRecord, actor: str, now: pd.Timestamp) -> None:
    d.get_store().mutate(lambda r: r.create(rec, actor, now), actor, "create ad-hoc")
    st.session_state["af_saving"] = False
    _finish("Ad-hoc saved.")



def _reset_keys(prefix: str) -> None:
    """Dialog widgets are keyed; without this a re-opened dialog would show the
    previous open's values instead of the record's."""
    if st.session_state.pop(f"{prefix}_reset", False):
        for k in [k for k in st.session_state if k.startswith(prefix)]:
            del st.session_state[k]


@st.dialog("Edit ad-hoc", width="large")
def edit_adhoc_dialog(rec: AdhocRecord, equipment: EquipmentConfig, actor: str) -> None:
    _reset_keys("ef_")
    cfg = equipment.get(rec.site, rec.direction)
    st.markdown(f"**{rec.id}** · {site_label(rec.site)} · {rec.direction} · {'Units out' if rec.kind == 'unit_out' else 'Rate change'}")
    changes: dict = {}
    if rec.kind == "unit_out":
        labels = {unit_tile_label(u): u.id for u in cfg.units}
        cur = [l for l, i in labels.items() if i in rec.units]
        picked = st.pills("Units unavailable", list(labels), selection_mode="multi", default=cur, key=f"ef_units_{rec.id}") or []
        changes["units"] = [labels[l] for l in picked]
    else:
        changes["resulting_avail_gwhd"] = float(st.number_input("Resulting available (GWh/d)", 0.0, float(cfg.nameplate_gwhd),
                                                                value=float(rec.resulting_avail_gwhd or 0), step=0.5, key=f"ef_rate_{rec.id}"))
    start_loc = parse_iso(rec.start).tz_convert(LONDON).to_pydatetime().replace(tzinfo=None)
    changes["start"] = iso_utc(_when(f"ef_start_{rec.id}", start_loc, "Start"))
    ends = st.radio("Ends", ["Until further notice", "At a set time"], horizontal=True,
                    index=0 if rec.end is None else 1, key=f"ef_ends_{rec.id}")
    if ends == "Until further notice":
        changes["end"] = None
    else:
        end_loc = (parse_iso(rec.end) if rec.end else pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).tz_convert(LONDON).to_pydatetime().replace(tzinfo=None)
        changes["end"] = iso_utc(_when(f"ef_end_{rec.id}", end_loc, "End"))
    changes["notes"] = st.text_area("Notes", value=rec.notes, key=f"ef_notes_{rec.id}")
    reason = st.text_input("Reason for this change (required)", key=f"ef_reason_{rec.id}")
    now = pd.Timestamp.now(tz="UTC")
    trial = AdhocRecord.from_dict({**rec.to_dict(), **changes})
    errors = validate_record(trial, equipment, now)
    for e in errors:
        st.caption(f"• {e}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save changes", type="primary", disabled=bool(errors) or len(reason.strip()) < 3, width="stretch"):
            try:
                d.get_store().mutate(lambda r: r.update(rec.id, changes, actor, now, reason.strip()), actor, f"{rec.id} update")
                _finish(f"{rec.id} updated.")
            except Exception as exc:  # noqa: BLE001
                _store_error(exc)
    with c2:
        if st.button("Cancel", width="stretch", key=f"ef_cancel_{rec.id}"):
            st.session_state["r2_dialog_open"] = False
            st.rerun()


@st.dialog("Close ad-hoc")
def close_adhoc_dialog(rec: AdhocRecord, actor: str) -> None:
    _reset_keys("cf_")
    st.markdown(f"**{rec.id}** · {site_label(rec.site)} · {rec.direction}")
    mode = st.radio("When did it end?", ["Now", "At a time"], horizontal=True, key=f"cf_mode_{rec.id}")
    now = pd.Timestamp.now(tz="UTC")
    at = now if mode == "Now" else _when(f"cf_at_{rec.id}", _now_local_rounded(), "Ended")
    reason = st.text_input("Reason (required)", key=f"cf_reason_{rec.id}", placeholder="e.g. back in service / superseded by REMIT ATW_1402")
    if st.button("Close ad-hoc", type="primary", disabled=len(reason.strip()) < 3):
        try:
            d.get_store().mutate(lambda r: r.close(rec.id, actor, now, reason.strip(), at=at), actor, f"{rec.id} close")
            _finish(f"{rec.id} closed.")
        except Exception as exc:  # noqa: BLE001
            _store_error(exc)


@st.dialog("Cancel ad-hoc")
def cancel_adhoc_dialog(rec: AdhocRecord, actor: str) -> None:
    _reset_keys("xf_")
    st.markdown(f"**{rec.id}** · {site_label(rec.site)} · {rec.direction}")
    st.caption("Cancelling removes the entry from the graphs and counts. It stays in the history (nothing is deleted).")
    reason = st.text_input("Reason (required)", key=f"xf_reason_{rec.id}", placeholder="e.g. entered in error / test entry")
    if st.button("Cancel this ad-hoc", type="primary", disabled=len(reason.strip()) < 3):
        try:
            now = pd.Timestamp.now(tz="UTC")
            d.get_store().mutate(lambda r: r.cancel(rec.id, actor, now, reason.strip()), actor, f"{rec.id} cancel")
            _finish(f"{rec.id} cancelled.")
        except Exception as exc:  # noqa: BLE001
            _store_error(exc)
