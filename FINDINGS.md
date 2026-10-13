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

## 1. Coordination buys about 4× the hosting capacity of the same transformer

`export_hosting_capacity.py` · **Grid headroom** pane

200 existing homes on a measured residential baseline (89 kW peak), EVs arriving
into them. Fleet has staggered arrivals and departures, mixed energy
requirements and a 3.7/7/11 kW charger mix. Capacity is the **median over fleet
draws** (20 at the headline rating, 6 at the others), each draw taking the median
across 12 measured nights, with the charge-on-arrival ceiling found on a step-1
grid:

| Transformer | Charging on arrival | Coordinated | Gain (median) | Range across draws |
| --- | --- | --- | --- | --- |
| 160 kW | 25 | 148 | 5.8× | 4.0-6.9× |
| **250 kW** | **75** | **308** | **4.1×** | **3.3-5.3×** |
| 400 kW | 151 | 580 | 3.8× | 3.3-4.4× |
| 630 kW | 272 | 990 | 3.7× | 3.2-3.9× |

An earlier version of this table was one draw of the fleet (seed 0): 60 → 318 =
**5.3×** at 250 kW, 7.5× at 160 kW and 4.0× at 630 kW. That draw was the most
favourable of the twenty, which is how it went unnoticed; the sensitivity section
below shows the spread.

The mechanism is that the binding constraint moves. Charging on arrival consumes
one or two hours of a thirteen-hour window and hits the rating on *instantaneous
power* while most of the night sits empty. Coordinating the street spreads the
same energy across the window until *energy* binds instead.

**The gain is not one number — it falls as the transformer loosens**, from 5.8×
on a 160 kW unit to 3.7× on a 630 kW one. Coordination is worth most where the
headroom is thinnest, so quoting a single figure means quoting a rating with it.
250 kW is the headline because 200 Spanish dwellings at a measured 0.446 kW
coincident peak are a plausible load for a European secondary substation of that
size.

This is the finding with capital attached: it defers a physical upgrade.

> **Two corrections are folded into this number.**
>
> It was once reported as **14.1×**, which assumed every vehicle arrives at
> exactly 18:00 — a synchronised arrival maximally penalises the baseline it is
> measured against. Once arrivals stagger, charge-on-arrival hosting triples and
> most of the claimed 14× turns out to have been the assumption.
>
> It was then reported as **6.3×**, measured against a residential baseline that
> overstated household demand sevenfold (finding 11). Correcting that also
> forced the transformer ratings down: the old 1,000–1,500 kW series was chosen
> when the baseline claimed an 800 kW residential peak, and against the measured
> 89 kW it would have left the unit 7% loaded by houses, which is not a planning
> case anyone faces.
>
> When flagging that error I estimated the corrected headline at "nearer 4×".
> **That estimate was wrong** — it came from a simplified uniform fleet on the
> old oversized transformer, and should not have been extrapolated. The actual
> recompute gives **5.3×**.

Ceilings come from bisecting the solver, bounded above by an energy argument so
the search can never report its own limit as the answer — an earlier version
returned exactly 1,500 at the 1,500 kW rating, which was the bisection bound
rather than a ceiling. `solver_ceiling` raises instead of returning it, and every
published figure is checked against its own search bound.

### How far the assumptions move it

`ml/sensitivity_hosting.py` moves one assumed input at a time and re-runs the
250 kW headline with the same method (realistic fleet, 12 sampled nights,
median). The `base` row reproduces 60 → 318 = 5.3×. **This is sensitivity to
assumptions, not validation or a confidence interval**: the baseline is system
load rather than a metered feeder, so no sweep shows the true value lies in the
range, and it would not have caught the earlier structural errors (14×, 6.3×,
the 7× baseline). Ranges were written down before the run and are judgement.

