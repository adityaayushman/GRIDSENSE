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

> ⚠️ **Read this number as provisional.** Finding 11 shows the residential
> baseline these figures are measured against overstates household demand about
> sevenfold, and that error inflates the coordination gain by roughly 1.5×. The
> corrected headline is nearer 4× than 6.3×. The table above has not yet been
> recomputed on a calibrated baseline.

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

`export_regions.py` · **Two grids** pane · Spain (ENTSO-E 2015-2018) vs Germany/Luxembourg (2023-2026)

| Grid | Mean intensity | Std | Median night saving | Nights under 1% |
| --- | --- | --- | --- | --- |
| Spain | 266.6 gCO₂eq/kWh | 81.4 | **3.3%** | 38.0% |
| Germany | **358.4** | **135.0** | **1.0%** | **50.1%** |

Germany's grid is dirtier and swings harder, so it looked like the better place
to shift load. It is worse: half its nights offer under 1%.

**My first explanation for this was wrong** and is worth recording. I claimed
Germany's overnight hours "sit flat on lignite", so there was less within-night
shape to exploit. Measuring it directly refuted that: Germany's median spread
*inside the charging window* is **25.5%**, wider than Spain's 21.3%. More
within-window variation, less saving.

The actual reason is what the default behaviour already achieves. Averaged over
every night, 18:00 — the hour everyone plugs in — is the **cleanest** hour of
the window in both grids, and Germany's advantage there is larger:

| | Arrival hour vs that grid's night mean |
| --- | --- |
| Spain | −2.8% |
| Germany | **−7.4%** |

Charging on arrival is landing on the best hour by accident, and it lands there
harder in Germany. The optimizer is measured against that baseline, so the
better the accident, the less there is left to win. Three separate statistics —
mean intensity, standard deviation, and within-window spread — all point the
opposite way.

The practical reading: the value of carbon-aware charging is set by how good
the *unmanaged* behaviour already is, not by how carbon-intensive or how
volatile the grid is. See the **Two grids** pane, which plots both shapes.

The German data was screened with `screen_dataset.py` before use (lag-1
autocorrelation 0.92-0.99 across generation, load and price).

## 8. V2G is worth it for peak, not for carbon — and not at all for capacity

`optimize_schedule(allow_v2g=True)` · **Simulator**, vehicle-to-grid toggle

Letting vehicles discharge back to the grid improves whichever objective is
selected and quietly damages the others. On the default night, 80 vehicles. The
export cap is a policy dial, so both settings are shown: **capped** is the
shipped default of 6 kWh per vehicle per night, **uncapped** removes the limit.

| | CO₂ kg | Cost € | Peak kW | Exported |
| --- | --- | --- | --- | --- |
| Charge-only, min CO₂ | 216.1 | 98.93 | 782.8 | 0 |
| V2G capped, min CO₂ | 198.5 | 112.71 | 823.3 | 480 kWh |
| **V2G uncapped, min CO₂** | **161.1** | 154.26 | 863.1 | 1,858 kWh |
| Charge-only, min peak | 246.2 | 92.29 | 320.0 | 0 |
| **V2G, min peak** | 258.6 | 91.19 | **277.7** | 93 kWh |
| Charge-only, min cost | 266.6 | 87.20 | 741.1 | 0 |
| V2G capped, min cost | 310.7 | 85.11 | 741.1 | 480 kWh |
| **V2G uncapped, min cost** | 349.5 | **83.61** | 741.1 | 936 kWh |

The min-peak row is identical under both settings because the cap never binds
there — shaving the evening peak needs only 93 kWh, well inside the 480 kWh the
default allows.

Uncapped, minimising carbon with V2G pushes peak back to the *naive* level
(863.1 against 863.08) and raises the bill 56%. Under the shipped cap the same
objective still lands at 823 kW, above the charge-only 783, for a 14% higher
bill. Minimising cost raises emissions 31% against the charge-only cost optimum.

