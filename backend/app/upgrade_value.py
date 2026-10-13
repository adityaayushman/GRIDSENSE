"""The rupee value of the transformer upgrade that coordinated charging avoids.

For a neighbourhood with N electric vehicles on one distribution transformer, find the smallest
standard rating that hosts N when cars charge on arrival, and the smallest that hosts N when they
are coordinated. The difference in what those two transformers cost is the upgrade avoided.

This is an estimate with its inputs showing, not a finding. Two things limit it:

  * Hosting counts come from the modelled Indian fleet (`ml/export_india_capacity.py`): arrival
    times and energy per vehicle are assumed, 150 homes share the transformer.
  * Prices are vendor asking prices for the equipment (`ml/export_upgrade_inputs.py` lists them).
    No official schedule of rates was found. Installation is a multiplier you set.

When both methods need the same standard rating the answer is zero: coordination only saves money
when it moves the neighbourhood across a rating boundary. The result says so rather than quoting a
per-vehicle average that hides it.

The dashboard re-implements `avoided_upgrade` from the same data file, so the sliders respond
instantly; `tests/test_upgrade_value.py` pins the cases both must agree on.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "upgrade_inputs.json"
CASES = ("low", "base", "high")


@lru_cache(maxsize=1)
def inputs() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _loglog(kva: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Price at `kva` on the straight line through two (kVA, price) points in log-log space."""
    slope = (math.log(b[1]) - math.log(a[1])) / (math.log(b[0]) - math.log(a[0]))
    return math.exp(math.log(a[1]) + slope * (math.log(kva) - math.log(a[0])))


def equipment_price(kva: int, case: str) -> float:
    """Rupees for the transformer itself. `base` is the midpoint of the low and high prices."""
    if case == "base":
        return (equipment_price(kva, "low") + equipment_price(kva, "high")) / 2
    anchors = sorted(inputs()["price_anchors"].items(), key=lambda kv: int(kv[0]))
    a, b = ((float(k), float(v[case])) for k, v in anchors[:2])
    return _loglog(kva, a, b)


def extrapolated(kva: int) -> bool:
    keys = sorted(int(k) for k in inputs()["price_anchors"])
    return kva < keys[0] or kva > keys[-1]


def required_rating(evs: int, method: str) -> int | None:
    """Smallest standard rating (kVA) that hosts `evs`, or None if even the largest cannot."""
    for r in sorted(inputs()["ratings"], key=lambda r: r["rating_kva"]):
        if r[method] >= evs:
            return int(r["rating_kva"])
    return None


def avoided_upgrade(evs: int, installed_multiplier: float | None = None) -> dict:
    if evs < 1:
        raise ValueError("evs must be at least 1")
    mult = inputs()["default_install_multiplier"] if installed_multiplier is None else installed_multiplier
    if not 1.0 <= mult <= 4.0:
        raise ValueError("installed_multiplier must be between 1 and 4")

    dumb, coord = required_rating(evs, "dumb"), required_rating(evs, "coordinated")
    out: dict = {
        "evs": evs, "installed_multiplier": mult, "currency": "INR",
        "rating_on_arrival_kva": dumb, "rating_coordinated_kva": coord,
        "homes_per_transformer": inputs()["homes_per_transformer"],
        "price_source": inputs()["price_source_note"],
        "caveats": [
            "Hosting counts come from a modelled fleet, not measured sessions.",
            "Prices are vendor asking prices for equipment; installation is the multiplier you set.",
        ],
    }
    if coord is None:
        top = max(r["rating_kva"] for r in inputs()["ratings"])
        out.update(status="beyond_range",
                   note=f"{evs} EVs exceed the largest rating modelled ({top} kVA) even when coordinated.")
        return out
    if dumb is None:
        out.update(status="on_arrival_infeasible",
                   note="Charging on arrival needs more than the largest rating modelled; "
                        "the avoided cost cannot be priced from this table.")
        out["cost_inr"] = {"coordinated": {c: round(equipment_price(coord, c) * mult) for c in CASES}}
        return out

    cost = {m: {c: round(equipment_price(k, c) * mult) for c in CASES}
            for m, k in (("on_arrival", dumb), ("coordinated", coord))}
    saved = {c: cost["on_arrival"][c] - cost["coordinated"][c] for c in CASES}
    out.update(
        status="saved" if dumb != coord else "same_rating",
        cost_inr=cost, avoided_inr=saved,
        avoided_per_ev_inr={c: round(saved[c] / evs) for c in CASES},
        extrapolated_prices=sorted({k for k in (dumb, coord) if extrapolated(k)}),
        note=("Coordination avoids a larger transformer." if dumb != coord else
              "Both methods fit the same standard rating, so coordination avoids no upgrade at this size."),
    )
    return out


def staircase(installed_multiplier: float | None = None) -> list[dict]:
    """Avoided base-case rupees at every tenth EV count, for plotting where the steps fall."""
    hi = max(r["coordinated"] for r in inputs()["ratings"])
    rows = []
    for n in range(10, hi + 1, 10):
        r = avoided_upgrade(n, installed_multiplier)
        rows.append({"evs": n, "avoided_base_inr": r.get("avoided_inr", {}).get("base"), "status": r["status"]})
    return rows
