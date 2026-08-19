# GridSense — carbon-intensity forecasting

Replaces the hand-tuned synthetic carbon curve in `backend/app/data_sources.py`
with a model trained on real grid data, and measures how much the optimizer's
claimed benefit survives contact with that data.

## Data

[ENTSO-E Spain, 2015-2018](https://www.kaggle.com/datasets/nicholasjhana/energy-consumption-generation-prices-and-weather)
(Kaggle, CC0). 35,064 hourly rows: generation by 20 fuel types, actual and
day-ahead load, day-ahead solar/wind forecasts, day-ahead and settled prices.

Carbon intensity is not a column in the dataset — it is derived in
[`src/carbon.py`](src/carbon.py) as the generation mix weighted by IPCC AR5
lifecycle emission factors, the same construction ElectricityMaps uses.

> **Average, not marginal.** This yields the intensity of the *average* kWh.
> GridSense's premise is *marginal* emissions — the intensity of the *next* kWh,
> which is what actually changes when load moves. `estimate_marginal_intensity`
> derives a marginal figure by regressing hourly ∆emissions on ∆load
> (228 vs 267 gCO2eq/kWh average), but the forecasting work below models the
> average series. Closing that gap needs real MOER data.

## Headline finding: the shipped curve is not merely inaccurate, it is inverted

Real Spanish grid intensity is **lowest at midday** (solar) and **highest in the
early morning**. The synthetic curve in `data_sources.py` peaks at 19:00 and
troughs at 13:00 — roughly the opposite shape.

Backtesting the real optimizer over all 1,444 complete overnight windows
(`backtest.py`, 18:00→07:00, 80 EVs):

| | CO2 reduction vs naive |
| --- | --- |
| Claimed by the demo (synthetic curve) | **32.4%** |
| Real data, median night | **3.3%** |
| Real data, mean night | 9.6% |
| Real data, fleet total across 4 years | **10.4%** |

The saving is real but long-tailed: **38% of nights save under 1%**, 57% save
under 5%, while 17% save over 20%. On 33% of nights the cleanest hour in the
window is 18:00 — the arrival hour — so naive charging is already near-optimal.

## Forecasting

Day-ahead setup: a forecast is issued at 23:00 on day D for all 24 hours of day
D+1, using only TSO day-ahead solar/wind/load forecasts, calendar features, and
carbon-intensity lags ≥ 24h. Temporal split — train 2015-2017, test 2018. No
shuffling.

Accuracy alone is the wrong yardstick, because the optimizer only needs the
*ranking* of hours to be right. `train.py` therefore also reports **decision
regret**: schedule on the forecast, score against actuals, compare to perfect
foresight.

| Forecast | MAE | RMSE | % of achievable saving captured |
| --- | --- | --- | --- |
| Shipped synthetic curve | 97.20 | 124.64 | **−26.8%** |
| Persistence (lag 24h) | 44.32 | 59.98 | 12.8% |
| Climatology (month × hour) | 56.01 | 68.49 | 16.4% |
| Gradient boosting | 28.51 | 37.09 | 67.5% |
| **Ridge** | **28.27** | **36.02** | **68.5%** |

Two results worth dwelling on:

1. **The synthetic curve scores negative.** Scheduling against it is *worse than
   not optimizing at all* — it reliably steers charging into hours it believes
   are clean and the real grid does not. A demo driving real chargers this way
   would increase emissions.
2. **Ridge matches gradient boosting.** Given the tie, the linear model wins on
   deployability: it exports as 15 coefficients and an intercept, so the API
   scores a forecast with a dot product and needs no scikit-learn in the
   serverless bundle. The export is verified bit-exact against sklearn.

## Artifacts

| File | Size | Purpose |
| --- | --- | --- |
| `artifacts/ridge_forecaster.json` | 1 KB | Coefficients + intercept for dependency-free inference |
| `artifacts/real_daily_curves.json` | 133 KB | 364 measured 2018 daily curves — lets the demo show real grid days |
| `artifacts/carbon_profile.json` | 4 KB | Mean intensity by month × hour (climatology fallback) |
| `artifacts/metrics.json` | 1 KB | The tables above, machine-readable |

`real_daily_curves.json` is the recommended default for the demo: real measured
data, no API key, no model at serve time, and the numbers reproduce the backtest
exactly.

## Shipping it

`export_grid_days.py` writes `backend/app/data/grid_days.json`, which is what the
live API now serves. Two details there are load-bearing:

- **Nights are stitched, not calendar days.** A charging night runs 18:00→07:00
  and spans two dates, so indices 0-7 come from the *following* morning. Slicing
  a single calendar day instead would splice an evening onto its own morning and
  the API's figures would stop matching this backtest.
- **The shipped subset is sampled along the saving distribution, not by date.**
  Taking every Nth calendar date pulled the retained median to 1.0% against the
  true 3.3%, because saving is not evenly spread through the year. Sampling
  systematically along the sorted distribution preserves the median and both
  tails by construction. Nothing is dropped for looking bad — and the default
  night is the median, not the best.

## Running

```bash
cd ml
python -m venv venv && ./venv/Scripts/python -m pip install -r requirements.txt
kaggle datasets download -d nicholasjhana/energy-consumption-generation-prices-and-weather \
  --unzip -p data/raw

python explore.py         # data quality + carbon derivation sanity check
python analyze_window.py  # how much shifting headroom exists overnight
python backtest.py        # replay the optimizer over 1,444 real nights
python train.py           # train, evaluate, export artifacts
```

## Keeping the dashboard in sync

`export_evidence.py` writes `frontend/src/data/evidence.json`, which the
dashboard's **Existing vs GridSense** pane renders. Every figure there is
*derived*, never transcribed: forecast scores come from `artifacts/metrics.json`,
the savings distribution from the 1,444-night backtest, and the LP-vs-greedy
comparison is recomputed on each run.

So after changing the model, the optimizer, or the data, re-run in order:

```bash
python train.py            # refresh artifacts/metrics.json
python backtest.py         # refresh data/backtest_nightly.csv
python export_grid_days.py # refresh the days the API serves
python export_evidence.py  # push all of it into the dashboard
```

Nothing in the comparison pane is hand-typed, so the UI cannot silently drift
from the analysis behind it.
