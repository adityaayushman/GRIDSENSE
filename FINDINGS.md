# GridSense — findings

Every number here is reproducible from the scripts named beside it, against
measured ENTSO-E Spanish grid data (Kaggle, CC0) with IPCC AR5 lifecycle
emission factors. Nothing is hand-tuned or assumed.

Regenerate everything:

```bash
cd ml
python backtest.py                # 1,444-night replay      -> data/backtest_nightly.csv
python train.py                   # first-pass forecaster   -> artifacts/metrics.json
python train_v2.py                # tuned sweep + weather   -> artifacts/metrics_v2.json
python export_forecaster.py       # deployable ridge        -> artifacts/ridge_forecaster.json
python export_evidence.py         # -> frontend/src/data/evidence.json
python export_hosting_capacity.py # -> frontend/src/data/hosting.json
```

---

## 1. Coordination buys 6× the hosting capacity of the same transformer

`export_hosting_capacity.py` · **Grid headroom** pane

200 existing homes (800 kW residential peak), EVs arriving into them. Fleet has
staggered arrivals and departures, mixed energy requirements and a 3.7/7/11 kW
charger mix; median across 12 measured nights:

| Transformer | Charging on arrival | Coordinated | Gain |
| --- | --- | --- | --- |
| 1,000 kW | 70 | 809 | 11.6× |
| **1,250 kW** | **200** | **1,254** | **6.3×** |
| 1,500 kW | 340 | 1,700 | 5.0× |

The mechanism is that the binding constraint moves. Charging on arrival consumes
one or two hours of a thirteen-hour window and hits the rating on *instantaneous
power* while most of the night sits empty. Coordinating the street spreads the
same energy across the window until *energy* binds instead.

This is the finding with capital attached: it defers a physical upgrade.

> **This number was previously reported as 14.1×, and that was wrong.** The
> earlier figure assumed every vehicle arrives at exactly 18:00. That is not a
> harmless simplification — a synchronised arrival maximally penalises the
> baseline it is measured against. Once arrivals stagger, the coordinated ceiling
> rises about 27% but charge-on-arrival hosting **triples** (70 → 200 at
> 1,250 kW), because the arrival spike spreads out on its own. Most of the
> claimed 14× was the assumption, not the coordination. The identical-fleet
> figures are kept in the pane as contrast.

Ceilings come from bisecting the solver, bounded above by an energy argument so
the search can never report its own limit as the answer — an earlier version
returned exactly 1,500 at the 1,500 kW rating, which was the bisection bound
rather than a ceiling. `solver_ceiling` now raises instead of returning it.

> **Remaining caveat.** Vehicles are still drawn from one distribution and every
> car can wait until morning. A fleet with hard early deadlines would host fewer.

## 2. The emissions saving is real but small, and long-tailed

`backtest.py` · **Existing vs GridSense** pane

Replaying the optimizer over all 1,444 complete overnight windows:

| | CO₂ reduction vs charging on arrival |
| --- | --- |
| Median night | **3.3%** |
| Mean night | 9.6% |
| Fleet total across four years | **10.4%** |

**38% of nights save under 1%.** 57% save under 5%. 17% save over 20%. On 33% of
nights the cleanest hour in the window is 18:00 — the arrival hour — so charging
on arrival is already near-optimal.

A single headline percentage hides both tails, which is why the dashboard reports
the distribution.

## 3. The synthetic curve was not merely inaccurate — it was inverted

`train.py` · **Existing vs GridSense** pane

Real Spanish grid intensity is *lowest* at midday (solar) and *highest* in the
early morning. The synthetic curve originally shipped in `data_sources.py` peaked
at 19:00 and troughed at 13:00 — roughly the opposite shape.

Evaluated by **decision regret** — schedule on the forecast, score against what
actually happened, compare to perfect foresight:

| Forecast | MAE | % of achievable saving captured |
| --- | --- | --- |
| Synthetic curve | 97.20 | **−26.8%** |
| Persistence (lag 24h) | 44.32 | 12.8% |
| Climatology (month × hour) | 56.01 | 16.4% |
| Gradient boosting | 28.51 | 67.5% |
| **Ridge (deployed)** | **23.70** | **71.0%** |
| Ridge + GBM blend (not shipped) | 22.61 | 72.8% |