**Carbon abatement through V2G costs €0.78/kg CO₂ capped and €1.01/kg uncapped**,
against an EU ETS price around €0.06–0.09/kg — roughly ten times too expensive at
either setting, which is what makes the conclusion robust to where the dial is
set. As a way to cut carbon it is not economic; as a way to shave peak it works,
cutting the peak a further 13% below the charge-only optimum at a slightly
*lower* bill.

**It does nothing for hosting capacity.** The 1,250 kW transformer supports 988
vehicles whether V2G is on or off, capped or uncapped. Hosting capacity is bound
by *energy* — the fleet must still net-import what it needs, and V2G adds no
energy, it only moves import around and loses ~10% in the round trip. Peak and
capacity are different constraints, and V2G addresses only the first.

> **On the export cap.** Uncapped, the schedule cycles packs repeatedly: it
> prices carbon and money but not battery wear, and a battery that costs nothing
> to use is worth cycling until the arbitrage runs out. `max_export_kwh` caps
> throughput, as real V2G programmes do. The default is 6 kWh per vehicle per
> night. Degradation is out of scope for this project, so the cap stands in for
> it rather than modelling it.

> Round-trip loss (~10%) is charged entirely to the discharge leg. Splitting it
> across both legs is more physically faithful but would move every previously
> published figure by ~5% while changing nothing about V2G's economics, since
> only the round trip matters.

---

## 9. Rolling-horizon control loses to the one-shot LP, and the loss splits cleanly

`ml/mpc.py`, `ml/train_horizon.py` · **Rolling control** pane

Grid operators do not decide a whole night in advance; they re-solve as data
arrives and commit only the imminent step. Rebuilding the scheduler that way is
a harder and more defensible engineering claim than a static LP, so it was
built: 362 held-out nights, re-solving every hour, committing one hour at a
time.

It is worse. Mean regret against perfect foresight rises from **2.049%** to
**2.615%** — MPC gives back 28% of what the one-shot LP had already won. It is
better on 65 nights, identical on 189, worse on 108.

The interesting part is that the loss decomposes. A third arm re-solves every
hour but is fed only the static day-ahead forecast, so it gains no information
by waiting. It differs from each neighbour in exactly one thing:

| | mean regret | mean position |
| --- | --- | --- |
| One-shot LP | 2.049% | 4.83 |
| Rolling, static forecast | 3.411% | 5.28 |
| Rolling, refreshed forecast | 2.615% | 4.52 |
| Perfect foresight | 0% | 5.05 |

*Position* is the mean hour-index at which energy lands, 0 = 18:00, 12 = 06:00.

- **Committing hour by hour costs +1.361pp.**
- **Refreshing the forecast buys −0.796pp.**
- **Net +0.566pp**, so the control structure costs about 1.7× what the better
  information is worth.

The mechanism is visible in the position column. Rolling-with-static-info defers
hardest of all — 5.28, later even than perfect foresight at 5.05. At each hour
it compares the hour in front of it against the *minimum* of a dozen noisy
forecasts, and the minimum of noisy estimates is optimistically biased: some
later hour almost always looks cleaner than it will turn out to be. So the
controller waits, waits again, and is eventually forced to buy whatever the
remaining hours offer. The one-shot LP never faces that comparison, because it
allocates across all thirteen hours at once and its errors partly average out.

Forecast quality does improve with proximity, and by a lot — MAE runs from
**6.72 g at one hour ahead to 26.33 g at thirteen**, monotone, measured in
`train_horizon.py`. The premise of rolling control holds. What fails is the
assumption that better information per decision outweighs making thirteen
irreversible decisions instead of one.

