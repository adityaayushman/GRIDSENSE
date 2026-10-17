"""How does a real street's evening demand compare with the modelled baseline?

The hosting-capacity headline (finding 1) uses a modelled residential baseline: system load scaled to
a street. A real street is a sum of individual homes, and individual homes are spiky; the sum over
a couple of hundred smooths them but keeps an evening peak. This measures that on real smart-meter
data (Low Carbon London, GoiEner; see `fetch_real_loads.py`):

  * the diversified evening peak per home on a street of N homes, and how much it varies between
    streets (the thing a single modelled number hides)
  * the peak-to-trough ratio of the street's average day
  * which hour the peak falls in

and puts the modelled baseline beside it. Three representative streets per region (p10, median, p90
by evening peak per home), each in annual-average and winter form, are saved with their 24-hour
profiles for `hosting.py` to run the hosting-capacity search on.

    python baselines.py uk
    python baselines.py spain
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE.parent / "data" / "validation"
OUT = HERE.parent / "artifacts"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "backend"))

from app import data_sources as ds  # noqa: E402

REGIONS = {
    "uk": {"name": "United Kingdom", "tz": "Europe/London", "file": "uk_homes.npz",
           "source": "Low Carbon London, UK Power Networks, 2013, flat-tariff homes", "licence": "CC BY 4.0"},
    "spain": {"name": "Spain (Basque Country and Navarre)", "tz": "Europe/Madrid", "file": "spain_homes.npz",
              "source": "GoiEner, residential supply points without self-generation, 2018",
              "licence": "CC BY 4.0"},
}
HOMES = 200          # the headline street (a 250 kW unit)
DRAWS = 300
EVENING = list(range(17, 24))
WINTER = (12, 1, 2)


def load(region: str) -> tuple[np.ndarray, pd.DatetimeIndex]:
    z = np.load(DATA / REGIONS[region]["file"], allow_pickle=False)
    hours = pd.to_datetime(z["hours"], unit="h", utc=True)
    kw = z["kw"].astype(np.float64)
    # Fill a home's gaps with its own mean for that local hour of day, so a missing hour neither
    # drops a home from the sum nor adds a spurious zero.
    loc_hour = hours.tz_convert(REGIONS[region]["tz"]).hour.to_numpy()
    for h in range(24):
        cols = np.where(loc_hour == h)[0]
        block = kw[:, cols]
        mean = np.nanmean(block, axis=1, keepdims=True)
        block = np.where(np.isfinite(block), block, mean)
        kw[:, cols] = block
    return kw, hours


def street_profile(kw: np.ndarray, rows: np.ndarray, loc_hour: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean demand of the whole street by local hour of day, in kW."""
    s = kw[rows][:, mask].sum(axis=0)
    h = loc_hour[mask]
    return np.array([s[h == k].mean() for k in range(24)])


def metrics(profile: np.ndarray, homes: int) -> dict:
    return {
        "peak_kw_per_home": round(float(profile.max() / homes), 3),
        "peak_hour": int(profile.argmax()),
        "mean_kw_per_home": round(float(profile.mean() / homes), 3),
        "peak_to_trough": round(float(profile.max() / profile.min()), 2),
        "peak_to_mean": round(float(profile.max() / profile.mean()), 2),
    }


def model_baseline(homes: int) -> dict:
    shape = ds.SPAIN_LOAD_SHAPE
    scale = ds.SPAIN_DAILY_KWH_PER_HOME / sum(shape)
    prof = np.array([homes * s * scale for s in shape])
    return {**metrics(prof, homes), "profile_kw": [round(float(v), 2) for v in prof]}


def run(region: str) -> dict:
    cfg = REGIONS[region]
    kw, hours = load(region)
    loc = hours.tz_convert(cfg["tz"])
    loc_hour = loc.hour.to_numpy()
    winter = np.isin(loc.month.to_numpy(), WINTER)
    allm = np.ones(len(hours), dtype=bool)
    rng = np.random.default_rng(5)
    n = kw.shape[0]
    draws = []
    for _ in range(DRAWS):
        rows = rng.choice(n, size=min(HOMES, n), replace=False)
        p_all = street_profile(kw, rows, loc_hour, allm)
        p_win = street_profile(kw, rows, loc_hour, winter)
        draws.append((p_all, p_win, rows))
    peaks = np.array([d[1].max() / HOMES for d in draws])      # winter evening peak per home decides the street
    order = np.argsort(peaks)
    pick = {"p10": order[int(0.10 * DRAWS)], "median": order[DRAWS // 2], "p90": order[int(0.90 * DRAWS)]}

    def summ(arr):
        a = np.asarray(arr)
        return {"p5": round(float(np.percentile(a, 5)), 3), "median": round(float(np.median(a)), 3),
                "p95": round(float(np.percentile(a, 95)), 3)}

    stats = {
        "peak_kw_per_home_annual": summ([d[0].max() / HOMES for d in draws]),
        "peak_kw_per_home_winter": summ(peaks),
        "peak_to_trough_annual": summ([d[0].max() / d[0].min() for d in draws]),
        "peak_hour_winter_mode": int(pd.Series([int(d[1].argmax()) for d in draws]).mode().iloc[0]),
        "mean_kw_per_home": round(float(np.mean([d[0].mean() / HOMES for d in draws])), 3),
    }
    streets = {}
    for label, i in pick.items():
        p_all, p_win, rows = draws[i]
        streets[label] = {
            "annual": {**metrics(p_all, HOMES), "profile_kw": [round(float(v), 2) for v in p_all]},
            "winter": {**metrics(p_win, HOMES), "profile_kw": [round(float(v), 2) for v in p_win]},
        }
    # How much does the sample size matter? Diversity: the per-home peak falls as homes are pooled.
    diversity = []
    for m in (1, 5, 20, 50, 100, 200):
        if m > n:
            continue
        vals = []
        for _ in range(120):
            rows = rng.choice(n, size=m, replace=False)
            vals.append(street_profile(kw, rows, loc_hour, winter).max() / m)
        diversity.append({"homes": m, "median_peak_kw_per_home": round(float(np.median(vals)), 3)})
    return {
        "region": region, "name": cfg["name"], "source": cfg["source"], "licence": cfg["licence"],
        "homes_in_panel": int(n), "street_homes": HOMES, "draws": DRAWS, "stats": stats,
        "streets": streets, "diversity_winter_peak": diversity,
        "model": model_baseline(HOMES),
    }


if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else ""
    if region not in REGIONS:
        sys.exit(__doc__)
    res = run(region)
    (OUT / f"validation_baselines_{region}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    s, m = res["stats"], res["model"]
    print(f"{res['name']}: {res['homes_in_panel']} homes, streets of {HOMES}")
    print(f"  real winter evening peak per home  median {s['peak_kw_per_home_winter']['median']} kW "
          f"(5-95%: {s['peak_kw_per_home_winter']['p5']}-{s['peak_kw_per_home_winter']['p95']}) at hour {s['peak_hour_winter_mode']}")
    print(f"  real annual peak per home          median {s['peak_kw_per_home_annual']['median']} kW")
    print(f"  real peak-to-trough (annual)       median {s['peak_to_trough_annual']['median']}")
    print(f"  model baseline                     peak {m['peak_kw_per_home']} kW/home at hour {m['peak_hour']}, "
          f"peak-to-trough {m['peak_to_trough']}")
