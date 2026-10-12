"""Merge every Indian grid source into one hourly master table.

India's data is scattered across sources that each cover a different slice of
time and resolution. None is enough alone; together they are the largest
consistent Indian grid record this project can assemble from free public data.

    source                                   resolution   span                       used for
    ---------------------------------------  -----------  -------------------------  -------------------------
    Grid-India Daily PSP report (TimeSeries) 15 min       2025-04 .. today           fuel mix, demand, frequency
    Grid-India hourly demand (Kaggle)        hourly       2019-01 .. 2024-04         national + 5 regional demand
    CEA Daily Generation Report              daily        2018-04 .. 2026-08         fuel-mix carbon intensity
    POSOCO/Grid-India daily (robbieandrew)   daily        2013-01 .. 2026-08         demand, energy, region, state
    Open-Meteo ERA5 reanalysis               hourly       2018-04 .. a week ago      13-city weather
    Python `holidays` (India)                daily        any                        public-holiday flag

The master index is hourly **IST** (Asia/Kolkata, no DST), 2018-04-01 onward.
Daily sources are repeated across the hours of their day and prefixed `d_`, so a
reader never mistakes a daily figure for an hourly one. Every source has a
`has_*` flag, so a model can tell "measured" from "not available" instead of
reading a NaN as a value.

What it does NOT contain, stated plainly:

  * **Hourly fuel mix before April 2025.** Grid-India published the 15-minute
    fuel split only from then; before it, the fuel mix exists daily (CEA) and
    demand exists hourly (Kaggle), but there is no hourly carbon intensity.
  * **Hourly demand from May 2024 to March 2025** - the Kaggle series ends and
    the PSP series has not started. 11 months, left empty rather than invented.
  * **Prices.** The Indian day-ahead market (IEX) publishes no free bulk history.

Weather is converted from UTC to IST by time interpolation (IST is UTC+5:30, so
the two hourly grids are half an hour apart).

    python build_india_dataset.py

Writes data/india-big/india_master_hourly.csv and artifacts/india_master_summary.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

BIG = HERE / "data" / "india-big"
GRID = HERE / "data" / "india-grid"
OUT = BIG / "india_master_hourly.csv"
SUMMARY = HERE / "artifacts" / "india_master_summary.json"
START = "2018-04-01"

# gCO2eq/kWh, IPCC AR5 lifecycle - the same set src/carbon.py and india_carbon.py use.
PSP_FACTORS = {"nuclear_mw": 12.0, "wind_mw": 11.0, "solar_mw": 45.0, "hydro_mw": 24.0,
               "gas_mw": 490.0, "thermal_mw": 820.0, "others_mw": 700.0}
# CEA Daily Generation Report columns, GWh/day.
CEA_FACTORS = {"CEA.DGR.COL": 820.0, "CEA.DGR.LIG": 1054.0, "CEA.DGR.GAS": 490.0,
               "CEA.DGR.DIE": 650.0, "CEA.DGR.HSO": 650.0, "CEA.DGR.NAP": 650.0,
               "CEA.DGR.MFU": 650.0, "CEA.DGR.NUC": 12.0, "CEA.DGR.HYD": 24.0,
               "CEA.DGR.BHU": 24.0, "CEA.DGR.WND": 11.0, "CEA.DGR.SOL": 45.0,
               "CEA.DGR.OTH": 100.0}
REGIONS = ["NR", "WR", "SR", "ER", "NER"]
POSOCO_REGION_FIELDS = ["DemandMet", "MaximumDemand", "EnergyMet", "HydroGen", "WindGen", "SolarGen"]


def psp_hourly() -> pd.DataFrame:
    d = pd.read_csv(GRID / "india_psp_15min.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    h = d.resample("1h").mean()
    gen = h[[c for c in PSP_FACTORS if c in h.columns]]
    total = gen.sum(axis=1)
    h["ci_psp"] = (sum(gen[c] * PSP_FACTORS[c] for c in gen.columns) / total.where(total > 0))
    h["renewable_share_psp"] = h[["wind_mw", "solar_mw", "hydro_mw"]].sum(axis=1) / total.where(total > 0)
    return h.add_prefix("psp_").rename(columns={"psp_ci_psp": "ci_psp", "psp_renewable_share_psp": "renewable_share_psp"})


def kaggle_demand() -> pd.DataFrame:
    d = pd.read_csv(GRID / "india_hourly_load.csv", parse_dates=["datetime"]).set_index("datetime").sort_index()
    d = d[~d.index.duplicated()]
    d.columns = ["demand_national", "demand_north", "demand_west", "demand_east", "demand_south", "demand_northeast"]
    return d.add_suffix("_mw")


def cea_daily() -> pd.DataFrame:
    c = pd.read_csv(GRID / "CEA_DGR_data.csv")
    c.index = pd.to_datetime(c.pop("yyyymmdd").astype(str), format="%Y%m%d")
    g = c[[k for k in CEA_FACTORS if k in c.columns]].apply(pd.to_numeric, errors="coerce")
    # Wind / solar / other are absent before 2019 in this report; treating that as
    # zero would call 2018 dirtier than it was, so those days get no intensity.
    complete = g[["CEA.DGR.WND", "CEA.DGR.SOL"]].notna().all(axis=1)
    filled = g.fillna(0.0)
    total = filled.sum(axis=1)
    ci = (sum(filled[k] * CEA_FACTORS[k] for k in filled.columns) / total.where(total > 0)).where(complete)
    out = g.rename(columns=lambda k: k.replace("CEA.DGR.", "cea_").lower() + "_gwh")
    out["ci_cea_daily"] = ci
    out["cea_coal_share"] = ((filled["CEA.DGR.COL"] + filled["CEA.DGR.LIG"]) / total.where(total > 0)).where(complete)
    return out.add_prefix("d_").rename(columns={"d_ci_cea_daily": "d_ci_cea", "d_cea_coal_share": "d_coal_share"})


def posoco_daily() -> pd.DataFrame:
    p = pd.read_csv(GRID / "POSOCO_data.csv")
    p.index = pd.to_datetime(p.pop("yyyymmdd").astype(str), format="%Y%m%d")
    keep = [c for c in p.columns if c.startswith("India: ")]
    keep += [f"{r}: {f}" for r in REGIONS for f in POSOCO_REGION_FIELDS if f"{r}: {f}" in p.columns]
    out = p[keep].apply(pd.to_numeric, errors="coerce")
    out.columns = ["d_posoco_" + c.replace(": ", "_").replace(" ", "").lower() for c in out.columns]
    return out


def weather_ist(index: pd.DatetimeIndex) -> pd.DataFrame:
    w = pd.read_csv(BIG / "weather_hourly.csv", index_col=0, parse_dates=True)
    w.index = pd.to_datetime(w.index, utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
    w = w[~w.index.duplicated()].sort_index()
    both = w.index.union(index)
    return w.reindex(both).interpolate(method="time", limit=2).reindex(index)


def calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    import holidays

    hol = holidays.India(years=range(index.year.min(), index.year.max() + 1))
    cal = pd.DataFrame(index=index)
    cal["hour"], cal["dow"], cal["month"] = index.hour, index.dayofweek, index.month
    cal["is_weekend"] = (index.dayofweek >= 5).astype(int)
    cal["is_holiday"] = [int(d in hol) for d in index.date]
    # Indian meteorological seasons, matching india_load.SEASONS in spirit.
    cal["season"] = pd.cut(index.month, [0, 2, 5, 9, 11, 12], labels=["winter", "summer", "monsoon", "post_monsoon", "winter"],
                           ordered=False).astype(str)
    cal["hour_sin"], cal["hour_cos"] = np.sin(2 * np.pi * index.hour / 24), np.cos(2 * np.pi * index.hour / 24)
    cal["doy_sin"], cal["doy_cos"] = np.sin(2 * np.pi * index.dayofyear / 365.25), np.cos(2 * np.pi * index.dayofyear / 365.25)
    return cal


def main() -> None:
    psp, kag, cea, pos = psp_hourly(), kaggle_demand(), cea_daily(), posoco_daily()
    end = max(psp.index.max(), kag.index.max()).normalize() + pd.Timedelta(hours=23)
    idx = pd.date_range(START, end, freq="h", name="ts_ist")

    master = pd.DataFrame(index=idx)
    master = master.join(calendar(idx))
    master = master.join(psp).join(kag)
    daily = cea.join(pos, how="outer")
    key = pd.DatetimeIndex(idx.normalize())
    master = master.join(daily.reindex(key).set_index(idx))
    master = master.join(weather_ist(idx))

    # Provenance flags: what was measured at this hour, and at what resolution.
    master["has_psp_hourly"] = master["ci_psp"].notna().astype(int)
    master["has_hourly_demand_kaggle"] = master["demand_national_mw"].notna().astype(int)
    master["has_cea_daily"] = master["d_ci_cea"].notna().astype(int)
    master["has_posoco_daily"] = master["d_posoco_india_demandmet"].notna().astype(int)
    master["has_weather"] = master["india_temp_c"].notna().astype(int)

    # One demand column across both hourly sources, so a model has a single target.
    master["demand_mw"] = master["demand_national_mw"].fillna(master["psp_demand_met_mw"])
    master["demand_source"] = np.where(master["demand_national_mw"].notna(), "kaggle",
                                       np.where(master["psp_demand_met_mw"].notna(), "psp", ""))

    BIG.mkdir(parents=True, exist_ok=True)
    master.to_csv(OUT)

    # ---- validation: do independent sources agree where they overlap? ------
    checks = {}
    day_psp = master["ci_psp"].groupby(key).mean()
    j = pd.concat([day_psp.rename("psp"), cea["d_ci_cea"].rename("cea")], axis=1).dropna()
    if len(j) > 30:
        checks["ci_psp_vs_cea_daily"] = {"days": len(j), "corr": round(float(j.corr().iloc[0, 1]), 3),
                                         "mean_psp": round(float(j.psp.mean()), 1), "mean_cea": round(float(j.cea.mean()), 1)}
    dm_k = master["demand_national_mw"].groupby(key).mean() * 24 / 1000   # GWh/day
    j2 = pd.concat([dm_k.rename("kaggle_gwh"), pos["d_posoco_india_energymet"].rename("posoco_gwh")], axis=1).dropna()
    j2 = j2[(j2.kaggle_gwh > 0) & (j2.posoco_gwh > 0)]
    if len(j2) > 30:
        checks["kaggle_hourly_vs_posoco_daily_energy"] = {
            "days": len(j2), "corr": round(float(j2.corr().iloc[0, 1]), 3),
            "ratio_median": round(float((j2.kaggle_gwh / j2.posoco_gwh).median()), 3)}
    dm_p = master["psp_demand_met_mw"].groupby(key).mean() * 24 / 1000
    j3 = pd.concat([dm_p.rename("psp_gwh"), pos["d_posoco_india_energymet"].rename("posoco_gwh")], axis=1).dropna()
    if len(j3) > 30:
        checks["psp_demand_vs_posoco_daily_energy"] = {
            "days": len(j3), "corr": round(float(j3.corr().iloc[0, 1]), 3),
            "ratio_median": round(float((j3.psp_gwh / j3.posoco_gwh).median()), 3)}

    flags = [c for c in master.columns if c.startswith("has_")]
    cover = {}
    for f in flags:
        on = master.index[master[f] == 1]
        cover[f] = {"hours": int(len(on)), "from": str(on.min()) if len(on) else None, "to": str(on.max()) if len(on) else None}
    summary = {
        "note": "Generated by ml/build_india_dataset.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(master), "columns": master.shape[1],
        "index": f"hourly IST, {master.index.min()} .. {master.index.max()}",
        "size_mb": round(OUT.stat().st_size / 1e6, 1),
        "coverage": cover,
        "agreement_checks": checks,
        "column_groups": {
            "calendar": [c for c in master.columns if c in ("hour", "dow", "month", "is_weekend", "is_holiday", "season", "hour_sin", "hour_cos", "doy_sin", "doy_cos")],
            "psp_15min_hourly": [c for c in master.columns if c.startswith("psp_") or c in ("ci_psp", "renewable_share_psp")],
            "kaggle_hourly_demand": [c for c in master.columns if c.startswith("demand_") and c.endswith("_mw")],
            "daily_cea_and_posoco": [c for c in master.columns if c.startswith("d_")],
            "weather": [c for c in master.columns if "_temp_c" in c or "_rh_pct" in c or "_cloud_pct" in c or "_ghi_wm2" in c or "_wind_kmh" in c or "_rain_mm" in c],
        },
    }
    summary["column_groups"] = {k: {"n": len(v), "examples": v[:6]} for k, v in summary["column_groups"].items()}
    SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"{len(master):,} hourly rows x {master.shape[1]} columns · {summary['index']} · {summary['size_mb']} MB")
    for f, c in cover.items():
        print(f"  {f:<28} {c['hours']:>7,} h   {c['from']} .. {c['to']}")
    for k, v in checks.items():
        print(f"  check {k}: {v}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
