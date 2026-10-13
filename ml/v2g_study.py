"""Vehicle-to-grid, measured across many nights rather than one.

FINDINGS.md finding 8 originally tabulated V2G on a single night. That depends on which night
it is: on the median night of the corrected record V2G changes nothing for carbon at all, because
there is no spread of clean hours to arbitrage. A fair statement needs many nights.

80 vehicles, 9.2 kWh each, 7 kW chargers, window 18:00-07:00, owner reserve 12 kWh, export cap 6 kWh
per vehicle per night or none. Every fourth served night, summed over the nights.

    python v2g_study.py        # -> artifacts/v2g_study.json
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app import data_sources as ds  # noqa: E402
from app.optimizer import Vehicle, run_scenario  # noqa: E402

OUT = HERE / "artifacts" / "v2g_study.json"
EV = 80


def fleet(v2g: bool, cap: float | None) -> list[Vehicle]:
    return [Vehicle(id=f"v{i}", energy_needed_kwh=9.2, charger_kw=7.0, arrival_hour=18, deadline_hour=7,
                    discharge_kw=7.0 if v2g else 0.0, battery_kwh=60.0, arrival_soc_kwh=25.0, reserve_kwh=12.0,
                    max_export_kwh=cap) for i in range(EV)]


def main() -> None:
    days = ds.available_days()[::4]
    base = ds.get_residential_baseline_kw(EV)
    modes = (("charge-only", False, None), ("V2G capped 6 kWh", True, 6.0), ("V2G uncapped", True, None))
    acc: dict = {}
    for d in days:
        carbon, price = ds.get_carbon_intensity(day=d), ds.get_price(day=d)
        for obj in ("emissions", "peak", "cost"):
            for label, v2g, cap in modes:
                r = run_scenario(fleet(v2g, cap), carbon, base, price=price, objective=obj, allow_v2g=v2g)
                a = acc.setdefault((obj, label), {"co2": 0.0, "cost": 0.0, "peaks": [], "exp": 0.0, "naive_co2": 0.0, "naive_cost": 0.0})
                a["co2"] += r.emissions_optimized_kg
                a["cost"] += r.cost_optimized
                a["peaks"].append(r.peak_optimized_kw)
                a["exp"] += r.exported_kwh
                a["naive_co2"] += r.emissions_naive_kg
                a["naive_cost"] += r.cost_naive
        print(f"  {d} done", flush=True)

    rows = []
    for (obj, label), a in acc.items():
        rows.append({"objective": obj, "mode": label, "co2_kg": round(a["co2"], 1), "cost_eur": round(a["cost"], 2),
                     "mean_peak_kw": round(statistics.mean(a["peaks"]), 1), "exported_kwh": round(a["exp"])})
    e0 = acc[("emissions", "charge-only")]
    out = {"nights": len(days), "vehicles": EV, "rows": rows,
           "naive_co2_kg": round(e0["naive_co2"], 1), "naive_cost_eur": round(e0["naive_cost"], 2)}
    for label in ("V2G capped 6 kWh", "V2G uncapped"):
        a = acc[("emissions", label)]
        dco2, dcost = e0["co2"] - a["co2"], a["cost"] - e0["cost"]
        out[f"abatement_eur_per_kg_{'capped' if 'capped' in label and 'un' not in label else 'uncapped'}"] = (
            round(dcost / dco2, 2) if dco2 > 1e-9 else None)
        out[f"co2_saved_kg_{'capped' if 'capped' in label and 'un' not in label else 'uncapped'}"] = round(dco2, 2)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{'objective':<10} {'mode':<18} {'CO2 kg':>8} {'cost EUR':>9} {'mean peak kW':>13} {'export kWh':>11}")
    for r in rows:
        print(f"{r['objective']:<10} {r['mode']:<18} {r['co2_kg']:>8} {r['cost_eur']:>9} {r['mean_peak_kw']:>13} {r['exported_kwh']:>11}")
    print({k: v for k, v in out.items() if k.startswith(("abatement", "co2_saved", "naive"))})
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
