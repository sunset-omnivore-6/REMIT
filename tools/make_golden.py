"""Generate tests/unit/golden/core_contract.json by running the ORIGINAL REMIT
1.0 functions (exec'd from app.py, wall clock frozen) on data/samples/
remit_sample.json. The contract test then holds remit2.core to this output.

Usage: python tools/make_golden.py /path/to/REMIT/app.py
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/REMIT/app.py")

sample = json.loads((ROOT / "data/samples/remit_sample.json").read_text())
NOW = pd.Timestamp(sample["now"]).tz_convert("UTC")
raw = pd.DataFrame(sample["items"])


class FrozenTimestamp(pd.Timestamp):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.tz_convert(None)


fake_pd = types.ModuleType("pandas")
fake_pd.__dict__.update(pd.__dict__)
fake_pd.Timestamp = FrozenTimestamp
sys.modules["streamlit_autorefresh"] = types.SimpleNamespace(st_autorefresh=lambda **k: None)

src = io.open(SRC, encoding="utf-8").read()
ns: dict = {"pd": fake_pd}
code = src[: src.index("# Main\n# ------")]
code = code.replace("import pandas as pd\n", "")  # keep our frozen module
# Same ISO8601 parse fix as the lifter applies (see docs/decisions.md), so the
# golden is "1.0 semantics + parse fix".
assert code.count('out[col], errors="coerce", utc=True\n') == 1
code = code.replace('out[col], errors="coerce", utc=True\n', 'out[col], errors="coerce", utc=True, format="ISO8601"\n')
exec(compile(code, "v1_app_functions", "exec"), ns)

cats = ["Withdrawal", "Injection", "Storage"]
cmap = ns["detect_columns"](raw)
df = ns["normalise"](raw, cmap)
df_op = ns["build_operational"](df, cmap, cats)
tech = ns["tech_capacity_lookup"](df_op, cats)


def ts(v):
    return None if pd.isna(v) else pd.Timestamp(v).tz_convert("UTC").isoformat()


def num(v):
    return None if pd.isna(v) else float(v)


op_records = [
    {
        "threadId": str(r["threadId"]), "site": r["__site__"], "category": r["__category__"],
        "status": r["__status__"], "planned": r["__planned__"],
        "start": ts(r["__eventStart__"]), "end": ts(r["__eventEnd__"]), "publication": ts(r["__publication__"]),
        "avail": num(r["__availCapacity__"]), "unavail": num(r["__unavailCapacity__"]), "tech": num(r["__techCapacity__"]),
        "unitUnknown": bool(r["__unitUnknown__"]),
    }
    for _, r in df_op.sort_values("threadId").iterrows()
]

grid = [NOW + pd.Timedelta(hours=h) for h in range(-48, 169, 6)]
cap_grid = {}
for site in ("Atwick", "Aldbrough"):
    for cat in ("Withdrawal", "Injection"):
        cap_grid[f"{site}/{cat}"] = [float(ns["_capacity_at"](df_op, site, cat, t, tech[(site, cat)])) for t in grid]

changes = [
    {"site": c["site"], "category": c["category"], "when": c["when"].isoformat(),
     "from": float(c["from"]), "to": float(c["to"])}
    for c in ns["compute_capacity_changes"](df_op, tech, cats, lookahead_days=7)
]
start, end = NOW - pd.Timedelta(days=4), NOW + pd.Timedelta(days=7)
series = ns["compute_capacity_series"](df_op, start, end, tech, ["Withdrawal", "Injection"])
series_records = [
    {"date": r["date"].isoformat(), "site": r["site"], "category": r["category"], "available": float(r["available"])}
    for _, r in series.iterrows()
]
recent = sorted(
    (str(it["row"]["threadId"]), it["kind"]) for it in ns["compute_recent_changes"](df, cmap, lookback_hours=24)
)

golden = {
    "source": str(SRC), "now": NOW.isoformat(), "cmap": cmap,
    "tech": {f"{k[0]}/{k[1]}": v for k, v in tech.items()},
    "operational": op_records, "grid": [t.isoformat() for t in grid], "capacity_at": cap_grid,
    "changes": changes, "series_window": [start.isoformat(), end.isoformat()], "series": series_records,
    "recent": recent,
}
out = ROOT / "tests/unit/golden/core_contract.json"
out.write_text(json.dumps(golden, indent=1), encoding="utf-8")
print(f"golden written: {len(op_records)} op rows, {len(changes)} changes, {len(series_records)} series pts, recent={recent}")
