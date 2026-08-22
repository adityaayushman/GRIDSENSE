"""Does carbon-aware charging pay off differently in a different grid?"""
import sys, statistics
sys.path.insert(0, "d:/projects/gridsense/ml/src")
sys.path.insert(0, "d:/projects/gridsense/backend")
import pandas as pd, numpy as np
from carbon import EMISSION_FACTORS
from app.optimizer import Vehicle, naive_schedule, optimize_schedule

# German columns -> the same IPCC AR5 factors, keyed by this file's names.
DE = {
 "biomass":230.0,"fossil_brown_coal_lignite":1054.0,"fossil_coal_derived_gas":820.0,
 "fossil_gas":490.0,"fossil_hard_coal":820.0,"fossil_oil":650.0,"geothermal":38.0,
 "hydro_run_of_river":24.0,"hydro_water_reservoir":24.0,"hydro_pumped_storage":24.0,
 "nuclear":12.0,"others":700.0,"waste":700.0,"wind_offshore_mw":11.0,
 "wind_onshore_mw":11.0,"solar_mw":45.0,
}

d = pd.read_csv("data/de/de_lu_hourly.csv", parse_dates=["ts_utc"])
d = d.set_index("ts_utc").sort_index()
gen = d[list(DE)].fillna(0.0)
tot = gen.sum(axis=1)
ci_de = (sum(gen[c]*DE[c] for c in DE) / tot.replace(0, np.nan)).dropna()

e = pd.read_csv("data/raw/energy_dataset.csv", parse_dates=["time"], index_col="time")
e.index = pd.to_datetime(e.index, utc=True); e = e[~e.index.duplicated()].sort_index()
cols = [c for c in EMISSION_FACTORS if c in e.columns]
g = e[cols].fillna(0.0)
ci_es = (sum(g[c]*EMISSION_FACTORS[c] for c in cols) / g.sum(axis=1).replace(0, np.nan)).dropna()

print(f"{'':<10} {'mean':>8} {'std':>8} {'p10':>8} {'p90':>8}  gCO2eq/kWh")
for name, ci in (("Spain", ci_es), ("Germany", ci_de)):
    print(f"{name:<10} {ci.mean():>8.0f} {ci.std():>8.0f} {ci.quantile(.1):>8.0f} {ci.quantile(.9):>8.0f}")

# The number that matters: saving achievable inside a real charging window.
fleet=[Vehicle("agg", 9.2*80, 7.0*80, 18, 7)]; naive=naive_schedule(fleet)
def sweep(ci, tz):
    loc = ci.index.tz_convert(tz); h = loc.hour
    night = loc.normalize() - pd.to_timedelta((h<7).astype(int), unit="D")
    f = pd.DataFrame({"ci":ci.values,"h":h,"n":night})
    w=[x%24 for x in range(18,18+13)]; cuts=[]
    for _, grp in f.groupby("n"):
        by = grp.groupby("h")["ci"].mean()
        if not set(w).issubset(by.index): continue
        curve=[float(by.get(x, by.mean())) for x in range(24)]
        opt=optimize_schedule(fleet, curve, objective="emissions")
        en=sum(naive[x]*curve[x] for x in range(24)); eo=sum(opt[x]*curve[x] for x in range(24))
        if en>0: cuts.append((1-eo/en)*100)
    return cuts

print()
for name, ci, tz in (("Spain", ci_es, "Europe/Madrid"), ("Germany", ci_de, "Europe/Berlin")):
    c = sweep(ci, tz)
    print(f"{name:<10} nights {len(c):>5}  median {statistics.median(c):>5.1f}%  "
          f"mean {statistics.mean(c):>5.1f}%  under1% {sum(1 for x in c if x<1)/len(c)*100:>4.0f}%  "
          f"over20% {sum(1 for x in c if x>20)/len(c)*100:>4.0f}%")
