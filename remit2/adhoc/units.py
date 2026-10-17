"""Units per direction: rates are GWh/d, storage (working gas capacity) is TWh.

Equipment values and record fields keep their historical `*_gwhd` names; for
the Storage direction they hold TWh. Pure — no Streamlit."""
from __future__ import annotations

from ..core.constants import DEFAULT_UNIT


def unit_of(direction: str) -> str:
    return DEFAULT_UNIT.get(direction, "GWh/d")


def decimals(direction: str) -> int:
    """Storage levels (≈ 3 TWh, caverns ≈ 0.4 TWh) need two decimals; rates one."""
    return 2 if direction == "Storage" else 1


def q(v: float, direction: str) -> str:
    """A level or amount at display precision: '22.5' / '2.75'."""
    return f"{float(v):.{decimals(direction)}f}"


def amount(v: float, direction: str) -> str:
    """A configured unit value: '7.5' / '30' for rates, '0.43' for caverns."""
    return q(v, direction) if direction == "Storage" else f"{float(v):g}"
