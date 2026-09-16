# REMIT 2.0 — Hornsea & Aldbrough availability

A UI- and accessibility-first Streamlit app showing available gas-storage
capacity (withdrawal / injection) at SSE's Hornsea (Atwick) and Aldbrough
sites over the foreseeable future, built from published REMIT/UoF notices
**plus sub-threshold "ad-hoc" plant adjustments** entered in-app.

- `remit2/core/` — the data layer lifted verbatim from REMIT 1.0 (`tools/lift_from_v1.py`), no Streamlit.
- `remit2/adhoc/` — ad-hoc model, register, combine rule, threshold check, text narration.
- `remit2/ui/` — the only Streamlit layer: theme, cached data, controls, hero cards, page.
- `config/equipment.default.json` — nameplates, unit values, quarterly REMIT thresholds.

## Run locally

```bash
pip install -r requirements-dev.txt
REMIT2_FIXTURE=data/samples/remit_sample.json streamlit run app.py    # synthetic data
streamlit run app.py                                                   # live SSE feed
```

Query `?mode=wall` gives a chrome-free wall-display layout.

## Tests

```bash
python -m pytest tests/unit -q                       # core contract, combine goldens, equipment
PLAYWRIGHT_CHROMIUM=/opt/pw-browsers/chromium python -m pytest tests/e2e -q
```

See `docs/decisions.md` for the design decisions and the plan.
