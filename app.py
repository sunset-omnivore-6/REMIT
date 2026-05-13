import pandas as pd
import requests
import streamlit as st

API_URL = "https://thermaloutages.sse.com/api/v1/outages/gasuof"
SITES = ("Atwick", "Aldbrough")
PAGE_SIZE = 100
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://thermaloutages.sse.com/gas-uof",
}

st.set_page_config(page_title="REMIT — Atwick & Aldbrough", layout="wide")
st.title("REMIT — Atwick & Aldbrough gas storage")
st.caption(f"Source: {API_URL}")


@st.cache_data(ttl=300)
def fetch_remit() -> pd.DataFrame:
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "pageNumber": page,
            "pageSize": PAGE_SIZE,
            "sortDirection": "DESC",
            "sortBy": "PublicationDateTime",
            "revisionsReturned": "Latest",
            "outageDateMatch": "CONTAINED",
        }
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        # The endpoint may return either a bare list or a paged envelope
        # like {"items": [...], "totalCount": N} — handle both.
        if isinstance(payload, dict):
            items = (
                payload.get("items")
                or payload.get("data")
                or payload.get("results")
                or []
            )
            total = payload.get("totalCount") or payload.get("total")
        else:
            items = payload
            total = None

        if not items:
            break
        rows.extend(items)

        if total is not None and len(rows) >= total:
            break
        if len(items) < PAGE_SIZE:
            break
        page += 1
        if page > 100:  # hard safety cap
            break

    return pd.json_normalize(rows)


def filter_sites(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = pd.Series(False, index=df.index)
    pattern = "|".join(SITES)
    for col in df.columns:
        mask |= df[col].astype(str).str.contains(pattern, case=False, na=False)
    return df[mask].reset_index(drop=True)


try:
    raw = fetch_remit()
except Exception as exc:
    st.error(f"Failed to fetch {API_URL}: {exc}")
    st.stop()

if raw.empty:
    st.warning("API returned no records.")
    st.stop()

filtered = filter_sites(raw)

st.subheader(f"Rows for {' / '.join(SITES)} ({len(filtered)} of {len(raw)})")
st.dataframe(filtered, use_container_width=True)

with st.expander("Raw API columns"):
    st.write(list(raw.columns))
