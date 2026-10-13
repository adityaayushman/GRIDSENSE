"""One file of results for the Results view and the README figures.

Every chart on the Results view and every PNG in docs/figures reads this file, and
this file reads the analyses' own artifacts, so a number cannot be typed into a chart.
Re-run it after any analysis changes:

    python export_results.py        # -> frontend/src/data/results.json

What it gathers
---------------
  savings      what overnight carbon-aware charging is worth on five grids, as the share
               of nights in each saving band, plus median and fleet-total saving. The
               Spanish record is the corrected one (finding 17). Each grid is scored the
               same way: identical vehicles, window 18:00-07:00, greedy fill (equal to
               the LP when no constraint couples vehicles, finding 4), except India,
               which uses the Indian fleet mix and is checked against finding 12.
  hosting      the 250 kW gain across twenty fleet draws, and the range at each rating.
  sensitivity  one-at-a-time moves of the assumed inputs against the noise band.
  forecast     share of the achievable saving a day-ahead forecast captures, by grid.
  control      rolling-horizon regret against the one-shot plan.
  india        the three charging windows.
  corrections  every published number that changed, with what it was and what it is.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE.parent / "backend"))

from carbon import carbon_intensity  # noqa: E402
from export_regions import germany  # noqa: E402
from india_fleet import indian_fleet  # noqa: E402
from india_carbon import hourly as india_hourly  # noqa: E402
from spread_gate import ENERGY_KWH, CHARGER_KW, NAIVE, emis, fill  # noqa: E402

ART = HERE / "artifacts"
DATA = HERE.parent / "frontend" / "src" / "data"
OUT = DATA / "results.json"
WINDOW = [h % 24 for h in range(18, 18 + 13)]
BANDS = [("lt1", "under 1%", None, 1), ("b1_5", "1-5%", 1, 5), ("b5_20", "5-20%", 5, 20), ("gt20", "over 20%", 20, None)]


# ----------------------------------------------------------------- savings
def nights(ci: pd.Series, tz: str | None, window: list[int], deadline: int) -> list[list[float]]:
    idx = ci.index.tz_convert(tz) if (tz and ci.index.tz is not None) else ci.index
    h = idx.hour
    night = idx.normalize() - pd.to_timedelta((h < deadline).astype(int), unit="D") if deadline < window[0] else idx.normalize()
    f = pd.DataFrame({"ci": ci.values, "h": h, "n": night})
    out = []
    for _, g in f.groupby("n"):
        by = g.groupby("h")["ci"].mean()
        if set(window) <= set(by.index) and not by.loc[window].isna().any():
            out.append([float(by.get(x, by.mean())) for x in range(24)])
    return out


def summarise(label: str, source: str, savings: list[float], e_naive: float, e_opt: float, note: str = "") -> dict:
    n = len(savings)
    bands = {}
    for key, _, lo, hi in BANDS:
        bands[key] = round(sum(1 for s in savings if (lo is None or s >= lo) and (hi is None or s < hi)) / n * 100, 1)
    # Rounded shares can sum to 100.1; give the difference to the largest band so a stacked
    # bar closes exactly at 100% and the axis never reads 100.1%.
    drift = round(100.0 - sum(bands.values()), 1)
    if drift:
        bands[max(bands, key=bands.get)] = round(bands[max(bands, key=bands.get)] + drift, 1)
    return {"label": label, "source": source, "nights": n, "median_pct": round(statistics.median(savings), 2),
            "mean_pct": round(statistics.mean(savings), 2), "fleet_pct": round((1 - e_opt / e_naive) * 100, 2),
            "bands": bands, "note": note}


def identical_fleet_savings(curves: list[list[float]]) -> tuple[list[float], float, float]:
    sv, en, eo = [], 0.0, 0.0
    for c in curves:
        a, b = emis(NAIVE, c), emis(fill(c), c)
        if a > 0:
            sv.append((1 - b / a) * 100)
            en += a
            eo += b
    return sv, en, eo


def indian_savings(ci: pd.Series, arrival: int, deadline: int) -> tuple[list[float], float, float]:
    """Per-vehicle greedy over the Indian fleet mix: the LP optimum without a coupling constraint.

    Vehicles keep their own staggered arrival windows, and an overnight window is
    stitched (evening of day D, morning of D+1), exactly as india_backtest.py does.
    """
    from app.optimizer import _available_hours

    fleet = indian_fleet(100, arrival=arrival, deadline=deadline)
    by = pd.DataFrame({"ci": ci.values, "h": ci.index.hour, "d": ci.index.normalize()})
    tables = {k: g.groupby("h")["ci"].mean() for k, g in by.groupby("d")}
    days = sorted(tables)
    curves = []
    for i, day in enumerate(days):
        m = tables[day]
        if not set(range(24)) <= set(m.index):
            continue
        if deadline < arrival:
            if i + 1 >= len(days) or (days[i + 1] - day).days != 1 or not set(range(24)) <= set(tables[days[i + 1]].index):
                continue
            n = tables[days[i + 1]]
            curves.append([float(n[x]) if x < deadline else float(m[x]) for x in range(24)])
        else:
            curves.append([float(m[x]) for x in range(24)])
    sv, en_t, eo_t = [], 0.0, 0.0
    for curve in curves:
        en = eo = 0.0
        for v in fleet:
            hrs = _available_hours(v)
            need = v.energy_needed_kwh
            for h in hrs:                                   # on arrival
                take = min(v.charger_kw, need)
                en += take * curve[h]
                need -= take
                if need <= 1e-12:
                    break
            need = v.energy_needed_kwh
            for h in sorted(hrs, key=lambda x: curve[x]):   # cleanest first
                take = min(v.charger_kw, need)
                eo += take * curve[h]
                need -= take
                if need <= 1e-12:
                    break
        if en > 0:
            sv.append((1 - eo / en) * 100)
            en_t += en
            eo_t += eo
    return sv, en_t, eo_t


def build_savings() -> list[dict]:
    out = []
    # Spain 2015-2018 on the corrected record
    k = pd.read_csv(HERE / "data/raw/energy_dataset.csv", parse_dates=["time"], index_col="time")
    k.index = pd.to_datetime(k.index, utc=True)
    k = k[~k.index.duplicated()]
    sv, en, eo = identical_fleet_savings(nights(carbon_intensity(k).dropna(), "Europe/Madrid", WINDOW, 7))
    out.append({"id": "es1518", **summarise("Spain 2015-18", "ENTSO-E via Energy-Charts, corrected (finding 17)", sv, en, eo)})
    # Spain 2025
    e = pd.read_csv(HERE / "data/es-ec/spain_hourly.csv", index_col=0, parse_dates=True)
    e.index = pd.to_datetime(e.index, utc=True)
    ci25 = e["ci"].dropna()
    ci25 = ci25[ci25.index.year == 2025]
    sv, en, eo = identical_fleet_savings(nights(ci25, "Europe/Madrid", WINDOW, 7))
    out.append({"id": "es2025", **summarise("Spain 2025", "ENTSO-E via Energy-Charts", sv, en, eo)})
    # Germany
    sv, en, eo = identical_fleet_savings(nights(germany(), "Europe/Berlin", WINDOW, 7))
    out.append({"id": "de", **summarise("Germany 2023-26", "ENTSO-E DE-LU", sv, en, eo)})
    # India, two windows, Indian fleet
    h = india_hourly()
    ci = h.set_index("timestamp")["ci"]
    for wid, label, a, d in (("in_night", "India overnight 18-07", 18, 7), ("in_day", "India daytime 09-17", 9, 17)):
        sv, en, eo = indian_savings(ci, a, d)
        out.append({"id": wid, **summarise(label, "Grid-India Daily PSP, 15-minute", sv, en, eo,
                                           "Indian fleet mix: scooters, rickshaws, cars")})
    # Guard: the independent computation must agree with the published India figures.
    ic = json.loads((DATA / "india_carbon.json").read_text(encoding="utf-8"))["windows"]
    for wid, key in (("in_night", "overnight"), ("in_day", "daytime")):
        got = next(x for x in out if x["id"] == wid)["median_pct"]
        if abs(got - ic[key]["median_cut_pct"]) > 0.06:
            raise RuntimeError(f"{wid}: greedy median {got} disagrees with the LP backtest {ic[key]['median_cut_pct']}")
    return out


# ----------------------------------------------------------------- the rest
def build_hosting() -> dict:
    seeds = json.loads((ART / "hosting_seeds.json").read_text(encoding="utf-8"))
    draws = sorted(({"seed": int(k.split(":")[1]), "dumb": v["dumb"], "coordinated": v["coordinated"],
                     "gain": round(v["coordinated"] / max(v["dumb"], 1), 2)} for k, v in seeds.items() if k.startswith("250:")),
                   key=lambda r: r["seed"])
    h = json.loads((DATA / "hosting.json").read_text(encoding="utf-8"))
    return {"rating_kw": 250, "draws": draws, "median": h["headline"]["gain"], "published_first_draw": draws[0]["gain"],
            "ratings": [{k: r[k] for k in ("rating_kw", "dumb", "coordinated", "gain", "gain_min", "gain_max", "seeds")}
                        for r in h["realistic"]]}


def build_sensitivity(hosting: dict) -> dict:
    rows = json.loads((ART / "sensitivity_hosting.json").read_text(encoding="utf-8"))["rows"]
    gains = [d["gain"] for d in hosting["draws"]]
    lo, hi = min(gains), max(gains)
    # "Beyond the noise band" means clearly beyond: a quarter of a point past either edge, so a
    # move of 0.1 is not presented as an effect.
    out = []
    for r in rows.values():
        if r["group"] in ("base", "noise"):
            continue
        out.append({"name": r["name"], "group": r["group"], "what": r["what"], "gain": r["gain_fine"],
                    "outside_band": bool(r["gain_fine"] < lo - 0.25 or r["gain_fine"] > hi + 0.25)})
    return {"band": [lo, hi], "median": statistics.median(gains), "rows": sorted(out, key=lambda r: r["gain"])}


def build_forecast() -> dict:
    mm = json.loads((ART / "modern_forecaster_metrics.json").read_text(encoding="utf-8"))
    sg = json.loads((ART / "spread_gate.json").read_text(encoding="utf-8"))
    grids = {g["grid"]: g for g in sg["grids"]}

    def gate_row(name):
        g = grids[name]
        sweep = {s["tau"]: s for s in g["sweep_saving_gate"]}
        o = g["out_of_sample"]["saving_gate"]
        return {"oracle_total_pct": g["oracle_total_saving_pct"],
                "ungated_captured_pct": sweep[0]["captured_of_oracle_pct"], "ungated_worse_pct": sweep[0]["worse_share_pct"],
                "gated_tau": o["tau_chosen_on_first_half"], "gated_worse_out_of_sample_pct": o["gated"]["worse_share_pct"],
                "ungated_worse_out_of_sample_pct": o["ungated"]["worse_share_pct"]}

    return {
        "es2018": {"lags_only": mm["A_replication"]["without_tso"]["captured_pct"],
                   "with_day_ahead": mm["A_replication"]["with_tso"]["captured_pct"]},
        "es2025": {"lags_only": mm["B_value_of_forecasts"]["lags_only"]["captured_pct"],
                   "with_day_ahead": mm["B_value_of_forecasts"]["with_tso"]["captured_pct"],
                   "deployed": mm["D_deployed"]["captured_pct"], "oracle_pct": mm["D_deployed"]["oracle_saving_pct"],
                   "deployed_worse": mm["D_deployed"]["worse_nights_pct"], "deployed_gated_worse": mm["D_deployed"]["gated_worse_pct"]},
        "gate": {name: gate_row(name) for name in ("Spain", "Germany", "India")},
    }


def build_control() -> dict:
    m = json.loads((DATA / "mpc.json").read_text(encoding="utf-8"))
    s = m["strategies"]
    pen = m["deferral_penalty"]["results"]
    return {"nights": m["nights"], "regret": {k: s[k]["mean_regret_pct"] for k in ("oneshot", "mpc", "mpc_static")},
            "penalty": {k: v["mean_regret_pct"] for k, v in pen.items()}, "oneshot": m["deferral_penalty"]["oneshot_regret_pct"]}


def build_india() -> dict:
    c = json.loads((DATA / "india_carbon.json").read_text(encoding="utf-8"))
    return {"days": c["days"], "mean_ci": c["mean_ci"], "windows": c["windows"], "diurnal": c["diurnal"]}


def corrections_count() -> int:
    """Rows of the LESSONS.md table: one per published claim that turned out wrong."""
    text = (HERE.parent / "LESSONS.md").read_text(encoding="utf-8")
    return len(re.findall(r"^\| \d+ \|", text, re.M))


def main() -> None:
    savings = build_savings()
    hosting = build_hosting()
    out = {
        "note": "Generated by ml/export_results.py - do not edit by hand.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corrections_count": corrections_count(),
        "savings": savings,
        "hosting": hosting,
        "sensitivity": build_sensitivity(hosting),
        "forecast": build_forecast(),
        "control": build_control(),
        "india": build_india(),
    }
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{'grid':<24} {'nights':>6} {'median':>7} {'fleet':>7} {'<1%':>6} {'1-5':>6} {'5-20':>6} {'>20':>6}")
    for s in savings:
        b = s["bands"]
        print(f"{s['label']:<24} {s['nights']:>6} {s['median_pct']:>6}% {s['fleet_pct']:>6}% {b['lt1']:>5}% {b['b1_5']:>5}% {b['b5_20']:>5}% {b['gt20']:>5}%")
    print(f"hosting 250 kW: median {hosting['median']}x over {len(hosting['draws'])} draws; first draw {hosting['published_first_draw']}x")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
