"""Marginal-emissions proxy, served from the table `ml/marginal.py` estimates.

NOT MOER. It is the empirical slope of dispatchable emissions against residual load, per season and
3-hour block, from public generation data. See `ml/marginal.py` for the method and its limits, and
`median_r2_overnight` for how well it fits on each grid.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "marginal.json"
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
REGIONS = {"ES": "Spain", "DE": "Germany", "IN": "India"}


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def grid(region: str) -> dict:
    name = REGIONS.get(region.upper())
    if name is None:
        raise ValueError(f"no marginal estimate for region {region!r}; have {sorted(REGIONS)}")
    return next(g for g in _data()["grids"] if g["grid"] == name)


def season_of(day: str) -> str:
    return SEASONS[int(day[5:7])]


def curve(region: str, day: str) -> list[float]:
    """Marginal rate for each hour 0-23 of the season `day` falls in, gCO2eq/kWh.

    Hours with no usable estimate fall back to that hour's average intensity, so the curve is
    always complete.
    """
    rows = grid(region)["table"][season_of(day)]
    return [float(r["marginal"] if r["marginal"] is not None else (r["average"] or 0.0)) for r in rows]


def summary() -> dict:
    d = _data()
    return {
        "method": d["method"], "generated_at": d["generated_at"],
        "grids": [{k: v for k, v in g.items() if k != "table"} for g in d["grids"]],
    }
