# GridSense — findings

Every number here is reproducible from the scripts named beside it, against
measured ENTSO-E grid data with IPCC AR5 lifecycle emission factors. The Spanish
record is the Energy-Charts republication of ENTSO-E (CC BY 4.0), checked against
Spain's own grid operator; the Kaggle copy this project was first built on is wrong
on a third of nights (finding 17). Nothing is hand-tuned or assumed.

Regenerate everything:

```bash
cd ml
python make_corrected_energy_dataset.py  # corrected Spanish record -> data/raw/energy_dataset.csv
python backtest.py                # 1,448-night replay      -> data/backtest_nightly.csv
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

Replaying the optimizer over all 1,448 complete overnight windows of the corrected
record (finding 17):

| | CO₂ reduction vs charging on arrival |
| --- | --- |
| Median night | **2.0%** |
| Mean night | 6.4% |
| Fleet total across four years | **6.6%** |

**41% of nights save under 1%.** 61% save under 5%. 9% save over 20%. On 36% of
nights the cleanest hour in the window is 18:00, the arrival hour, so charging on
arrival is already near-optimal. By season the mean cut is 10.3% in winter, 7.8% in
autumn, 4.8% in spring and 2.7% in summer.

A single headline percentage hides both tails, which is why the dashboard reports
the distribution.

> These figures replaced 3.3% (median) and 10.4% (fleet total). Both were computed
> on an input record that was wrong for the first twelve days of every month, and
> the wrong nights carried most of the saving: nights starting on days 1-12 showed
> a 15.1% fleet saving on the old record against 6.3% on the same nights of the
> corrected one. Finding 17 has the evidence.

## 3. The synthetic curve was not merely inaccurate: it was inverted

`train.py`, `train_v2.py` · **Existing vs GridSense** pane

Real Spanish grid intensity is *lowest* at midday (solar) and *highest* in the
early morning. The synthetic curve originally shipped in `data_sources.py` peaked
at 19:00 and troughed at 13:00, roughly the opposite shape.

Evaluated by **decision regret** (schedule on the forecast, score against what
actually happened, compare to perfect foresight), on the held-out 2018 year of the
corrected record:

| Forecast | MAE | % of achievable saving captured |
| --- | --- | --- |
| Synthetic curve | 101.04 | **−34.0%** |
| Persistence (lag 24h) | 31.77 | 32.3% |
| Climatology (month × hour) | 45.09 | 55.5% |
| Ridge, first pass | 21.18 | 67.2% |
| Gradient boosting, first pass | 20.20 | 69.5% |
| **Ridge, tuned (deployed)** | **15.32** | **68.9%** |
| Ridge + GBM blend (not shipped) | 14.05 | 73.1% |

The synthetic curve scores **negative**: scheduling against it is worse than not
optimizing at all. A demo driving real chargers that way would increase emissions.

**The forecaster's edge is smaller than first reported.** On the old record the
simple baselines looked hopeless (persistence 12.8%, climatology 16.4%), which made the
ridge model's 71% look like the difference between failing and succeeding. On the
corrected record climatology alone captures 55.5%, so the model adds about 13 points
over the simplest sensible forecast, not 55. The corrupted early-month nights had
made every naive forecast look worse than it is.

The blend is the strongest candidate but is **not** what ships: it needs
scikit-learn at inference, while ridge exports as a coefficient vector scored with a
dot product and keeps the serverless bundle free of ML dependencies. Ridge gives up
4.2pp of captured saving for that. The export is verified bit-exact against sklearn.

`train_v2.py` improved ridge from MAE 21.18 / 67.2% to 15.32 / 68.9%, a 28% cut in
error, through richer features (more lags, rolling min/max/std, week-over-week drift,
renewable share) and a 48-config hyperparameter search under blocked time-series CV.
No new data was involved.

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

`export_grid_days.py`, `v2g_study.py`

The cheapest hour and the cleanest hour of a night coincide on only **18.0%** of
nights, and across a night the two curves barely correlate (mean within-night
correlation 0.15). Measured over twelve nights with 80 vehicles, minimizing cost
leaves emissions 4.3% above the emissions optimum (1,886 against 1,808 kg), and
minimizing emissions leaves the bill 4.5% above the cost optimum (€959 against €918).
Optimizing for emissions can also raise peak: 1,953 kg when minimizing peak against
1,808 kg when minimizing carbon. The dashboard shows those as increases rather than
hiding them.

## 6. Forecast error only matters when there is something to gain

`export_forecast_curves.py`, `corrected_stats.py` · **Simulator**, Carbon signal toggle

Scheduling on the day-ahead forecast and scoring against actuals, on the served
nights:

| Night | Perfect foresight | On forecast |
| --- | --- | --- |
| 2018-01-19 | 37.8% | 37.0% |
| 2018-02-13 | 31.5% | 28.6% |
| 2018-10-13 | 26.6% | 22.5% |
| 2018-06-23 | 0.0% | **−6.9%** |
| 2018-06-12 | 0.0% | **−5.7%** |
| 2018-12-03 | 0.5% | **−4.4%** |

When the curve has real structure the forecast finds most of it. When the night is
nearly flat, forecast error exceeds the differences being chased and scheduling on it
is worse than not scheduling at all: 10 of the 46 served nights end up worse than
charging on arrival. Aggregated by total mass across 2018 the forecast captures 68.9%,
which hides this split.

The operational reading: act only when the *predicted* spread is large enough to
survive the model's own error. That gate is built and measured in finding 13.

## 7. A dirtier, more variable grid saves less on a typical night and more on its best

`export_regions.py` · **Two grids** pane · Spain (ENTSO-E 2015-2018, corrected) vs Germany/Luxembourg (2023-2026)

| Grid | Mean intensity | Std | Median night saving | Mean night saving | Nights under 1% | Nights over 20% |
| --- | --- | --- | --- | --- | --- | --- |
| Spain | 254.7 gCO₂eq/kWh | 74.6 | **2.0%** | 6.4% | 41.4% | 9.1% |
| Germany | **358.4** | **135.0** | **1.0%** | **8.1%** | **50.1%** | **16.6%** |

Germany's grid is dirtier and swings harder, so it looked like the better place to
shift load. On a typical night it is worse: the median saving is half of Spain's and
half its nights offer under 1%. But its tail is fatter, so across the whole record it
saves more in total (8.2% against 6.6%). Dirtiness and variability predict the *best*
nights, not the typical one.

**My first explanation for the typical-night result was wrong** and is worth recording.
I claimed Germany's overnight hours "sit flat on lignite", so there was less
within-night shape to exploit. Measuring it directly refuted that: Germany's median
spread *inside the charging window* is **25.5%**, wider than Spain's 17.0%. More
within-window variation, less typical saving.

What explains the typical night is what the default behaviour already achieves.
Averaged over every night, 18:00, the hour everyone plugs in, is the **cleanest** hour
of the window in both grids, and Germany's advantage there is larger:

| | Arrival hour vs that grid's night mean |
| --- | --- |
| Spain | −2.7% |
| Germany | **−7.4%** |

Charging on arrival is landing on the best hour by accident, and it lands there harder
in Germany. The optimizer is measured against that baseline, so the better the
accident, the less there is left to win on an ordinary night.

The practical reading: the typical value of carbon-aware charging is set by how good
the *unmanaged* behaviour already is, not by how carbon-intensive or how volatile the
grid is. Volatility buys a longer tail of big-saving nights on top of that. See the
**Two grids** pane, which plots both shapes.

The German data was screened with `screen_dataset.py` before use (lag-1
autocorrelation 0.92-0.99 across generation, load and price).

> On the old Spanish record this finding read "a dirtier, more variable grid is not a
> better one to shift in", because Spain's median looked like 3.3% and its mean 9.6%.
> The corrected record narrows the gap on the median and reverses it on the mean.

## 8. V2G buys a cheaper bill, not carbon or peak

`v2g_study.py`, `optimize_schedule(allow_v2g=True)` · **Simulator**, vehicle-to-grid toggle

Letting vehicles discharge back to the grid improves whichever objective is selected
and quietly damages the others. Measured over twelve nights (every fourth served night)
with 80 vehicles, summed. The export cap is a policy dial, so both settings are shown:
**capped** is the shipped default of 6 kWh per vehicle per night, **uncapped** removes the
limit.

| Objective | Mode | CO₂ kg | Bill € | Mean peak kW | Exported kWh |
| --- | --- | --- | --- | --- | --- |
| Min CO₂ | Charge-only | 1,808.3 | 959.19 | 576.5 | 0 |
| | V2G capped | 1,741.1 | 978.28 | 579.6 | 3,706 |
| | V2G uncapped | **1,695.2** | 1,019.62 | 579.4 | 8,014 |
| Min cost | Charge-only | 1,886.4 | 917.91 | 493.1 | 0 |
| | V2G capped | 1,882.5 | 859.81 | 585.6 | 3,840 |
| | V2G uncapped | 1,906.3 | **812.13** | 585.7 | 7,488 |
| Min peak | all three | 1,953.3 | 999.37 | 86.7 | 0 |

(Charging on arrival: 1,950.3 kg and €1,072.65.)

- **Carbon.** Minimizing carbon with V2G cuts emissions a further 3.7% capped and 6.3%
  uncapped, and raises the bill 2.0% and 6.3%. **Carbon abatement through V2G costs
  €0.28/kg capped and €0.53/kg uncapped**, against an EU ETS price around €0.06-0.09/kg:
  three to five times too expensive capped, six to nine uncapped. As a way to cut
  carbon it is not economic, though it is closer than the "ten times" reported before.
- **Cost.** This is where V2G pays: under the cost objective the bill falls 6.3% capped
  and 11.5% uncapped, with emissions roughly unchanged (-0.2% and +1.1%).
- **Peak.** V2G does nothing. Minimizing peak already flattens the fleet to 86.7 kW,
  which is the residential baseline's own shape, so there is nothing left to discharge
  against. The earlier finding that V2G trims peak a further 13% was measured on a
  baseline that overstated household demand (finding 11) and does not survive its
  correction.
- **Capacity.** V2G adds no energy, only moves import around and loses ~10% in the round
  trip, so hosting capacity, which is bound by energy, should not move. That was verified
  on the earlier baseline and has not been re-run on the recalibrated one.

> **On the export cap.** Uncapped, the schedule cycles packs repeatedly: it prices
> carbon and money but not battery wear, and a battery that costs nothing to use is worth
> cycling until the arbitrage runs out. `max_export_kwh` caps throughput, as real V2G
> programmes do. The default is 6 kWh per vehicle per night. Degradation is out of scope
> for this project, so the cap stands in for it rather than modelling it.

> Round-trip loss (~10%) is charged entirely to the discharge leg. Splitting it across
> both legs is more physically faithful but would move every published figure by ~5%
> while changing nothing about V2G's economics, since only the round trip matters.
>
> The single-night table that stood here before depended on the night chosen: on the
> median night of the corrected record V2G changes nothing for carbon at all, because that
> night has no spread of clean hours to arbitrage.

---

## 9. Rolling-horizon control loses to the one-shot LP

`ml/mpc.py`, `ml/train_horizon.py` · **Rolling control** pane

Grid operators do not decide a whole night in advance; they re-solve as data arrives
and commit only the imminent step. Rebuilding the scheduler that way is a harder and
more defensible engineering claim than a static LP, so it was built: 362 held-out
nights, re-solving every hour, committing one hour at a time.

It is worse. Mean regret against perfect foresight rises from **2.521%** to **2.965%**,
so MPC's regret is 18% higher than the one-shot plan's. It is better on 96 nights,
identical on 142, worse on 124.

A third arm re-solves every hour but is fed only the static day-ahead forecast, so it
gains no information by waiting. It differs from each neighbour in exactly one thing:

| | mean regret | mean position |
| --- | --- | --- |
| One-shot LP | 2.521% | 5.23 |
| Rolling, static forecast | 2.499% | 5.42 |
| Rolling, refreshed forecast | 2.965% | 4.83 |
| Perfect foresight | 0% | 5.09 |

*Position* is the mean hour-index at which energy lands, 0 = 18:00, 12 = 06:00.

- **Committing hour by hour costs -0.022pp**, which is nothing.
- **Refreshing the forecast costs +0.465pp**: the better information made the schedule
  slightly worse.
- **Net +0.443pp.**

**This reverses the earlier diagnosis.** On the old Spanish record, commitment cost
+1.361pp and the refreshed forecast bought back 0.796pp, and the explanation was that
the minimum of a dozen noisy forecasts is optimistically biased, so the controller waits
too long. On the corrected record the static arm is fine and the *refreshed* controller
lands earlier than perfect foresight (4.83 against 5.09), so over-deferral does not
describe it. I do not have an explanation for why fresher information hurts. One
candidate, untested, is that splicing the near-horizon lag models onto the day-ahead
model at the crossover (horizon 6) gives inconsistent curves from hour to hour.

Forecast quality does improve with proximity, and by a lot: MAE runs from **4.96 g at
one hour ahead to 20.49 g at thirteen**, monotone, measured in `train_horizon.py`, and the
day-ahead model (MAE 15.32) beats the lag models from h=6 out. The premise of rolling
control holds. What fails is the assumption that better information per decision
outweighs making thirteen irreversible decisions instead of one, and on this data the
two effects no longer even point the way they did.

> **Two ways this comparison could have been rigged, and what was done about them.**
> The shipped day-ahead model beats the lag models from h=6 out, so a controller could be
> flattered by handing its baseline the weaker forecast at long horizons. Both arms use
> the better model at every horizon, with the crossover recorded. Separately, an early
> version let the baseline read the *true* intensity for horizons past the crossover,
> which handed the one-shot LP perfect foresight of 03:00-06:00, the cleanest stretch of
> a Spanish night. That bug made MPC look 238% worse; fixing it moved the answer
> substantially. The sign did not change, but nearly all of the magnitude did.

> **The obvious repair was tried, and made it worse.** A deferral penalty adds
> λ × the forecast's own MAE at that horizon to every forecast hour still ahead, which
> prices the optionality of waiting. Same 362 nights, same controller, λ from 0 to 2
> (`mpc.py`; the greedy solver used for the sweep reproduces the LP controller to
> 0.0000%):
>
> | λ | Mean regret | vs one-shot | Mean position |
> | --- | --- | --- | --- |
> | 0 (unmodified) | 2.965% | +0.443pp | 4.83 |
> | 0.5 | 3.013% | +0.492pp | 3.69 |
> | 1.0 | 3.216% | +0.694pp | 2.93 |
> | 1.5 | 3.634% | +1.113pp | 2.47 |
> | 2.0 | 3.945% | +1.424pp | 2.13 |
>
> Regret rises monotonically with the penalty and no λ beats the one-shot LP's 2.521%.
> Pushing a controller that already lands early (4.83) earlier still only moves energy
> into dirtier hours. This closes the question for this formulation. A terminal cost
> shaped differently, or a controller with the true value of waiting, remains untested.

Time-consistency is pinned by `test_optimizer_is_time_consistent`, and the backtest
re-checks it every run: fed perfect forecasts, the rolling machinery reproduces the
one-shot optimum to 0.0000% on every sampled night. The loss is a property of
forecasting under commitment, not an implementation artefact.

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

Finding 7 found that a dirtier grid is not a better one to shift load in on a typical
night, because value follows a grid's *shape* rather than its level. India is the test
case that prediction deserved, and it now has measured data behind it.

> **Corrected twice.** First on a mislabelled series (finding 14): the overnight
> window saves more than the 0.05% first reported, and the daytime window turns out
> to be worth something. Then again when the backtest was found to score overnight
> windows on a single calendar day instead of stitching 18:00 to 07:00 across
> midnight: 0.12% became **0.09%** and the share of days under 1% rose from 87% to
> **92.3%**. The Spanish comparison figures were also restated (finding 17).

**The data.** Grid-India publishes a Daily PSP Report whose `TimeSeries` sheet
carries 96 fifteen-minute intervals of all-India generation split by fuel. It is
free, official, and needs no account — it is the primary source Electricity Maps
itself parses for Indian zones, so going straight to it gives finer resolution
than their hourly export. **53,243 fifteen-minute rows across 555 days**,
2025-04-01 to 2026-10-11; the hourly intensity derived from it has lag-1
autocorrelation +0.955 and lag-24 +0.981. Carbon intensity uses the same IPCC AR5
factors as Spain, so the two are comparable by construction rather than by
assertion. Two independent sources agree with it where they overlap (finding 14).

**India runs at 592 gCO₂eq/kWh** against Spain's 255 — about 2.3× as dirty, on a
25.1% wind, solar and hydro share of generation.

And the overnight window is the worst part of its day:

| Window | Mean intensity | Spread | Median CO₂ cut | Days under 1% |
| --- | --- | --- | --- | --- |
| **Overnight 18–07** (this project's default) | 649 | 5.9% | **0.09%** | **92.3%** |
| Daytime 09–17 | 497 | 15.6% | **1.51%** | 26.7% |
| Afternoon 12–18 | 514 | 23.7% | **0.00%** | 99.8% |
| Spain, overnight | 255 | — | 2.00% | 41.4% |

Intensity sits at about 650-660 from 18:00 through the small hours and peaks at
**660 at 03:00-05:00**, then falls to a trough of **472 at midday**, where the
solar is. India's clean hours are the middle of the day. A European charging
habit points Indian drivers at precisely the wrong end of the clock, and
scheduling inside that window recovers a median of **0.09%** — about 22× less
than Spain, on a grid more than twice as dirty. Finding 7 holds.

**Where there is a saving, it is in the daytime window**: 1.51% median, 1.74% mean,
and only 27% of days under 1% — twelve times the overnight figure. That is the
charging a workplace or a depot does, not the habit this project was built around,
and it is still modest.

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
overnight carbon saving rounds to under a tenth of a percent. A project that exists to
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
*expects* (forecast-optimal against charge-on-arrival, both scored on the
forecast) and acts only if that is at least τ; below τ it charges on arrival.
Everything is scored against what actually happened.

**Spain**, deployed ridge forecaster, 361 held-out 2018 nights of the corrected
record. The ungated row reproduces the 68.9% of achievable saving in finding 3, which
is the check that the harness measures the same thing:

| Gate τ (expected saving) | Nights acted on | Fleet-total saving | Share of oracle | Nights worse than nothing |
| --- | --- | --- | --- | --- |
| none | 100% | 5.37% | 68.9% | **26.6%** |
| 1% | 57% | 5.48% | 70.3% | 15.2% |
| 2% | 52% | 5.58% | 71.6% | 11.9% |
| 3% | 49% | 5.67% | 72.7% | 9.7% |
| **4%** | **47%** | **5.74%** | **73.6%** | **7.8%** |
| 5% | 42% | 5.65% | 72.4% | 5.0% |
| 7.5% | 36% | 5.29% | 67.9% | 3.6% |
| 15% | 12% | 3.53% | 45.3% | 1.1% |

Perfect foresight saves 7.79%. A moderate gate *removes about three in four of the
harmful nights and slightly raises the total*, because the nights it skips are the
ones that were losing. Push τ too high and it starts discarding real savings. τ was
chosen on the first 180 held-out nights and scored on the other 181 so the figure is
not tuned on its own test: ungated 6.08% with 25.4% worse nights, gated at τ=4%
**6.32% with 6.1% worse**, acting on 49%.

> The earlier version of this table put the optimum at 7.5%. That was a property of the
> wrong record, which had larger, easier savings. On the corrected one the curve peaks at
> 4% and 7.5% already gives savings back. The shipped threshold is 4%, and the Simulator
> uses the same value.

**The expected saving is the right thing to gate on; the window spread is not.**
Gating on the forecast's (max-min)/mean, the wording in finding 6, never improved
on the ungated total in this sweep and needed a far larger τ to cut harm. A wide
predicted spread does not mean a profitable shift: a spread can sit in hours the
charger cannot reach.

**Germany and India are a weaker test, and the result is more mixed.** Neither has
a deployed forecaster, so each uses a plain lag ridge (24-168 h lags, previous-day
mean/max/min) trained on the first 70% of its record. They are worse forecasters
than Spain's, and the three grids are not a like-for-like forecast comparison.

- **Germany** (341 nights): the plain forecaster is actively harmful ungated, a
  net **-1.23%** over the held-out span with 35% of nights worse than nothing. The
  gate turns that to roughly zero (+0.06%) by acting on very few nights at τ=20%,
  but the half it was scored on happened to be a good one for the ungated schedule
  (+1.45%), so out of sample the gate gave up total saving (1.45% to 0.38%) to cut
  worse nights from 32% to 4%. A gate tuned on one stretch of a non-stationary grid
  does not transfer cleanly.
- **India** (159 nights, on the repaired series): perfect foresight saves
  **0.05%** in total, so there is almost nothing to gate toward. Ungated scheduling
  loses 0.05% and the gated schedule gives up nothing, with the share of nights worse
  than charging on arrival falling from 7.5% to under 1% (out of sample, 7.5% to 1.2%).
  This is finding 12 seen from the controller's side: on that grid, overnight, the
  right decision is almost always "charge on arrival".

**What this does and does not establish.** The gate is a safety measure for a
scheduler that is driven by an imperfect forecast. In Spain it is close to free;
elsewhere it mainly stops the scheduler doing damage. It does not make carbon
scheduling a large lever: the oracle ceiling is 7.8% in Spain and 0.05% in India. The
Spanish result uses the project's one real forecaster; the German and Indian results
use throwaway ones, and a better German forecaster would change that row. All grids use
one identical-vehicle fleet (9.2 kWh at 7 kW), for which a greedy fill equals the LP
(cross-checked to 1e-16 on 12 nights per grid), so the Indian fleet's real mix of
scooters and rickshaws is not represented.

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

The obvious fix for a forecaster that captures 69% of the achievable saving is
more training data. Four experiments say it is the wrong place to look.

**Spain, the deployed model, 2018 test year** (`learning_curve.py`). Ridge trained
on 1, 2 and 3 years before 2018:

| Training | Rows | MAE | Share of saving captured |
| --- | --- | --- | --- |
| 2017 only | 8,760 | 15.47 | 68.9% |
| 2016-2017 | 17,544 | 15.31 | 68.3% |
| 2015-2017 | 26,114 | 15.32 | 68.9% |

Three years of history do no better than one. On the old record error fell from one year
to two before flattening; on the corrected one it is flat from the start. The model is
not data-starved.

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
the captured saving from **68.9% to 40.6%** (MAE 15.3 → 28.5). On that split those three
inputs are worth about twenty-eight points of decision quality; a decade of extra
history is worth about two. The extended record alone cannot supply them for Spain.
They turned out to be obtainable without a token (Energy-Charts republishes them),
and finding 16 uses them: on the 2025 grid they are worth about eight points rather
than twenty-eight, because solar has made the daily shape regular enough for lags to do
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

**A. The corrected record reproduces the deployed result, and shows what the old one hid.**
The deployed split (train 2015-2017, test 2018) on the new data, with the day-ahead
forecasts:

| | MAE | Share of saving captured |
| --- | --- | --- |
| Old Kaggle record (superseded) | 23.70 | 71.0% |
| Corrected record, with day-ahead forecasts (deployed) | 15.32 | **68.9%** |
| Corrected record, lags and calendar only | 28.49 | 40.0% |

The old record's error was much higher (23.7 against 15.3) because a third of its nights
were wrong inputs the model could not fit. The decision metric moved by only two points
because the wrong nights were wrong in both the inputs and the targets the model was
scored on. Finding 17 has the diagnosis.

**B. What the day-ahead inputs are worth depends on the grid.** Train 2022-2024, test
2025, ridge:

| Features | MAE | Captured |
| --- | --- | --- |
| Lags and calendar only | 21.06 | 68.4% |
| + day-ahead solar, wind, load | 15.62 | 75.9% |
| + day-ahead price | 15.16 | 77.4% |

On the 2018 grid the forecasts were worth about twenty-nine points (40% to 69%). On the
2025 grid they are worth about eight, because lags alone already do well: solar has
made the daily shape regular enough that yesterday predicts today. The 2018 figure should
not be carried to the modern grid.

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
gate (finding 13) at 4% it captures 80.9% and the nights worse than charging on arrival
fall from 10.0% to 4.5%. A ridge+GBM blend reaches 81.6% and is not shipped, for the
same reason as before: it needs scikit-learn at inference.

**The grid itself.** Across all 361 nights of 2025 (perfect foresight): median saving
**2.7%**, fleet total **11.8%**, 44% of nights under 1%, 22% over 20%. Against 2018's
2.0%, 6.6%, 41% and 9%: a slightly larger typical night and a much longer tail, as a grid
with much more solar would produce. 46 of those nights are served (`era: "2025"`), with the
median-saving night as the default.

**Caveats.** The two copies of the 2015-2018 record disagreed, and finding 17 settles
which was right: Energy-Charts. This finding's 2025 numbers never touched the Kaggle copy
and are unaffected. One test year. The Energy-Charts archive labels these series day-ahead, but
that they are the forecasts as originally issued, and never revised afterwards, cannot be
verified from here; a live ENTSO-E pull would settle it. The flat tariff component added
to the price (EUR 0.062/kWh) is the 2018 approximation, reused for 2025. And 80.9% was
reached on a model chosen with 2025 in view, though its window was fixed on 2024.

---

## 17. The Spanish record this project started on is wrong on a third of its nights

`ml/make_corrected_energy_dataset.py`, `ml/fetch_spain_ec.py`, `ml/corrected_stats.py`

Finding 16 left a loose end: the Kaggle copy of the 2015-2018 Spanish ENTSO-E record and
the Energy-Charts copy of the same series agreed on every fuel's mean but only matched
exactly in 64% of hours. The hourly carbon correlation between them was 0.63. I assumed
the difference was a rounding or aggregation artefact. It was not.

**The evidence.** Spain's own grid operator (REE, REData API) publishes official daily
generation. Taking the median gap between each source's daily total and REE's:

| Days of the month | Kaggle vs REE | Energy-Charts vs REE |
| --- | --- | --- |
| 1-12 | **11.1%** | 7.2% |
| 13-end | 5.5% | 7.1% |

Energy-Charts is steady across the month, about 7% under REE, which is cogeneration the
public series does not include. Kaggle is as good as Energy-Charts on days 13 onward and
twice as far from REE on days 1-12. The first twelve days of each month in the Kaggle file are wrong; the
cause I do not know.

**What it did to the published numbers.** Nights starting on days 1-12 carried most of the
saving: 15.1% fleet-wide on the old record, 6.3% on the same nights of the corrected one.

| | Old record | Corrected |
| --- | --- | --- |
| Median night saving | 3.3% | **2.0%** |
| Fleet total | 10.4% | **6.6%** |
| Nights under 1% | 38% | 41% |
| Forecaster share of saving captured | 71.0% | 68.9% |
| Climatology baseline captured | 16.4% | 55.5% |
| MPC regret vs one-shot | +1.36pp commitment cost | commitment free, refresh +0.47pp |
| V2G abatement cost vs ETS | ten times too dear | three to nine times too dear |

**What was rebuilt.** `make_corrected_energy_dataset.py` writes the Kaggle schema from
Energy-Charts generation and day-ahead series (the original is kept as
`energy_dataset_kaggle.csv`), and every Spanish number in this document was re-run on it:
the backtest, both forecasters, the gate, the learning curve, rolling control, the V2G
study, the cost-versus-carbon comparison, the Germany comparison and the served nights.

**What it did not touch.** Hosting capacity (finding 1) runs on the feeder and charger
model and never used Spanish carbon. Germany, India and the 2025 era come from other
sources. Findings 4, 10, 11 and 14 are unaffected.

**What I did not establish.** Why the early-month days are wrong: it looks like a join or
aggregation error in the Kaggle build, but I have not seen the build. Whether Energy-Charts
has errors of its own: it is 7% under REE throughout, which fits cogeneration, and
consistent, but I only checked totals, not hourly shape. And the dataset the Kaggle copy
came from is widely used, so other work built on it carries the same problem.

**Lesson.** A source that agrees on means and fails on correlation is not agreeing. I saw
the 0.63 correlation in finding 16 and wrote it down as a caveat rather than chasing it.
That caveat was moving the headline by a third.

---

## 18. The average signal and a marginal one only loosely agree

`ml/marginal.py` · **Signals & value** pane · `GET /api/marginal`, `signal: "marginal"` on the scenario API

GridSense schedules against *average* carbon intensity. Shifting load moves the *marginal* plant, which
WattTime publishes as MOER behind a paid plan. This estimates a marginal rate from the same public
data instead: the slope of dispatchable-plant emissions against residual load (demand minus wind and
solar), from hour-to-hour differences, per season and 3-hour block, bounded by the dirtiest dispatchable
fuel. **It is a proxy, not MOER.**

| Grid | Overnight mean, average | Overnight mean, marginal | Correlation | Median fit R² |
| --- | --- | --- | --- | --- |
| Spain | 258 | 214 | 0.49 | 0.43 |
| Germany | 399 | 237 | -0.14 | 0.45 |
| India | 656 | 561 | 0.08 | 0.86 |

The two signals only loosely agree. Over every complete overnight window, judged on the *marginal* proxy
instead of the average it was built on:

| Grid | Built on average, judged on average | Built on average, judged on marginal | Built on marginal, judged on average |
| --- | --- | --- | --- |
| Spain | 2.0% | **-19.2%** | 0.0% |
| Germany | 1.0% | 0.0% | 0.0% |
| India | 0.0% | 0.0% | -2.6% |

**How much to believe the Spanish -19%.** Not much, yet. The fit is modest (R² 0.43), and the figure rests on
a few evening blocks being estimated far cleaner than the rest of the night (winter 21:00-23:00 carries a
standard error of about 61 g on an estimate near 98). Charging on arrival lands on exactly those hours, so it
wins under the proxy. That is a reason to want a real MOER series, not a finding that carbon scheduling is
harmful. What the table supports is narrower: **Germany and India are unchanged**, and in Spain the
conclusion depends on which signal is used.

What it does not do: see transmission limits, outages or imports; treat each season and hour block as one
regime; or replace MOER. The API serves the Spanish 2018-era nights with `signal: "marginal"` and refuses it
elsewhere.

---

## 19. An avoided transformer upgrade is worth thousands of rupees per neighbourhood, with wide error bars

`ml/export_upgrade_inputs.py`, `backend/app/upgrade_value.py` · **Signals & value** pane · `GET /api/upgrade-value`

For an Indian neighbourhood of N vehicles on one transformer (150 homes), find the smallest standard rating
that hosts N when cars charge on arrival and the smallest that hosts N when coordinated (finding 10), and price
the difference. At 100 vehicles that is 250 kVA against 100 kVA: **about ₹1.15 lakh avoided in the base case,
a range of ₹24,000 to ₹2.07 lakh**, about ₹1,155 a vehicle, with installed cost taken as 1.5 times the
equipment price.

Three things limit it, and the pane shows them:

- **The prices are vendor asking prices** from IndiaMART listings (₹1.7-3.5 lakh for 100 kVA, ₹1.8-4.5 lakh
  for 200 kVA). I found no CEA or DISCOM schedule of rates. Only those two ratings are anchors; the rest are
  extrapolated.
- **The installation multiplier is a guess**, exposed as a slider.
- **Hosting counts come from a modelled fleet**, not measured sessions.

The saving arrives in steps. At 30 vehicles both approaches fit a 100 kVA unit and coordination avoids
nothing; the answer is zero until the neighbourhood crosses a rating. Above about 300 vehicles charging on
arrival exceeds every rating modelled, so the avoided cost cannot be priced from this table.

---

## 20. Training the forecaster for the decision does not beat the plain ridge

`ml/train_decision_aware.py`, `ml/bootstrap_blend.py`

The deployed forecaster minimises squared error over all 24 hours, but the scheduler only uses the overnight
window and only cares about the ordering of hours inside it. Four changes aimed at that were tried, selected on
2024 and reported on 2025, scored by the share of the achievable saving captured (finding 3):

| Variant | 2024 valid (train 2023) | 2025 (train 2024) | 2025 (train 2022-24) | 2018 (train 2015-17) |
| --- | --- | --- | --- | --- |
| Ridge (deployed) | 73.0% | **80.9%** | 77.4% | 70.6% |
| Overnight hours only | 73.4% | 79.7% | 74.9% | 70.0% |
| One ridge per hour | 73.9% | 78.9% | 77.8% | 69.4% |
| Per hour + residual load | 73.2% | 78.0% | 77.7% | 68.3% |
| Ridge + residual load | 73.3% | 81.0% | 77.2% | 69.5% |
| Gradient boosting | 73.1% | 80.2% | 81.2% | 69.8% |
| Blend: per-hour ridge + gradient boosting | **75.9%** | 80.7% | 80.6% | 72.0% |

Nothing moves the result by more than the noise between folds. Training on the window hours, one model per
hour, and adding the day-ahead residual load (load minus solar minus wind) each did no better than the plain
ridge and sometimes worse. The blend is the only variant at or above the ridge on three of four folds, so it was
tested properly with a paired bootstrap over nights (2,000 resamples):

| Fold | Ridge | Blend | Difference | 95% interval |
| --- | --- | --- | --- | --- |
| 2018 (train 2015-17) | 70.6% | 72.0% | +1.4pp | -2.5 to +5.4 |
| 2025 (train 2024) | 80.9% | 80.7% | -0.2pp | -2.6 to +2.2 |
| 2025 (train 2022-24) | 77.4% | 80.6% | +3.2pp | +0.4 to +6.4 |

Only one of three intervals excludes zero, and that is the fold with the longest, dirtiest history, where
finding 16 already showed the ridge does worst. **So the deployed ridge stays.** The forecaster is limited by what
the inputs say about tomorrow, not by how it is fitted, which is what finding 15 said about data volume and
finding 16 about the day-ahead inputs. The blend is not worth giving up a model that serves as a coefficient
vector for a gain this size.

Caveats: one test year per fold and about 360 nights each, so the intervals are wide; one feature set and one
hyperparameter choice per model family; and the 2018 ridge here (70.6%) differs from finding 3's 68.9% because
the feature set includes the day-ahead price, which finding 3's deployed model did not.

---

## 21. Real streets validate the hosting-capacity headline: Spain matches, the UK is higher

`ml/validation/` · **Validation** pane · `GET /api/validation`

Finding 1's headline rests on a *modelled* residential baseline: system load scaled to a street. This replaces
it with real streets, built as the sum of 200 homes drawn from public smart-meter panels, and re-runs the
250 kW hosting-capacity search with exactly the same fleet, seed and method (finding 1's `base` row), changing
only the baseline. Regions are kept apart because the evidence differs.

| Region | Evidence | Homes | Real winter evening peak | Model baseline | Gain, model | Gain, real streets |
| --- | --- | --- | --- | --- | --- | --- |
| **Spain** | GoiEner (Basque Country and Navarre), raw panel, 2018, CC BY 4.0 | 7,084 | 0.43 kW/home at 22:00 | 0.45 kW at 13:00 | 5.3× | **4.9-5.0×** |
| **UK** (the "others") | Low Carbon London, raw panel, 2013, flat tariff, CC BY 4.0 | 4,018 | 0.80 kW/home at 19:00 | 0.45 kW at 13:00 | 5.3× | **10.0-10.7×** |
| **India** | Prayas eMARC *published figure*, not raw data | 115 metered | 0.20-0.25 kW/home at 21:00 | 0.38 kW at 11:00 | 3.5× | **3.2-3.3×** |

(Real-street gains are the p10, median and p90 streets in winter, on a step-1 search grid.)

- **Spain: the headline holds.** The modelled baseline peaks at 13:00; real Spanish homes peak at 22:00 and are far
  more peaked (peak-to-trough 2.6 against 1.4). The shape was wrong, but the gain on real streets, 4.9-5.0×, sits
  inside the model's own fleet-draw noise band (3.3-5.3×). Charge-on-arrival hosts slightly *more* on real streets
  (70 against 60), because the evening peak falls after most cars have arrived.
- **UK: coordination is worth about twice as much.** English homes peak at 19:00, as cars arrive, so charge-on-arrival
  hosts only 20-30 vehicles on a 250 kW unit against 60 in the model, while coordinated charging still hosts
  257-279. This is the direction the sensitivity sweep predicted for a peakier baseline (7.8-10.2×).
- **India: no open household data exists**, so this is a published-figure check and is labelled that way. Setting the
  baseline to Pune's published evening peak (a quarter to a half below the model's Delhi-based level) raises the
  absolute capacity (35 to 54-63 on arrival on a 100 kVA unit) and leaves the gain at 3.2-3.3× against 3.5×.
  The model's India baseline also peaks at 11:00 where real evening peaks sit at 21:00, which is the same shape
  error Spain's had.
- **India, predicted baselines.** To go beyond one assumed shape, the real Spanish and UK evening-peaking profiles were
  rescaled to Indian demand and run on the 100 kVA unit. At Pune's published level they give **3.5-3.7×**, so the
  gain does not depend on the shape. At Delhi's higher consumption they nearly fill the unit before any car arrives
  (5 vehicles on arrival for the UK shape), so the ratio is a tiny-denominator artefact and is marked n/m; the
  coordinated capacity stays at 115-219 vehicles throughout. These are predictions from borrowed shapes and cannot
  confirm India.
- **Street-to-street variation is small.** Winter peak per home across random streets of 200 homes spans 0.39-0.48 kW
  in Spain and 0.74-0.87 kW in the UK, so a single random street is a fair stand-in for the region.

**What this validates and what it does not.** It validates the *baseline*, the input the finding itself flagged as
the weakest. It does not validate the fleet (arrival times, energy per car, charger mix): no open charging-session
data was obtainable without an account, and the sensitivity sweep still stands for those. The comparison is
within each region, never across: the regions use different transformer sizes and fleets, and the UK and Spanish
panels contain homes without EVs, to which the modelled fleet is added. Spanish data is from the north (a
heating-dominated, cooler climate than most of the country), the UK data is from 2013, and every profile is a
mean day, the same representation the model uses.

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
full re-run with 40 features instead of 25, it is worth **−0.6pp** of captured
saving at the same MAE: very slightly *worse*. The reason is clean — the dataset already carries
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
  `src/carbon.py` estimates a system marginal rate (see `src/carbon.py` for the marginal
  estimate against the 255 gCO₂eq/kWh average) but the served series is the average. Closing this needs MOER data.
- **The residential baseline is the one remaining synthetic input.** ENTSO-E
  reports system-wide load, which cannot be scaled to a single feeder without an
  assumption.
- **All vehicles in a scenario are identical.** The optimizer supports
  heterogeneity; the API does not expose it.
- **Spain, not California.** Chosen because Spanish households are billed at
  genuinely hourly-varying prices (PVPC), which is the premise the cost objective
  depends on.
