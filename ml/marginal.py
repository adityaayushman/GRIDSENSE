"""Marginal emissions, estimated from public generation data (no WattTime licence needed).

GridSense schedules against *average* carbon intensity: the emissions of the average kWh on the
grid. Shifting a load changes the grid's output at the margin, so the quantity that matters is the
*marginal* rate, the emissions of the next kWh. WattTime publishes that as MOER, behind a paid plan.

This estimates it from the same public data the rest of the project already uses. The method is
the standard empirical one:

    marginal rate = d(emissions of dispatchable plant) / d(residual load)

where residual load is demand minus wind and solar, which are not dispatched to follow load. It is
estimated hour by hour (first differences, so slow level effects drop out) separately for each hour
of the day and each season, because the plant on the margin differs between a windy 03:00 and a sunny
13:00.

What this is not: it is not MOER. It sees only what moved in the national totals, it cannot see
transmission constraints or plant outages, and it treats each hour of day and season as one regime.
The question it answers is narrower and still useful: would the schedule change if the project
used a marginal signal, and by how much.

    python marginal.py        # -> artifacts/marginal.json, frontend and backend data copies
"""

from __future__ import annotations

import json
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

from export_regions import DE_FACTORS  # noqa: E402
from india_carbon import FACTORS as IN_FACTORS, load_15min  # noqa: E402
from spread_gate import NAIVE, WINDOW, emis, fill  # noqa: E402
from carbon import EMISSION_FACTORS as ES_FACTORS  # noqa: E402

OUT = HERE / "artifacts" / "marginal.json"
COPIES = [HERE.parent / "frontend" / "src" / "data" / "marginal.json",
          HERE.parent / "backend" / "app" / "data" / "marginal.json"]

DISPATCHABLE_MIN_EF = 200.0          # fuels at or above this are treated as following load
MAX_EF = 1100.0                      # a marginal rate cannot exceed the dirtiest fuel
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
SEASON_ORDER = ["winter", "spring", "summer", "autumn"]


def spain() -> tuple[pd.DataFrame, str]:
    e = pd.read_csv(HERE / "data/raw/energy_dataset.csv", parse_dates=["time"], index_col="time")
    e.index = pd.to_datetime(e.index, utc=True)
    e = e[~e.index.duplicated()].sort_index()
    fuels = [c for c in ES_FACTORS if c in e.columns]
    g = e[fuels].fillna(0.0)
    disp = [c for c in fuels if ES_FACTORS[c] >= DISPATCHABLE_MIN_EF]
    d = pd.DataFrame(index=e.index)
    d["avg"] = sum(g[c] * ES_FACTORS[c] for c in fuels) / g.sum(axis=1).replace(0, np.nan)
    d["disp_g"] = sum(g[c] * ES_FACTORS[c] for c in disp) * 1e3          # MW * g/kWh -> g/h
    d["resid"] = (e["total load actual"] - e["generation wind onshore"].fillna(0)
                  - e["generation solar"].fillna(0)) * 1e3               # kWh over the hour
    return d.dropna(), "Europe/Madrid"


def germany() -> tuple[pd.DataFrame, str]:
    e = pd.read_csv(HERE / "data/de/de_lu_hourly.csv", parse_dates=["ts_utc"]).set_index("ts_utc").sort_index()
    g = e[list(DE_FACTORS)].fillna(0.0)
    disp = [c for c in DE_FACTORS if DE_FACTORS[c] >= DISPATCHABLE_MIN_EF]
    d = pd.DataFrame(index=e.index)
    d["avg"] = sum(g[c] * DE_FACTORS[c] for c in DE_FACTORS) / g.sum(axis=1).replace(0, np.nan)
    d["disp_g"] = sum(g[c] * DE_FACTORS[c] for c in disp) * 1e3
    d["resid"] = (e["load_mw"] - e["wind_onshore_mw"].fillna(0) - e["wind_offshore_mw"].fillna(0)
                  - e["solar_mw"].fillna(0)) * 1e3
    return d.dropna(), "Europe/Berlin"


