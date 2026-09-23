"""View controls (rendered inside the page toolbar)."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass
class Controls:
    horizon_days: int
    show_as: str        # "Values" | "Plant"
    show_tables: bool = False
    patterns: bool = True   # hatching is always on
    refresh: bool = False


def init_state() -> None:
    st.session_state.setdefault("r2_horizon_days", 30)
    st.session_state.setdefault("r2_show_as", "Values")


def current() -> Controls:
    init_state()
    return Controls(int(st.session_state["r2_horizon_days"]), st.session_state.get("r2_show_as") or "Values")


def days_input() -> None:
    st.number_input("Days ahead", 1, 730, key="r2_horizon_days", step=1, label_visibility="collapsed",
                    help="How far ahead the graphs look (default 30)")


def show_as_input() -> None:
    st.segmented_control("Show as", ["Values", "Plant"], key="r2_show_as", label_visibility="collapsed",
                         help="Plant: Hornsea in equipment terms (comps, Vortisep, Phase 6)")
    if st.session_state.get("r2_show_as") is None:
        st.session_state["r2_show_as"] = "Values"