The synthetic curve scores **negative**: scheduling against it is worse than not
optimizing at all. A demo driving real chargers that way would increase emissions.

The blend is the strongest candidate but is **not** what ships: it needs
scikit-learn at inference, while ridge exports as a coefficient vector scored
with a dot product and keeps the serverless bundle free of ML dependencies.
Ridge gives up 1.8pp of captured saving for that, which is the right trade for a
function that already carries a CBC solver binary. The export is verified
bit-exact against sklearn.

`train_v2.py` improved ridge from MAE 28.27 / 68.5% to 23.70 / 71.0% — a 16% cut
in error — through richer features (more lags, rolling min/max/std, week-over-week
drift, renewable share) and a 48-config hyperparameter search under blocked
time-series CV. No new data was involved.

## 4. The optimizer only earns its keep under a coupling constraint

`export_evidence.py` · **Existing vs GridSense** pane

| Scenario | LP vs greedy objective gap | Greedy peak |
| --- | --- | --- |
| Identical vehicles | 0.0000% | 560 kW |
| Mixed arrivals, energy, chargers | 0.0000% | 482.5 kW |
| Mixed + shared 180 kW feeder | 10.4953% | 482.5 kW — **breaches by 302.5 kW** |

Without a constraint linking vehicles the problem **separates**: each car
independently fills its own cleanest hours and a ten-line greedy loop reproduces
the LP exactly. Vehicle heterogeneity does not change this — the surprise, since
variety was the expected unlock. Only a shared limit makes the schedule a genuine
optimisation.

Two constraints in this model couple vehicles: the `peak` objective, and feeder
capacity. Until feeder capacity was exposed, two of the three objectives were
solvable by greedy.

## 5. Cost and carbon genuinely conflict

`export_grid_days.py`

The cheapest hour and the cleanest hour coincide on only **14.4%** of nights
(correlation 0.41). Optimizing for cost can raise emissions — on the default
night it raises them 18.7% — and optimizing for emissions can raise peak. The
dashboard shows those as increases rather than hiding them.

## 6. Forecast error only matters when there is something to gain

`export_forecast_curves.py` · **Simulator**, Carbon signal toggle

Scheduling on the day-ahead forecast and scoring against actuals, per night:

| Night | Perfect foresight | On forecast | Captured |
| --- | --- | --- | --- |
| 2018-01-19 | 38.5% | 37.8% | 98% |
| 2018-02-11 | 31.1% | 28.9% | 93% |
| 2018-02-02 | 26.0% | 24.0% | 92% |
| 2018-02-12 | 6.5% | **−9.4%** | −145% |
| 2018-02-15 | 2.1% | **−2.4%** | −114% |

When the curve has real structure the forecast finds it, capturing 92-98%. When
the night is nearly flat, forecast error exceeds the differences being chased and
scheduling on it is worse than not scheduling at all. Aggregated by total mass
across 2018 the forecast captures 71.0%, which hides this split.

The operational reading: act only when the *predicted* spread is large enough to
survive the model's own error. That is a gate this project does not yet
implement.

## 7. A dirtier, more variable grid is not a better one to shift in

`compare_regions.py` · Spain (ENTSO-E 2015-2018) vs Germany/Luxembourg (2023-2026)

| Grid | Mean intensity | Std | Median night saving | Nights under 1% |
| --- | --- | --- | --- | --- |
| Spain | 267 gCO₂eq/kWh | 81 | **3.3%** | 38% |
| Germany | **358** | **135** | **1.0%** | **50%** |

Germany's grid is dirtier and swings harder, so it looked like the better place
to shift load. It is worse: half its nights offer under 1%.

The reason is that *overall* variability is the wrong statistic. What a
scheduler can exploit is variability **inside the plug-in window**, and
Germany's variance is largely driven by multi-day weather — wind arriving or
not — which moves whole days together rather than creating within-night shape.
Its overnight hours sit flat on lignite and coal.

The practical reading: the value of carbon-aware charging is a property of a
grid's *diurnal shape*, not of how carbon-intensive it is. A country can be a
poor candidate precisely because its dirty generation is steady.

The German data was screened with `screen_dataset.py` before use (lag-1
autocorrelation 0.92-0.99 across generation, load and price).

---

## Datasets evaluated and rejected

