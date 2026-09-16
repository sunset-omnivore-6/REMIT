"""Controls row (one row above everything it scopes)."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

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
    st.session_state.setdefault("r2_horizon_days", 30)
    st.session_state.setdefault("r2_show_as", "Values")
    if wall:
        return Controls(int(st.session_state["r2_horizon_days"]), st.session_state["r2_show_as"], False, True, False)

    c1, c2, c3, c4 = st.columns([1.3, 1.8, 1.3, 1.0], vertical_alignment="bottom")
    with c1:
        st.number_input("Days ahead", 1, 730, key="r2_horizon_days", step=1, help="How far ahead the graphs look (default 30)")
    with c2:
        st.segmented_control("Show as", ["Values", "Plant"], key="r2_show_as",
                             help="Plant: Hornsea in equipment terms (comps, Vortisep, Phase 6)")
        if st.session_state.get("r2_show_as") is None:
            st.session_state["r2_show_as"] = "Values"
    with c3:
        patterns = st.toggle("Patterns", value=True, key="r2_patterns", help="Hatch the cause areas as well as colouring them")
    with c4:
        refresh = st.button("⟳ Refresh", width="stretch")
    return Controls(int(st.session_state["r2_horizon_days"]), st.session_state.get("r2_show_as") or "Values", False, patterns, refresh)