| Input varied | Setting | Dumb | Coordinated | Gain |
| --- | --- | --- | --- | --- |
| **Base** | published | 60 | 318 | **5.3×** |
| Fleet draw (noise) | 20 seeds | 60-92 | 298-318 | **3.3-5.3×, median 4.1×** |
| Baseline peakiness | flat / half swing | 60 | 310 / 314 | 5.2× / 5.2× |
| | double / triple swing | 50 | 325 / 331 | 6.5× / 6.6× |
| | evening bump 0.5 / 1.0 | 40 / 30 | 310 / 305 | 7.8× / 10.2× |
| Arrivals | early / late | 60 | 321 / 302 | 5.4× / 5.0× |
| Departures | hard early / relaxed | 60 | 302 / 318 | 5.0× / 5.3× |
| Energy per car | 6 / 14 kWh | 80 / 40 | 470 / 200 | 5.9× / 5.0× |
| Chargers | all 7 kW / slow / fast | 50-60 | 319 / 312 / 320 | 6.4× / 5.2× / 6.4× |
| Homes on the unit | 100 / 150 / 300 / 400 | 70 / 70 / 30 / 20 | 384 / 352 / 246 / 175 | 5.5× / 5.0× / 8.2× / 8.8× |

What this does and does not say:

- **The 5.3× first published was the best of twenty fleet draws.** Redrawing the
  fleet from the same assumptions (seeds 0-19, nights unchanged) gives a gain
  between **3.3× and 5.3×**, median **4.1×**, with charge-on-arrival found on a
  step-1 grid (the method the table above now uses). On the original step-10 grid
  the range was 3.4-5.3×, median 4.3×, because a ceiling near 60 carried ±17% of
  quantisation. The coordinated count barely moves (298-318 vehicles, median 309);
  all of the spread is the charge-on-arrival ceiling, which ranges 60-92.
  **"About 4×, between 3.3× and 5.3×" is the honest statement**; seed 0 happened
  to be the favourable end.
- **No single input pushes it below the noise floor.** The lowest non-noise move
  is hard-early deadlines at 5.0×; every row sits inside the 3.3-5.3× band.
- **The "upper bound" caveat holds for vehicle counts, not for the ratio.** A
  peakier baseline cuts the coordinated count slightly (318 → 305 at the
  largest evening bump) but cuts charging-on-arrival capacity much faster
  (60 → 30), so the *gain rises* to 7.8-10.2×. The system-load baseline therefore
  likely understates the gain while overstating absolute headroom.
- **More homes on the unit raises the gain** (8.2× at 300 homes) because the
  houses eat the rating and arrival charging collapses first. Fewer homes does
  not lower it below ~5×.

> **Remaining caveat.** The baseline's *shape* is measured Spanish system load,
> which carries flat industrial demand and is therefore less peaky than a real
> street. That understates the evening residential peak and so overstates the
> headroom left for charging: these figures are an upper bound. Vehicles are also
> drawn from one distribution and every car can wait until morning; a fleet with
> hard early deadlines would host fewer.

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
survive the model's own error. That gate is built and measured in finding 13.

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