Screened with `screen_dataset.py`, which any candidate must pass before it is
trained on. The decisive test is autocorrelation: every real physical series has
hour-to-hour inertia, and values drawn independently do not, however plausible
the column names look.

| Candidate | Verdict |
| --- | --- |
| [EV Charging EDA Insights](https://www.kaggle.com/code/amitvkulkarni/ev-charging-eda-insights) | A Kaggle *notebook*, not a dataset — no data to train on |
| [EV Charging Stations in India (OpenChargeMap)](https://www.kaggle.com/datasets/deepeshkansotia/ev-charging-stations-in-india-openchargemap) | 1,000 station locations. No time column and **no power-rating column**, so it cannot inform charger mix or scheduling |
| [EV Charging Station Usage & Grid Load](https://www.kaggle.com/datasets/jayjoshi37/ev-charging-station-usage-and-grid-load-analysis) | **Independent random draws.** Fails the screen on every column |

The third is worth spelling out, because it looks entirely usable — hourly
timestamps, no gaps, realistic column names and ranges:

| Series | lag-1 | lag-24 |
| --- | --- | --- |
| `grid_load_mw` (India) | −0.025 | −0.004 |
| `vehicles_charged` (India) | +0.018 | +0.010 |
| White-noise reference | −0.056 | +0.009 |
| `carbon_intensity` (measured, Spain) | **+0.983** | +0.649 |
| `total load actual` (measured, Spain) | **+0.951** | +0.700 |

Grid load at 15:00 has no relationship to grid load at 14:00, which no real
feeder does. A model fit to this learns the mean and reports a believable error
figure while having learned nothing.

Separately, all three are **India** and this project's carbon and price series
are **Spain**. Even had the data been sound, mixing them into the carbon
forecaster would have corrupted it — the grid mixes are not comparable.

One earlier check of mine was the wrong test and is worth recording: variance
explained by hour-of-day gave R² ≈ 0.008 for the India data, which looked
damning until the same statistic came out at R² ≈ 0.0085 for *measured* Spanish
carbon intensity. Four-year hourly means wash out the diurnal swing, so that
statistic separates nothing. Autocorrelation does.

---

## Hypotheses that did not survive

Kept deliberately. A findings document that only lists confirmations is a
marketing document.

**Uncoordinated carbon-aware charging was expected to be *worse* than dumb
charging.** The theory: every household independently targets the same cleanest
hour, synchronises, and manufactures a new peak. It raises the peak on only 3 of
46 nights, and by 1.03×. The cleanest hours are usually overnight, away from the
19:00 residential peak, so selfish optimisation normally helps slightly. The
synchronisation effect is real but small; the coordination gap is the large one.

**Weather was expected to be the largest untapped signal.** The Kaggle download
shipped `weather_features.csv` — hourly cloud cover, wind speed and temperature
for five Spanish cities — unused by the first pass. Cloud cover drives solar and
wind speed drives wind, so it looked like the obvious lever. Measured across a
full re-run with 40 features instead of 25, it is worth **−0.19pp** of captured
saving: very slightly *worse*. The reason is clean — the dataset already carries
the TSO's day-ahead solar and wind forecasts, which are themselves produced from
weather models, so the signal was already present and the raw columns added
redundancy and dimensionality. Both variants are reported in
`artifacts/metrics_v2.json`.

**Vehicle heterogeneity was expected to make the LP necessary.** It does not —
see finding 4. Differing arrivals, energies and charger ratings still separate.

**An early sweep scaled the residential baseline with the EV count**, so both
peaks grew together, the ratio pinned at 0.91× and no crossing point could exist
by construction. Houses already exist; EVs arrive into them.

---

## Known limitations

- **Average, not marginal, carbon intensity.** The derived series is the
  emissions of the average kWh; load shifting responds to the *next* kWh.
  `src/carbon.py` estimates a system marginal rate (228 vs 267 gCO₂eq/kWh
  average) but the served series is the average. Closing this needs MOER data.
- **The residential baseline is the one remaining synthetic input.** ENTSO-E
  reports system-wide load, which cannot be scaled to a single feeder without an
  assumption.
- **All vehicles in a scenario are identical.** The optimizer supports
  heterogeneity; the API does not expose it.
- **Spain, not California.** Chosen because Spanish households are billed at
  genuinely hourly-varying prices (PVPC), which is the premise the cost objective
  depends on.