> **Two ways this comparison could have been rigged, and what was done about
> them.** The shipped day-ahead model (MAE 23.70) beats the lag models from h=9
> out, so a controller could be flattered by handing its baseline the weaker
> forecast at long horizons. Both arms use the better model at every horizon,
> with the crossover recorded. Separately, an early version let the baseline read
> the *true* intensity for horizons past the crossover, which handed the one-shot
> LP perfect foresight of 03:00–06:00 — the cleanest stretch of a Spanish night.
> That bug made MPC look 238% worse; fixing it moved the answer to 28%. The sign
> did not change, but nearly all of the magnitude did.

> **What was not tried.** This is certainty-equivalent MPC — the standard
> reading of "re-solve each hour and execute the next step". A controller with a
> terminal cost, or one penalising deferral to price the optionality it is
> destroying, would target the diagnosed failure directly. That is a real
> possibility and is not evidence for the current conclusion, which is only
> about the formulation actually tested.

Time-consistency is pinned by `test_optimizer_is_time_consistent`, and the
backtest re-checks it every run: fed perfect forecasts, the rolling machinery
reproduces the one-shot optimum to 0.0000% on every sampled night. The loss is
a property of forecasting under commitment, not an implementation artefact.

---

## 10. India is a different problem, and the European model gets it wrong twice

`ml/india_fleet.py`, `ml/export_india_capacity.py` · **India** pane

Hosting capacity never needed carbon data — it is load against a rating — so it
is the one claim in this project that transfers to India intact. What does not
transfer is everything underneath it.

**India does not drive cars.** FADA retail registrations for calendar 2025:
two-wheelers 1,279,951 (56%), three-wheelers 797,733 (35%), passenger cars
176,817 (8%). Ninety-one percent of Indian EVs are two- and three-wheelers, and
61% of *all* three-wheeler sales are now electric — that segment is close to
fully electrified rather than emerging.

**Indian transformers are small.** IS 1180 standard distribution ratings run
16–2500 kVA, and a residential unit is typically 63–250 kVA against the 1,250 kW
this project assumed. Ratings are apparent power, so a 0.9 power factor is
applied; treating kVA as kW would quietly grant every transformer 10% more
headroom than it has.

Per 100 vehicles:

| | Energy wanted | Connected power |
| --- | --- | --- |
| Indian fleet | 404 kWh | 144 kW |
| European cars | 920 kWh | 700 kW |

**2.3× less energy and 4.9× less connected power.** A 900 W scooter charger is
not a small car charger; it is a different class of load, and thirteen overnight
hours are far more than it needs. Three-wheelers are the segment that matters:
35 of the 100 vehicles but 56% of the energy, because a shared rickshaw is
worked all day and wants most of its pack back.

Capacity on a 40-home feeder:

| Rating | On arrival | Coordinated | Gain |
| --- | --- | --- | --- |
| 63 kVA | 24 | 129 | **5.4×** |
| 100 kVA | 60 | 236 | 3.9× |
| 160 kVA | 116 | 410 | 3.5× |
| 250 kVA | 194 | 672 | 3.5× |
| 400 kVA | 331 | 1,111 | 3.4× |

**The gain rises as the transformer shrinks.** On a small unit the houses
already occupy most of the rating, so the headroom for charging on arrival is
thin while the overnight valley is proportionally larger. Coordination is worth
most exactly where the grid is most constrained — which in India is most of it.
That is the opposite of where a European reading would point the intervention.

On the same 100 kVA unit, the Indian fleet fits 60 vehicles charging on arrival
against 25 European cars. Modelling India with European vehicles would have
understated one transformer's capacity 2.4× and aimed the fix at the wrong
problem.

> **Carbon is still open.** Grid-India and the CEA publish generation mix only
> daily, but Electricity Maps' data portal offers free historical CSV at hourly
> granularity for Indian zones, which an earlier note in this document wrongly
> called paid. Finding 7 predicts India will save *less* than Spain despite
> being 2.3× dirtier, because steady coal has no shape to exploit. That is now
> testable and has not been tested.

---

## 11. The residential baseline was overstated sevenfold, and it inflated finding 1

`app/data_sources.py` · found while calibrating the Indian equivalent