> **The obvious repair was tried, and made it worse.** The diagnosis points at
> pricing the optionality the controller destroys by waiting, so a deferral
> penalty was added: λ × the forecast's own MAE at that horizon is added to every
> forecast hour still ahead, which makes distant, uncertain hours look dirtier and
> removes the optimistic bias of the minimum. Same 362 nights, same controller, λ
> from 0 to 2 (`mpc.py`; the greedy solver used for the sweep reproduces the LP
> controller to 0.0000%):
>
> | λ | Mean regret | vs one-shot | Mean position |
> | --- | --- | --- | --- |
> | 0 (unmodified) | 2.615% | +0.566pp | 4.52 |
> | 0.5 | 2.951% | +0.902pp | 3.45 |
> | 1.0 | 3.675% | +1.626pp | 2.58 |
> | 1.5 | 4.578% | +2.529pp | 2.05 |
> | 2.0 | 5.627% | +3.577pp | 1.66 |
>
> Regret rises monotonically with the penalty; no λ beats the one-shot LP's
> 2.049%. The reason is in the position column. The over-deferral diagnosis
> describes the *static* arm (position 5.28, later than perfect foresight's 5.05).
> The refreshed controller that is actually compared sits at 4.52, *earlier* than
> the oracle, so it was not over-deferring on average, and pushing it earlier still
> only moves energy into dirtier hours. The penalty repairs a failure this
> controller does not have. This closes the question for this formulation: a
> deferral penalty does not rescue rolling control here. A terminal cost shaped
> differently, or a controller with the true value of waiting, remains untested.

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

Capacity on a 150-home feeder, with the load shape taken from **46,728 measured
hours** of Grid-India demand (2019-01-01 to 2024-04-30, lag-1 autocorrelation
+0.979, screened by `screen_dataset.py`) rather than drawn by hand:

| Rating | On arrival | Coordinated | Gain |
| --- | --- | --- | --- |
| 63 kVA | — | — | houses alone exceed it |
| **100 kVA** | **35** | **123** | **3.5×** |
| 160 kVA | 91 | 296 | 3.3× |
| 250 kVA | 171 | 561 | 3.3× |
| 400 kVA | 304 | 997 | 3.3× |

The gain is flat across ratings, because the arrival peak and the overnight
energy both scale with the transformer. What does not scale is the houses: 150
homes draw 57.6 kW at their own peak, past the 63 kVA unit's 56.7 kW rating, so
that unit hosts nothing at any level of coordination. Below some rating the
answer is not "coordinate" but "replace the transformer".

**Sensitivity to the homes count** (`ml/sensitivity_india.py`, 100 kVA unit,
everything else held): 100 homes → 54 on arrival / 179 coordinated = **3.3×**;
150 (base) → 35 / 123 = **3.5×**; 200 → 16 / 68 = **4.3×**. The gain holds at
3.3-4.3× across the plausible range and rises as the unit gets more loaded.
This varies one assumed input, not the fleet or the baseline shape, and is
sensitivity to an assumption, not validation.

**Capacity is seasonal, and the two mechanisms compound.** Overnight demand and
window shape both come from the measured series:

| Season | Overnight level | Peak/valley in window | Coordinated |
| --- | --- | --- | --- |
| Winter | 0.92× | 1.32 | **143** |
| Autumn | 0.93× | 1.25 | 137 |
| Spring | 1.03× | 1.13 | 118 |
| Summer | 1.06× | 1.11 | **107** |
| Monsoon | 1.07× | 1.12 | 107 |

The same transformer hosts **143 vehicles in winter and 107 in summer, a 1.34×
spread**. Summer overnight demand runs 15% higher, so there is less headroom —
*and* the window is flatter (1.11 against winter's 1.32), because air
conditioning runs all night, so there is less valley to move load into.
Coordination helps least exactly when the transformer is most stressed. Sizing
on an annual average sizes for a month that never occurs.

On the same 100 kVA unit, the Indian fleet fits 35 vehicles charging on arrival
against 13 European cars. Modelling India with European vehicles would have
understated one transformer's capacity 2.7× and aimed the fix at the wrong
problem.

> **Two parameters here were guessed first and corrected after.** The feeder
> shape was a pair of Gaussians until the measured series replaced it, which
> moved the residential peak from 32.2 kW to 15.4 kW for the same energy — the
> freehand curve was far too peaky. And homes-per-transformer was set at 40,
> leaving a 90 kW unit 17% loaded, which suppressed every seasonal effect worth
> measuring; Indian 100 kVA units are sized for 70-80 kW at 60-75% loading, so
> 150 homes is the realistic figure. Both corrections changed the answer, and
> the second changed the seasonal spread from 1.04× to 1.34×.

> **Carbon is no longer open — see finding 12.** Grid-India's aggregate tables
> are daily, but its Daily PSP Report carries a 15-minute generation-by-fuel
> sheet. Finding 7's prediction has now been tested on 555 days of it: India
> saves a median 0.12% overnight against Spain's 3.30%, on a grid 2.2× as dirty.

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

**Resolved.** The Spanish pipeline has now been recomputed. `data_sources.py`
takes its shape from 35,056 measured hours of ENTSO-E `total load actual` and
its level from IDAE's 3,487 kWh per household per year, giving 287 kWh/month
against the 291 target. 200 homes peak at **89 kW**, not 800.

That also forced the transformer ratings down. The old 1,000–1,500 kW series was
chosen for an 800 kW residential peak; against 89 kW it would leave the unit 7%
loaded by houses, which is the same mistake made in the first Indian model and
corrected there. The series is now 160–630 kW, sized to the street this actually
models.

The corrected headline is **5.3×**, not the "nearer 4×" estimated above. That
estimate came from the simplified uniform fleet in the table — a different fleet
on a differently-sized transformer — and extrapolating from it was a mistake.
The table is kept because the *mechanism* it isolates is right: holding
everything else fixed, an inflated baseline does inflate the coordination gain.
Only the extrapolated magnitude was wrong.

The Indian model (finding 10) was calibrated from the start: its profile is
scaled so the day integrates to Delhi's measured ~260 kWh/month, leaving only
the *shape* assumed. Both countries now share one method.

This is the same class of error as finding 3, where a synthetic carbon curve
turned out to be inverted. The lesson there was applied to the carbon input and
not to this one.

---

## 12. India is twice as dirty as Spain and overnight carbon-aware charging saves almost nothing there

`ml/fetch_india_psp.py`, `ml/india_carbon.py`, `ml/india_backtest.py` · **India** pane

Finding 7 predicted that a dirtier grid is not a better one to shift load in,
because value follows a grid's *shape* rather than its level. India is the test
case that prediction deserved, and it now has measured data behind it.

> **Corrected.** This finding was first written on a mislabelled series; the
> numbers below are recomputed on the repaired one (finding 14). The direction
> held and the magnitudes did not: the overnight window saves 0.12% rather than
> 0.05%, and the daytime window turns out to be worth something.

**The data.** Grid-India publishes a Daily PSP Report whose `TimeSeries` sheet
carries 96 fifteen-minute intervals of all-India generation split by fuel. It is
free, official, and needs no account — it is the primary source Electricity Maps
itself parses for Indian zones, so going straight to it gives finer resolution
than their hourly export. **53,243 fifteen-minute rows across 555 days**,
2025-04-01 to 2026-10-11; the hourly intensity derived from it has lag-1
autocorrelation +0.955 and lag-24 +0.981. Carbon intensity uses the same IPCC AR5
factors as Spain, so the two are comparable by construction rather than by
assertion. Two independent sources agree with it where they overlap (finding 14).

**India runs at 592 gCO₂eq/kWh** against Spain's 267 — about 2.2× as dirty, on a
25.1% wind, solar and hydro share of generation.

And the overnight window is the worst part of its day:

| Window | Mean intensity | Spread | Median CO₂ cut | Days under 1% |
| --- | --- | --- | --- | --- |
| **Overnight 18–07** (this project's default) | 649 | 5.9% | **0.12%** | **87.0%** |
| Daytime 09–17 | 497 | 15.6% | **1.51%** | 26.7% |
| Afternoon 12–18 | 514 | 23.7% | **0.00%** | 99.8% |
| Spain, overnight | 267 | — | 3.30% | 38.0% |

Intensity sits at about 650-660 from 18:00 through the small hours and peaks at
**660 at 03:00-05:00**, then falls to a trough of **472 at midday**, where the
solar is. India's clean hours are the middle of the day. A European charging
habit points Indian drivers at precisely the wrong end of the clock, and
scheduling inside that window recovers a median of **0.12%** — about 27× less
than Spain, on a grid twice as dirty. Finding 7 holds.

**Where there is a saving, it is in the daytime window**: 1.51% median, 1.74% mean,
and only 27% of days under 1% — twelve times the overnight figure. That is the
charging a workplace or a depot does, not the habit this project was built around,
and it is still modest next to Spain's overnight 3.3%.

**The afternoon row is the sharper lesson, and it corrects finding 7.** That
window has the *widest* spread of the three — 23.7% against the overnight
window's 5.9% — and saves **nothing at all**. Six hours barely covers what a
three-wheeler needs at 1.9 kW, so the fleet must charge almost continuously and
there is nowhere to move load to. Shape is **necessary but not sufficient**: a
scheduler needs slack as well, and the two can point in opposite directions.
Finding 7's rule as originally stated would have predicted the afternoon window
to be the best of the three. It is the worst, and the corrected data makes the
gap larger, not smaller.

**The policy reading is uncomfortable for this project's own premise.**
Carbon-aware charging is the wrong intervention for overnight India. Capacity
coordination is the right one: the same fleet on the same transformer is worth
3.5× in hosting capacity (finding 10), a real and large number, while the
overnight carbon saving rounds to a tenth of a percent. A project that exists to
schedule charging against carbon has measured its way to the conclusion that in
India it should not, at night.

> Two modelling choices are stated rather than buried. The sheet reports a single
> THERMAL column, treated here as coal at 820 — it includes some lignite at 1054,
> so this **understates** Indian intensity slightly. And storage discharge is
> excluded from the mix, since its emissions belong to whatever charged it;
> counting it as zero-carbon generation would flatter the grid. Storage is ~1.6%
> of generation, so neither choice moves much, but both should be choices.

> An earlier version of this document said hourly Indian carbon data was
> available only behind a paid API. That was wrong twice over: Electricity Maps
> publishes free hourly CSV for Indian zones, *and* the underlying Grid-India
> source used here is free and finer-grained than either.

---

## 13. Gating on the expected saving removes most of the harm, and costs nothing in Spain

`ml/spread_gate.py` · wired into the API as `gate_min_saving_pct` and the Simulator's forecast toggle

Finding 6 left a gap: scheduling on a forecast is worse than charging on arrival
on flat nights, and the remedy ("act only when the predicted spread is large")
was named but not built. The gate here computes, at 18:00, the saving it
*expects* — forecast-optimal against charge-on-arrival, both scored on the
forecast — and acts only if that is at least τ; below τ it charges on arrival.
Everything is scored against what actually happened.

**Spain**, deployed ridge forecaster, 361 held-out 2018 nights. The ungated row
reproduces the published 71.0% of achievable saving, which is the check that the
harness measures the same thing as finding 3:

| Gate τ (expected saving) | Nights acted on | Fleet-total saving | Share of oracle | Nights worse than nothing |
| --- | --- | --- | --- | --- |
| none | 100% | 7.83% | 71.0% | **27.4%** |
| 2% | 58% | 8.12% | 73.6% | 16.6% |
| 5% | 48% | 8.08% | 73.3% | 10.2% |
| **7.5%** | **41%** | **8.18%** | **74.2%** | **5.8%** |
| 15% | 27% | 6.88% | 62.4% | 3.0% |

Perfect foresight saves 11.03%. A moderate gate *removes four in five of the
harmful nights and slightly raises the total*, because the nights it skips are
the ones that were losing. Push τ too high (15%+) and it starts discarding real
savings. τ was chosen on the first 180 held-out nights and scored on the other
181 so the figure is not tuned on its own test: ungated 7.91% with 27.1% worse
nights, gated at 7.5% **8.16% with 4.4% worse**, acting on 41%.

**The expected saving is the right thing to gate on; the window spread is not.**
Gating on the forecast's (max-min)/mean — the wording in finding 6 — chose τ=15%,
acted on 62% of nights, cut worse nights only to 12.7% and *lowered* the total to
7.50%. A wide predicted spread does not mean a profitable shift: a spread can sit
in hours the charger cannot reach.

**Germany and India are a weaker test, and the result is more mixed.** Neither has
a deployed forecaster, so each uses a plain lag ridge (24-168 h lags, previous-day
mean/max/min) trained on the first 70% of its record. They are worse forecasters
than Spain's, and the three grids are not a like-for-like forecast comparison.

- **Germany** (341 nights): the plain forecaster is actively harmful ungated, a
  net **-1.23%** over the held-out span with 35% of nights worse than nothing. The
  gate turns that to roughly zero (+0.06%) by acting on 6% of nights at τ=20%,
  but the half it was scored on happened to be a good one for the ungated schedule
  (+1.45%), so out of sample the gate gave up total saving (1.45% → 0.38%) to cut
  worse nights from 32% to 4%. The selection half and the reporting half do not
  look alike, which is itself the finding: a gate tuned on one stretch of a
  non-stationary grid does not transfer cleanly.
- **India** (159 nights, on the repaired series): perfect foresight saves
  **0.05%** in total, so there is almost nothing to gate toward. The saving gate
  fires on 1% of the held-out nights; ungated scheduling loses 0.08% and the
  gated schedule loses 0.05%, and the share of nights worse than charging on
  arrival falls from 7.5% to 1.2%. This is finding 12 seen from the
  controller's side — on that grid, overnight, the right decision is almost
  always "charge on arrival".

**What this does and does not establish.** The gate is a safety measure for a
scheduler that is driven by an imperfect forecast. In Spain it is close to free;
elsewhere it mainly stops the scheduler doing damage. It does not make carbon
scheduling a large lever — the oracle ceiling is still 11% in Spain and 0.05% in
India. The Spanish result uses the project's one real forecaster; the German and
Indian results use throwaway ones, and a better German forecaster would change
that row. All grids use one identical-vehicle fleet (9.2 kWh at 7 kW), for which
a greedy fill equals the LP (cross-checked to 1e-16 on 12 nights per grid), so the
Indian fleet's real mix of scooters and rickshaws is not represented.

---

## 14. The India parser read the wrong column for 84% of days, and findings 10 and 12 were built on it

`ml/fetch_india_psp.py` · found while merging more Indian sources

Grid-India's Daily PSP workbook changed layout twice inside the archive:

| Dates | Days | Column order after DEMAND MET |
| --- | --- | --- |
| 2025-04-01 → 2026-05-05 | 399 | NUCLEAR, WIND, SOLAR, HYDRO, GAS, THERMAL, OTHERS |
| 2026-05-06 → 2026-05-31 | 26 | … THERMAL, **STORAGE**, OTHERS |
| 2026-06-01 → | 83+ | **STORAGE DEMAND**, NUCLEAR, WIND, SOLAR, HYDRO, GAS, THERMAL, STORAGE, OTHERS |

The parser used one positional map, correct only for the last layout. For the
other **425 of 508 days** every fuel was read from its neighbour's column: wind
labelled nuclear, solar labelled wind, hydro labelled solar, and — the one that
mattered — **coal labelled gas**, so the dominant generator was weighted at 490
instead of 820. Nothing failed: the values were numeric, the rows were complete,
and the series was smooth enough to pass the autocorrelation screen.

**How it surfaced.** Merging more sources, an hour-of-day profile showed "solar"
at 15.7 GW at midnight and "gas" at 125 GW. Neither is physically possible; the
raw workbook headers confirmed the shift. The two checks that would have caught
it in minutes are the ones to run on any new fuel series: each fuel's diurnal
shape (solar must vanish at night) and closure (the fuels must sum to the
sheet's own total).

**The fix.** Columns are now found by their printed header, never by position,
and a file missing a required fuel is rejected rather than filled. All cached
workbooks were re-parsed: 555 days, 53,243 rows; closure median 0 MW. Three days (2025-04-26,
2025-07-15, 2025-08-20) then failed the new physical checks and were dropped.

**Independent confirmation** that the repaired series is right, where unrelated
sources overlap:

| Check | Days | Correlation | Level |
| --- | --- | --- | --- |
| Daily mean of PSP intensity vs CEA daily-generation intensity | 500 | 0.73 | 594 vs 592 gCO₂/kWh |
| PSP hourly demand vs POSOCO daily energy met | 505 | 0.999 | ratio 0.999 |
| Kaggle hourly demand vs POSOCO daily energy met | 1,946 | 0.994 | ratio 0.993 |

**What changed (finding 12, overnight window unless stated):**

| | As first reported (mislabelled) | Repaired |
| --- | --- | --- |
| Mean intensity | 541 | **592** |
| Wind + solar + hydro share | 13.4% | **25.1%** |
| Overnight mean intensity | 567 | **649** |
| Overnight median cut / days under 1% | 0.05% / 98.4% | **0.12% / 87.0%** |
| Daytime 09-17 median cut / days under 1% | 0.57% / 78.0% | **1.51% / 26.7%** |
| Afternoon 12-18 median cut | 0.00% | 0.00% |
| Cleanest hour | 488 at midday | 472 at 12:00 |

The conclusion survives and one detail sharpens: the overnight window is still
nearly worthless, but the daytime window is a real if modest opportunity rather
than a second dead end, and the grid is dirtier than reported (2.2× Spain's, not
2.0×).

**Not affected.** Spain and Germany (different sources); hosting capacity,
including India's 3.5× (finding 10), which uses a demand shape and a fleet and no
fuel mix; the Spanish forecaster. Only the Indian carbon figures were wrong.

This is the same class of error as findings 3 and 11 — a derived input accepted
without checking that it is physically sensible — and the third time it has cost
a published number. A sheet that "looks right" is not a check; a fuel that cannot
exist at that hour is.

---

## 15. More data is not the lever for the forecasters; the day-ahead inputs are

`ml/learning_curve.py`, `ml/train_long.py`, `ml/train_india.py`

The obvious fix for a forecaster that captures 71% of the achievable saving is
more training data. Four experiments say it is the wrong place to look.

**Spain, the deployed model, 2018 test year** (`learning_curve.py`). Ridge trained
on 1, 2 and 3 years before 2018:

| Training | Rows | MAE | Share of saving captured |
| --- | --- | --- | --- |
| 2017 only | 8,760 | 26.90 | 72.8% |
| 2016-2017 | 17,544 | 23.40 | 71.0% |
| 2015-2017 | 26,114 | 23.70 | 71.0% |

Error falls from one year to two, then stops. The model is not data-starved.

**Spain, eleven years, tested on 2025** (`train_long.py`). The Spanish record was
extended from 2015-2018 to 2015-2026 (103,006 hourly rows, Energy-Charts, free,
no key). Spain's grid has changed enormously over that span — mean intensity fell
from 274 in 2015 to 132 in 2025 — so this is a test of whether history still
describes today. Ridge and gradient boosting, trained on the N years before 2025:

| Training years | Ridge MAE | Ridge captured | GBM MAE | GBM captured |
| --- | --- | --- | --- | --- |
| 1 (2024) | 20.84 | 66.1% | 24.57 | 57.1% |
| 2 | **20.27** | 66.5% | 21.58 | 63.1% |
| 3 | 20.94 | **69.2%** | 21.79 | 63.7% |
| 5 | 21.22 | 67.6% | 21.58 | 63.9% |
| 8 | 21.82 | 68.5% | 21.13 | 66.2% |
| 10 | 22.22 | 68.2% | **21.08** | 67.9% |

Ridge is best on the **most recent two to three years** and gets *worse* as older,
dirtier-grid history is added (20.3 → 22.2 MAE). Only the flexible model, which
can learn that old and new years differ, keeps improving with volume (24.6 →
21.1), and it only just catches the short-window ridge. Perfect foresight saves
11.8% on 2025, so the ceiling is about where it was in 2018. The 2015-2017 model
applied unchanged to 2025 still captures 67.0% of it: the daily solar shape that
matters for a night-time window has survived the transition.

**What does matter: the day-ahead inputs.** Moving the *same* 2015-2017 → 2018
split onto the new source, which has lags and calendar but **none of the TSO
day-ahead solar, wind and load forecasts** the deployed model uses, drops
the captured saving from **71.0% to 40.6%** (MAE 23.7 → 28.5). On that split those three
inputs are worth about thirty points of decision quality; a decade of extra
history is worth about two. The extended record alone cannot supply them for Spain.
They turned out to be obtainable without a token (Energy-Charts republishes them),
and finding 16 uses them: on the 2025 grid they are worth about eight points rather
than thirty, because solar has made the daily shape regular enough for lags to do
much of the work.

**India demand, 46,728 hours** (`train_india.py`; tested on the final 12 months):

| Features | Ridge MAPE | GBM MAPE |
| --- | --- | --- |
| Lags only | 2.52% | 2.93% |
| + calendar and holidays | **2.35%** | 2.68% |
| + 12-city weather | 2.36% | 2.82% |

Weather does not help a national day-ahead demand forecast once yesterday's and
last week's demand are known: the lags already carry the season and the heat.
Gradient boosting is worse than ridge, and training volume is flat (2.84% on one
year, 2.80% on four). Weather here is observed, which flatters it, so the real
effect would be no larger. A 2.4% MAPE from a ridge on lags and a holiday flag
is the result to keep.

**India carbon, 555 days** (trained on 2025-04 to 2026-03, tested on the rest).
Perfect foresight saves **0.06%** overnight over the test span, so there is
nothing for a forecaster to find. Every forecaster scheduled on it makes things
worse than charging on arrival (captured share between -59% and -227%), and
adding weather made the ridge worse, not better (MAE 10.2 → 11.0). The gate
turns all of them into roughly zero, which is the right answer. The thing worth
forecasting for Indian charging is demand, not carbon.

**What this changes.** The remaining accuracy gap in Spain is closed by better
*inputs*, specifically day-ahead forecasts for a modern grid, not by a bigger
history, and for India by forecasting demand rather than carbon. All of the
data behind these experiments is reproducible from the scripts above; the raw
files are not committed (`ml/data/` is gitignored).

---

## 16. On today's grid a day-ahead forecaster captures 81% of the achievable saving

`ml/fetch_spain_forecasts_ec.py`, `ml/train_modern.py`, `ml/export_grid_days_modern.py`

Finding 15 said the limit on the forecaster is its day-ahead inputs, not its history,
and that the TSO's day-ahead solar, wind and load forecasts were out of reach without
an ENTSO-E token. They were not: Energy-Charts republishes the same ENTSO-E day-ahead
series for Spain, and the day-ahead market price, back to 2015, free and without a key
(CC BY 4.0). 103,294 hourly rows, 99.6-100% complete. With them the model was rebuilt
on the grid as it is now.

**A. The new source reproduces the old result.** The deployed split (train 2015-2017,
test 2018) on the new data, with the day-ahead forecasts:

| | MAE | Share of saving captured |
| --- | --- | --- |
| Deployed model (Kaggle record) | 23.70 | **71.0%** |
| New source, with day-ahead forecasts | 15.32 | **68.9%** |
| New source, lags and calendar only | 28.49 | 40.0% |

The decision metric agrees within about two points. The MAE does not, and is not
comparable across sources: the two intensity series are built from slightly different
generation tables, so their variance differs. Captured saving is the number to trust.

**B. What the day-ahead inputs are worth depends on the grid.** Train 2022-2024, test
2025, ridge:

| Features | MAE | Captured |
| --- | --- | --- |
| Lags and calendar only | 21.06 | 68.4% |
| + day-ahead solar, wind, load | 15.62 | 75.9% |
| + day-ahead price | 15.16 | 77.4% |

On the 2018 grid the forecasts were worth about thirty points (40% to 71%). On the
2025 grid they are worth about eight, because lags alone already do well: solar has
made the daily shape regular enough that yesterday predicts today. Finding 15's
"thirty points" is true of the 2018 split and should not be carried to the modern grid.

**C. Training window**, chosen on 2024 and scored on 2025 (ridge with forecasts and price):

| Years of history | 2024 validation MAE | Validation captured | 2025 MAE | 2025 captured | GBM MAE | GBM captured |
| --- | --- | --- | --- | --- | --- | --- |
| **1** | 16.01 | 73.0% | 15.60 | **80.9%** | 15.77 | 79.7% |
| 2 | 17.14 | 72.0% | 14.65 | 78.2% | 13.60 | 82.3% |
| 3 | 16.01 | 71.6% | 15.16 | 77.4% | 12.79 | 80.7% |
| 5 | 16.28 | 73.5% | 15.39 | 76.7% | 11.95 | 79.3% |
| 8 | 17.60 | 69.2% | 16.79 | 72.4% | 11.81 | 80.5% |

One year and three tie on validation MAE (16.01); validation captured breaks the tie
toward one year. Ridge gets steadily worse as older, dirtier-grid years are added
(80.9% to 72.4%), while gradient boosting holds near 80% at every window and has a
far lower MAE (11.8 against 15.6) but no better decisions. More history again does
not help the model that can be served without scikit-learn.

**D. The deployed model**: ridge on the 2024 data alone, scored on 2025, which it has
never seen: **MAE 15.6, 80.9% of an achievable 11.81% saving**. Behind the forecast
gate (finding 13) at 7.5% it captures 80.7% and the nights worse than charging on arrival
fall from 10.0% to 2.5%. A ridge+GBM blend reaches 81.6% and is not shipped, for the
same reason as before: it needs scikit-learn at inference.

**The grid itself.** Across all 361 nights of 2025 (perfect foresight): median saving
**2.7%**, fleet total **11.8%**, 44% of nights under 1%, 22% over 20%. Against 2018's
3.3%, 10.4%, 38% and 17%: a smaller typical night and a longer tail, as a grid with
much more solar would produce. 46 of those nights are served (`era: "2025"`), with the
median-saving night as the default.

**Caveats.** The two copies of the 2015-2018 record are not identical hour by hour. Every
fuel's mean matches to the unit, and 64% of hours match exactly, but the remaining hours
differ in a way I did not run to ground: on the hourly carbon series the correlation is
only 0.63 (mean absolute difference 41 g/kWh, no time shift, same in every month). The
decision metric agrees within two points (A above), but the sources are not
interchangeable, and a live ENTSO-E pull would show which one is closer to the truth.
One test year. The Energy-Charts archive labels these series day-ahead, but
that they are the forecasts as originally issued, and never revised afterwards, cannot be
verified from here; a live ENTSO-E pull would settle it. The flat tariff component added
to the price (EUR 0.062/kWh) is the 2018 approximation, reused for 2025. And 80.9% was
reached on a model chosen with 2025 in view, though its window was fixed on 2024.

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
