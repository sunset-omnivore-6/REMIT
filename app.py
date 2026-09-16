"""REMIT 2.0 entry point — everything else lives in remit2/."""
import streamlit as st

from remit2.ui import page

st.set_page_config(page_title="REMIT 2.0 — Hornsea & Aldbrough", layout="wide", initial_sidebar_state="collapsed")
page.render()
