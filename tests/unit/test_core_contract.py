"""Lift guard: remit2.core must reproduce REMIT 1.0's outputs on the sample.
Golden produced by tools/make_golden.py from the original app.py."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from remit2.core.capacity import capacity_at, compute_capacity_changes, compute_capacity_series, compute_recent_changes
from remit2.core.normalise import detect_columns, normalise
from remit2.core.operational import build_operational, tech_capacity_lookup

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests/unit/golden/core_contract.json").read_text())
SAMPLE = json.loads((ROOT / "data/samples/remit_sample.json").read_text())
NOW = pd.Timestamp(GOLDEN["now"])
CATS = ["Withdrawal", "Injection", "Storage"]


@pytest.fixture(scope="module")
def pipeline():
    raw = pd.DataFrame(SAMPLE["items"])
    cmap = detect_columns(raw)
    df = normalise(raw, cmap)
    df_op = build_operational(df, cmap, CATS)
    tech = tech_capacity_lookup(df_op, CATS)
    return raw, cmap, df, df_op, tech


def _ts(v):
    return None if pd.isna(v) else pd.Timestamp(v).tz_convert("UTC").isoformat()


def _num(v):
    return None if pd.isna(v) else float(v)


def test_column_detection(pipeline):
    assert pipeline[1] == GOLDEN["cmap"]


def test_operational_rows_identical(pipeline):
    _, _, _, df_op, _ = pipeline
    got = [
        {"threadId": str(r["threadId"]), "site": r["__site__"], "category": r["__category__"],
         "status": r["__status__"], "planned": r["__planned__"],
         "start": _ts(r["__eventStart__"]), "end": _ts(r["__eventEnd__"]), "publication": _ts(r["__publication__"]),
         "avail": _num(r["__availCapacity__"]), "unavail": _num(r["__unavailCapacity__"]), "tech": _num(r["__techCapacity__"]),
         "unitUnknown": bool(r["__unitUnknown__"])}
        for _, r in df_op.sort_values("threadId").iterrows()
    ]
    assert got == GOLDEN["operational"]


def test_tech_lookup(pipeline):
    assert {f"{k[0]}/{k[1]}": v for k, v in pipeline[4].items()} == GOLDEN["tech"]


def test_capacity_at_grid(pipeline):
    _, _, _, df_op, tech = pipeline
    grid = [pd.Timestamp(t) for t in GOLDEN["grid"]]
    for key, expected in GOLDEN["capacity_at"].items():
        site, cat = key.split("/")
        got = [float(capacity_at(df_op, site, cat, t, tech[(site, cat)])) for t in grid]
        assert got == pytest.approx(expected), key


def test_capacity_changes(pipeline):
    _, _, _, df_op, tech = pipeline
    got = [{"site": c["site"], "category": c["category"], "when": c["when"].isoformat(),
            "from": float(c["from"]), "to": float(c["to"])}
           for c in compute_capacity_changes(df_op, tech, CATS, lookahead_days=7, now=NOW)]
    assert got == GOLDEN["changes"]


def test_capacity_series(pipeline):
    _, _, _, df_op, tech = pipeline
    start, end = (pd.Timestamp(s) for s in GOLDEN["series_window"])
    series = compute_capacity_series(df_op, start, end, tech, ["Withdrawal", "Injection"])
    got = [{"date": r["date"].isoformat(), "site": r["site"], "category": r["category"], "available": float(r["available"])}
           for _, r in series.iterrows()]
    assert got == GOLDEN["series"]


def test_recent_changes_kinds(pipeline):
    _, cmap, df, _, _ = pipeline
    got = sorted((str(it["row"]["threadId"]), it["kind"]) for it in compute_recent_changes(df, cmap, lookback_hours=24, now=NOW))
    assert got == [tuple(x) for x in GOLDEN["recent"]]


def test_now_is_required():
    with pytest.raises(ValueError):
        compute_capacity_changes(pd.DataFrame(), {}, CATS)