def india() -> tuple[pd.DataFrame, str]:
    e = load_15min().set_index("timestamp").resample("1h").mean(numeric_only=True)
    fuels = [c for c in IN_FACTORS if c in e.columns]
    g = e[fuels].fillna(0.0)
    disp = [c for c in fuels if IN_FACTORS[c] >= DISPATCHABLE_MIN_EF]
    d = pd.DataFrame(index=e.index)
    d["avg"] = sum(g[c] * IN_FACTORS[c] for c in fuels) / g.sum(axis=1).replace(0, np.nan)
    d["disp_g"] = sum(g[c] * IN_FACTORS[c] for c in disp) * 1e3
    d["resid"] = (e["demand_met_mw"] - e["wind_mw"].fillna(0) - e["solar_mw"].fillna(0)) * 1e3
    d = d.dropna()
    d.index = pd.to_datetime(d.index).tz_localize("Asia/Kolkata").tz_convert("UTC")
    return d, "Asia/Kolkata"


BLOCK = 3   # hours pooled per estimate: a single hour of one season is too few, noisy points


def slopes(d: pd.DataFrame, tz: str, max_ef: float) -> dict:
    """Marginal rate per (season, 3-hour block): OLS of d(emissions) on d(residual load).

    Every hour in a block shares the block's estimate. The estimate is bounded above by the
    dirtiest dispatchable fuel on that grid, since no single plant can emit more per kWh than that.
    """
    loc = d.index.tz_convert(tz)
    f = pd.DataFrame({"de": d["disp_g"].diff().values, "dr": d["resid"].diff().values,
                      "h": loc.hour, "s": [SEASONS[m] for m in loc.month], "avg": d["avg"].values},
                     index=d.index)
    # Only consecutive hours: a gap in the record would turn the difference into a multi-hour one.
    gap = d.index.to_series().diff() != pd.Timedelta(hours=1)
    f = f[~gap.values].dropna()
    f = f[f["dr"].abs() > 1.0]
    table: dict = {}
    rng = np.random.default_rng(7)
    for sea in SEASON_ORDER:
        rows: list = [None] * 24
        for blk in range(24 // BLOCK):
            hours = range(blk * BLOCK, blk * BLOCK + BLOCK)
            x = f[(f.s == sea) & (f.h.isin(hours))]
            if len(x) < 60:
                est = {"marginal": None, "se": None, "r2": None}
            else:
                dr, de = x["dr"].to_numpy(), x["de"].to_numpy()
                slope, icpt = np.polyfit(dr, de, 1)
                ss_res = float(((de - (slope * dr + icpt)) ** 2).sum())
                r2 = 1 - ss_res / float(((de - de.mean()) ** 2).sum())
                boots = []
                for _ in range(150):
                    i = rng.integers(0, len(x), len(x))
                    boots.append(np.polyfit(dr[i], de[i], 1)[0])
                est = {"marginal": float(np.clip(slope, 0, max_ef)), "se": round(float(np.std(boots)), 1),
                       "r2": round(r2, 3)}
            for h in hours:
                y = f[(f.s == sea) & (f.h == h)]
                rows[h] = {"hour": h, "average": float(y["avg"].mean()) if len(y) else None,
                           "n": int(len(x)), **est}
        table[sea] = rows
    return table


def night_savings(d: pd.DataFrame, tz: str, table: dict) -> dict:
    """Schedule on one signal, score on another, over every complete night."""
    loc = d.index.tz_convert(tz)
    night = loc.normalize() - pd.to_timedelta((loc.hour < 7).astype(int), unit="D")
    f = pd.DataFrame({"a": d["avg"].values, "h": loc.hour, "n": night, "m": loc.month})
    marg = {s: [r["marginal"] for r in table[s]] for s in SEASON_ORDER}
    out = {"avg_on_avg": [], "avg_on_marg": [], "marg_on_marg": [], "marg_on_avg": []}
    for n, g in f.groupby("n"):
        by = g.groupby("h")["a"].mean()
        if not set(WINDOW) <= set(by.index):
            continue
        avg = [float(by.get(h, by.mean())) for h in range(24)]
        m = marg[SEASONS[int(g["m"].iloc[len(g) // 2])]]
        if any(m[h] is None for h in WINDOW):
            continue
        mc = [float(v) if v is not None else 0.0 for v in m]
        s_avg, s_marg = fill(avg), fill(mc)

        def cut(sched: list[float], curve: list[float]) -> float:
            base = emis(NAIVE, curve)
            return (1 - emis(sched, curve) / base) * 100 if base else 0.0
        out["avg_on_avg"].append(cut(s_avg, avg))
        out["avg_on_marg"].append(cut(s_avg, mc))
        out["marg_on_marg"].append(cut(s_marg, mc))
        out["marg_on_avg"].append(cut(s_marg, avg))
    return out


def summarise(vals: list[float]) -> dict:
    return {"median": round(statistics.median(vals), 2), "mean": round(statistics.mean(vals), 2),
            "under_1pct": round(sum(v < 1 for v in vals) / len(vals) * 100, 1)}


def build_grid(name: str, builder, region: str, max_ef: float) -> dict:
    d, tz = builder()
    table = slopes(d, tz, max_ef)
    nights = night_savings(d, tz, table)
    win_m = [r["marginal"] for s in SEASON_ORDER for r in table[s] if r["hour"] in WINDOW and r["marginal"] is not None]
    win_a = [r["average"] for s in SEASON_ORDER for r in table[s] if r["hour"] in WINDOW and r["average"] is not None]
    # Correlation between the two signals across the hour-by-season grid, overnight window.
    pairs = [(r["average"], r["marginal"]) for s in SEASON_ORDER for r in table[s]
             if r["hour"] in WINDOW and r["marginal"] is not None]
    corr = float(np.corrcoef([p[0] for p in pairs], [p[1] for p in pairs])[0, 1]) if len(pairs) > 3 else None
    night_r2 = [r["r2"] for sea in SEASON_ORDER for r in table[sea] if r["hour"] in WINDOW and r["r2"] is not None]
    return {
        "grid": name, "median_r2_overnight": round(statistics.median(night_r2), 2) if night_r2 else None, "region": region, "nights": len(nights["avg_on_avg"]), "hours": int(len(d)),
        "mean_average": round(float(statistics.mean(win_a)), 1),
        "mean_marginal": round(float(statistics.mean(win_m)), 1),
        "overnight_correlation": round(corr, 2) if corr is not None else None,
        "table": table,
        "savings": {k: summarise(v) for k, v in nights.items() if k != "marg_on_marg"},
    }


def main() -> None:
    grids = [build_grid("Spain", spain, "ES", 1054.0), build_grid("Germany", germany, "DE", 1054.0),
             build_grid("India", india, "IN", 820.0)]
    out = {
        "note": "Generated by ml/marginal.py - do not edit by hand.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "d(dispatchable emissions)/d(residual load) per season and hour of day, "
                  "first differences, OLS, clipped to [0, 1100] g/kWh. A proxy for MOER, not MOER.",
        "grids": grids,
    }
    text = json.dumps(out, indent=1)
    for p in [OUT, *COPIES]:
        p.write_text(text, encoding="utf-8")
    for g in grids:
        s = g["savings"]
        print(f"{g['grid']:<8} nights {g['nights']:>5} · overnight mean avg {g['mean_average']:>6} marg {g['mean_marginal']:>6} "
              f"· corr {g['overnight_correlation']} · median R2 {g['median_r2_overnight']}")
        print(f"   schedule on avg, scored on avg  : median {s['avg_on_avg']['median']:>5}%  under1% {s['avg_on_avg']['under_1pct']}%")
        print(f"   schedule on avg, scored on marg : median {s['avg_on_marg']['median']:>5}%  under1% {s['avg_on_marg']['under_1pct']}%")
        print(f"   schedule on marg, scored on avg : median {s['marg_on_avg']['median']:>5}%  under1% {s['marg_on_avg']['under_1pct']}%")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
