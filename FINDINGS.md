# GridSense — findings

Every number here is reproducible from the scripts named beside it, against
measured ENTSO-E Spanish grid data (Kaggle, CC0) with IPCC AR5 lifecycle
emission factors. Nothing is hand-tuned or assumed.

Regenerate everything:

```bash
cd ml
python backtest.py                # 1,444-night replay      -> data/backtest_nightly.csv
python train.py                   # forecaster + regret     -> artifacts/metrics.json
python export_evidence.py         # -> frontend/src/data/evidence.json
python export_hosting_capacity.py # -> frontend/src/data/hosting.json
```

---

## 1. Coordination buys 14× the hosting capacity of the same transformer

`export_hosting_capacity.py` · **Grid headroom** pane

200 existing homes (800 kW residential peak), EVs arriving into them, median
across 46 measured nights:

| 1,250 kW transformer | EVs hosted before the median night exceeds the rating |
| --- | --- |
| Charging on arrival | 70 |
| Uncoordinated carbon-aware | 100 |
| **Coordinated** | **988** (14.1×) |

The mechanism is that the binding constraint moves. Charging on arrival consumes
one or two hours of a thirteen-hour window and hits the rating on *instantaneous
power* while most of the night sits empty. Coordinating the street spreads the
same energy across the window until *energy* binds instead.

This is the finding with capital attached: it defers a physical upgrade.

Coordinated ceilings are solved analytically (`max_deliverable_kwh`) rather than
read off the end of the sweep — otherwise the answer is just where the sweep
stopped — and confirmed against the solver at the boundary in both directions.

> **Caveat.** Every vehicle is identical and plugged in for the same window.
> Staggered arrivals and cars that cannot wait both reduce this ceiling.

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
| **Ridge** | **28.27** | **68.5%** |

The synthetic curve scores **negative**: scheduling against it is worse than not
optimizing at all. A demo driving real chargers that way would increase emissions.

Ridge ties gradient boosting on accuracy, so the linear model wins on
deployability — it exports as 15 coefficients scored with a dot product, needing
no scikit-learn in the serverless bundle, and the export is verified bit-exact
against sklearn.

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
