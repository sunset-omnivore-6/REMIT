"""Controls row (one row above everything it scopes)."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

HORIZON_PRESETS = {"7d": 7, "14d": 14, "30d": 30, "60d": 60, "90d": 90}


@dataclass
class Controls:
    horizon_days: int
    show_as: str        # "Values" | "Plant"
    show_tables: bool
    patterns: bool
    refresh: bool


def _use_preset() -> None:
    if st.session_state.get("r2_horizon_preset") is None:       # deselect -> snap back
        st.session_state["r2_horizon_preset"] = st.session_state.get("r2_horizon_last", "30d")
    st.session_state["r2_horizon_last"] = st.session_state["r2_horizon_preset"]
    st.session_state["r2_horizon_mode"] = "preset"


def _use_custom() -> None:
    st.session_state["r2_horizon_mode"] = "custom"
    st.session_state["r2_horizon_preset"] = None


def render_controls(wall: bool = False) -> Controls:
    st.session_state.setdefault("r2_horizon_preset", "30d")
    st.session_state.setdefault("r2_horizon_custom", 30)
    st.session_state.setdefault("r2_horizon_mode", "preset")
    st.session_state.setdefault("r2_show_as", "Values")
    if wall:
        return Controls(_horizon(), st.session_state["r2_show_as"], False, True, False)

    c1, c2, c3, c4, c5, c6 = st.columns([3.2, 1.1, 1.6, 1.2, 1.2, 1.0], vertical_alignment="bottom")
    with c1:
        st.segmented_control("Horizon", list(HORIZON_PRESETS), key="r2_horizon_preset",
                             on_change=_use_preset, help="How far ahead the graphs look")
    with c2:
        with st.popover("Custom", width="stretch"):
            st.number_input("Days ahead", 1, 730, key="r2_horizon_custom", on_change=_use_custom)
    with c3:
        st.segmented_control("Show as", ["Values", "Plant"], key="r2_show_as",
                             help="Plant: Hornsea in equipment terms (comps, Vortisep, Phase 6)")
        if st.session_state.get("r2_show_as") is None:
            st.session_state["r2_show_as"] = "Values"
    with c4:
        show_tables = st.toggle("Tables", value=False, key="r2_show_tables", help="Open every graph's table view")
    with c5:
        patterns = st.toggle("Patterns", value=True, key="r2_patterns", help="Hatch the cause lanes as well as colouring them")
    with c6:
        refresh = st.button("⟳ Refresh", width="stretch")
    return Controls(_horizon(), st.session_state.get("r2_show_as") or "Values", show_tables, patterns, refresh)


def _horizon() -> int:
    if st.session_state.get("r2_horizon_mode") == "custom":
        return int(st.session_state["r2_horizon_custom"])
    return HORIZON_PRESETS[st.session_state.get("r2_horizon_preset") or "30d"]