The synthetic household profile is a sum of two Gaussians:

```python
household_count * (2.2 + 1.8 * exp(-((h-19)**2)/8) + 0.6 * exp(-((h-8)**2)/4))
```

Its *shape* was the documented assumption. Its **magnitude** was never checked,
and it is wrong: 4.00 kW peak and **1,915 kWh per household per month**, against
a measured Spanish average near 292. Spanish households commonly *contract*
3.3–5.75 kW as a ceiling; this curve never drops below 2.2 kW all night.

Because the transformer binds on `residential + EV load`, an inflated baseline
eats the rating before any vehicle plugs in — 800 kW of 1,250 kW. That punishes
charge-on-arrival, which adds to the existing peak, far more than it punishes
coordinated charging, which fills the overnight valley. So overstating the
houses overstates the value of coordination.

Holding the fleet and the transformer fixed and correcting only the baseline:

| Baseline | Per home | On arrival | Coordinated | Gain |
| --- | --- | --- | --- | --- |
| As shipped | 1,915 kWh/mo | 193 | 988 | **5.1×** |
| Calibrated | 288 kWh/mo | 465 | 1,635 | **3.5×** |

The published headline is **6.3×** on the realistic staggered fleet. The
comparison above uses a simplified fleet, so it does not give the corrected
headline directly — but the direction and rough size are unambiguous: the
baseline error inflates the coordination gain by about 1.5×, and the real figure
is nearer 4× than 6.3×.

The Indian model (finding 10) is calibrated: its profile is scaled so the day
integrates to Delhi's measured ~260 kWh/month, leaving only the *shape*
assumed. The Spanish pipeline has not yet been recomputed on a corrected
baseline, and every capacity figure in finding 1 and the **Grid headroom** pane
should be read as provisional until it is.

This is the same class of error as finding 3, where a synthetic carbon curve
turned out to be inverted. The lesson there was applied to the carbon input and
not to this one.

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

**Grid-India / CEA generation mix — rejected on resolution, not quality.**
Localising the whole project to India is the strongest differentiator available
to it, so the official sources were checked properly rather than dismissed.
Grid-India (formerly POSOCO) and the CEA publish a complete fuel breakdown —
coal, lignite, gas, nuclear, hydro, solar, wind — for **2,821 days** back to
2018, mirrored at `robbieandrew.github.io/india/`. The data is real, long, and
detailed. It is **daily**. This project schedules inside an 18:00–07:00 window,
and one number per day has no within-night shape to schedule against. Hourly
Indian generation mix exists only behind ElectricityMaps' paid API or inside
RLDC 15-minute PSP report PDFs, which would be a scraping project in its own
right. State SLDCs publish load, and load is not mix.

**Correction.** The paragraph above originally called Electricity Maps the paid
route. That is wrong for the historical data: their data portal offers free CSV
downloads at hourly granularity for Indian zones (2021-2024, five datasets per
account). The *API* is paid; the archive is not. The POSOCO/CEA finding stands —
those really are daily — but the conclusion drawn from it, that no free hourly
Indian source existed, was an overreach. Hourly Indian carbon intensity is
obtainable, and finding 7's prediction about India is testable.

The level comparison is still worth having, and finding 7 gives it teeth:

| | Carbon intensity | Resolution |
| --- | --- | --- |
| Spain | 267 gCO₂eq/kWh | hourly |
| Germany | 358 gCO₂eq/kWh | hourly |
| India | **626 gCO₂eq/kWh** | daily |

India runs 2.3× dirtier than Spain on 74% coal, with day-to-day variation of
only 7.3%. Finding 7 established that the value of carbon-aware charging tracks a
grid's *shape* rather than its dirtiness, which predicts India would be a **poor**
candidate despite the filthy power — steady coal offers nothing to shift toward.
That is a hypothesis, not a result; confirming it needs the hourly data that is
not available. `ml/india_feasibility.py` reproduces the table.

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
