import io

import pandas as pd
import requests
import streamlit as st

URL = "https://thermaloutages.sse.com/gas-uof"
SITES = ("Atwick", "Aldbrough")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

st.set_page_config(page_title="REMIT — Atwick & Aldbrough", layout="wide")
st.title("REMIT — Atwick & Aldbrough gas storage")
st.caption(f"Source: {URL}")


@st.cache_data(ttl=300)
def fetch_remit() -> pd.DataFrame:
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    if not tables:
        return pd.DataFrame()
    # Pick the widest table — REMIT pages typically render one main grid.
    df = max(tables, key=lambda t: t.shape[1] * t.shape[0])
    df.columns = [str(c).strip() for c in df.columns]
    return df


def filter_sites(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = pd.Series(False, index=df.index)
    for col in df.columns:
        col_str = df[col].astype(str)
        mask |= col_str.str.contains("|".join(SITES), case=False, na=False)
    return df[mask].reset_index(drop=True)


try:
    raw = fetch_remit()
except Exception as exc:
    st.error(f"Failed to fetch {URL}: {exc}")
    st.stop()

if raw.empty:
    st.warning("No tables found on the page.")
    st.stop()

filtered = filter_sites(raw)

st.subheader(f"Rows matching {' / '.join(SITES)} ({len(filtered)})")
st.dataframe(filtered, use_container_width=True)

with st.expander("Full REMIT table (all sites)"):
    st.dataframe(raw, use_container_width=True)
