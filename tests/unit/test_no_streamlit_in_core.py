"""remit2.core and remit2.adhoc must stay importable without Streamlit."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "remit2"


def test_no_streamlit_imports():
    offenders = []
    for pkg in ("core", "adhoc"):
        for p in (ROOT / pkg).rglob("*.py"):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if re.match(r"\s*(import streamlit|from streamlit)", line):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
