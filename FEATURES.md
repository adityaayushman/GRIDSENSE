# GridSense — feature list

Current state of the repo. Findings and their reproduction steps live in
[FINDINGS.md](FINDINGS.md).

**Live:** https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app

---

## Core optimization engine — built, tested

- LP charge scheduler (PuLP/CBC) assigning each vehicle's hourly power across a
  24-hour horizon.
- Three objectives: minimize **grid CO₂**, cost, or peak load.
- Constraints: total energy delivered by the deadline, per-hour power ≤ charger
  rating, charging only inside the arrival→deadline window (overnight wraparound
  handled), and an optional **shared feeder-capacity limit**.
- **Vehicle-to-grid**: vehicles may discharge back to the grid, with state of
  charge tracked hour by hour along the plug-in window, an owner's reserve that
  is never breached, round-trip losses charged to the export leg, and a cap on
  nightly throughput standing in for battery wear.
- An over-tight feeder limit returns a planning answer, not `Infeasible` —
  `max_deliverable_kwh` bounds what fits under the limit and the error reports
  both numbers.
- Naive-schedule simulator for the "before" case.
- **105 tests** (optimizer, ENTSO-E parser and the HTTP API), including regression guards for the defects found in this
  codebase: the cost objective silently having no price curve, the LP matching
  greedy whenever no constraint couples vehicles, and every ENTSO-E parse
  failure mode that would otherwise return a plausible but wrong curve.

## Data layer — built

- Serves **measured** Spanish grid data from `backend/app/data/grid_days.json`:
  carbon intensity derived from the ENTSO-E generation mix weighted by IPCC AR5
  lifecycle factors, and day-ahead market price plus the flat PVPC access
  component.
- 46 measured charging nights, sampled along the saving distribution so the
  retained median matches the full year's.
- Nights are stitched 18:00→07:00 across two calendar dates, matching the
  backtest construction.
- Only the residential baseline remains synthetic — ENTSO-E reports system-wide
  load, not one feeder's share.

## Backend API — built

- FastAPI. `POST /api/scenario` takes EV count, charger rating, arrival/deadline
  hours, objective, region, **measured night**, and **feeder capacity**; returns
  hourly naive vs optimized load, carbon intensity, price, peak/CO₂/cost deltas,
  and how far naive breaches the feeder.
- `gate_min_saving_pct` (optional) turns on the **forecast gate**: when scheduling
  on the day-ahead forecast, charge on arrival unless the forecast expects at
  least that saving. The response reports whether the gate was applied, whether
  it acted, the saving it expected, and — when it is ignored (cost/peak
  objective, feeder limit, V2G, or no forecast) — why. The Simulator exposes it
  as a toggle beside the carbon-signal switch. See FINDINGS.md finding 13.
- `GET /api/days` lists the nights available to simulate.
- `GET /api/health`. Swagger at `/docs`.
- CORS via an exact allowlist **and** an anchored origin pattern, since Vercel
  mints a new hostname per preview deploy.

## Frontend dashboard — built

Four deep-linkable panes:

- **Simulator** — scenario controls (EVs, charger rating, feeder capacity,
  measured night), a hero number that follows the selected objective, grid-load
  and carbon-intensity charts, and a grid-strain banner when naive breaches the
  transformer.
- **Existing vs GridSense** — capability matrix against charging-on-arrival and
  a synthetic-curve optimizer, decision-regret chart, savings distribution, and
  the LP-vs-greedy coupling table.
- **Grid headroom** — EV adoption sweep against transformer ratings, and the
  hosting-capacity table.
- **Two grids** — Spain against Germany on the same optimizer, with the average
  shape of a charging night in each, and a table of the statistics that predict
  the saving wrongly.

Charts plot the night in real sequence and use step interpolation, since an
hourly schedule is piecewise-constant. Series colours are validated against the
data-viz lightness/CVD/contrast gates. Reductions that go negative render as
increases rather than as a minus sign.

## Analysis — built

In `ml/`, all reproducible:

| Script | Produces |
| --- | --- |
| `explore.py` | Data-quality pass, carbon derivation sanity check |
| `analyze_window.py` | Shifting headroom inside the charging window |
| `backtest.py` | 1,444-night replay of the optimizer |
| `train.py` | First-pass forecaster, accuracy + decision regret |
| `train_v2.py` | Tuned sweep with/without weather |
| `export_forecaster.py` | The deployable ridge coefficients |
| `screen_dataset.py` | Gate a candidate dataset before training on it |
| `export_grid_days.py` | The nights the API serves |
| `export_evidence.py` | The **Existing vs GridSense** pane's figures |
| `export_hosting_capacity.py` | The **Grid headroom** pane's figures |
| `export_regions.py` | The **Two grids** pane's figures |

Nothing in either evidence pane is hand-typed — re-running the exporters updates
the site, so the UI cannot drift from the analysis.

## Live data — built, token-gated

`backend/app/entsoe.py` fetches actual generation per production type from the
ENTSO-E Transparency Platform and derives carbon intensity with the same IPCC
AR5 factors as the bundled data, so live and offline series are directly
comparable (cross-checked across all 19 production types).

Set `USE_LIVE_DATA=true` and `ENTSOE_TOKEN`; regions ES, FR, DE, PT. The token
is issued free on request by ENTSO-E, so this ships unexercised against the live
endpoint — but the parser, the factor mapping and the failure modes are covered
by 11 tests against fixtures.

> This replaced a WattTime stub. WattTime covers North American balancing
> authorities, so enabling it against a Spanish grid would have silently mixed
> continents.

## Day-ahead forecasting — built and serving

The simulator has a **Carbon signal** toggle. *Perfect foresight* schedules
against the measured curve — an upper bound no real scheduler can reach.
*Day-ahead forecast* schedules against what the deployed ridge model predicted
the evening before, while still scoring the result against what actually
happened.

That gap is the honest cost of not knowing tomorrow. On the default night it is
2.6% → **0.0%** (a nearly flat night, where the gate would hold back); aggregated across 2018 the forecast captures **68.9%** of the
achievable saving.

Predictions are precomputed per night by `ml/export_forecast_curves.py`, so
serving stays a lookup and the function bundle carries no ML dependency. The
carbon chart overlays the forecast the scheduler saw against the actual curve.

> Per-night behaviour is uneven in a way worth knowing: on nights with a large
> achievable saving the forecast captures 92-98% of it, but on nearly flat
> nights forecast error exceeds the real spread and scheduling on it can do
> worse than nothing. A production system should act only when the predicted
> spread is worth acting on. `ml/spread_gate.py` measures that gate (finding 13):
> in Spain gating on the expected saving cuts the harmful nights from 27% to 6%
> and raises the total slightly (τ = 4%). It is wired into the API (`gate_min_saving_pct`) and
> the Simulator's forecast toggle.

## Rolling-horizon control — built, and measured as a negative result

`ml/train_horizon.py` trains one ridge per forecast horizon, h = 1..13, so the
question "does waiting buy better information?" is answered with a number rather
than an assumption. It does: MAE runs **4.96 g** at one hour ahead to **20.49 g**
at thirteen, monotone.

`ml/mpc.py` then rebuilds the scheduler the way grid operators actually run —
re-solve every hour on refreshed forecasts, commit only the next hour — and
replays it over 362 held-out nights against the one-shot LP and perfect
foresight. **It loses** (regret 2.965% against the one-shot's 2.521%), and the loss
decomposes: hour-by-hour commitment is free (**−0.022pp**) while the refreshed forecast
makes things slightly *worse* (**+0.465pp**), for a reason I have not found.

The **Rolling control** pane presents this, including the reversal of
the earlier diagnosis and the bug that nearly inflated it — a baseline that was
accidentally reading true intensities at long horizons. Kept as a shipped pane
because a project that only displays its successes is a brochure.

> A deferral penalty (λ × the forecast's MAE added to hours still ahead) was
> then tried, λ from 0 to 2, and raised regret monotonically (3.0% → 3.9%, against
> the one-shot's 2.5%). See finding 9.

## Infrastructure — built

- One Vercel project serving **both tiers**, built from GitHub on every push:
  `/api/*` routes to a Python serverless function, everything else to the static
  Vite output. Same origin, so CORS is not load-bearing in production and the
  frontend needs no API hostname baked in at build time.
- Dockerfile + `render.yaml` maintained as a container alternative (deployable,
  not currently deployed).
- GitHub Actions CI — backend tests and frontend build on every push.
- `requirements.txt` is runtime-only; tests install `requirements-dev.txt`.

---

## Added since the first release

- **Forecast gate** (`gate_min_saving_pct`) on the API and a Simulator toggle.
- **Mixed fleets**: `fleet` takes groups of identical vehicles (scooters,
  rickshaws, cars) with their own energy, charger rating and window. The Simulator's
  Fleet switch sends India's FADA mix (56% scooters, 35% rickshaws, 8% cars).
- **Optional run persistence**: set `DATABASE_URL` and every scenario is recorded;
  read them back at `GET /api/runs` and in a Recent runs panel (hidden when off). Off by default; SQLAlchemy and a driver are
  in `requirements-db.txt`, not the runtime requirements. A failed write never
  fails a simulation.
- **Styled error and empty states** in the Simulator, which tell "cannot reach
  the API" from "that scenario cannot be scheduled" from "the solver failed".
- **Frontend linting** (`npm run lint`, run in CI), clean.
- **A merged India dataset**: 74,784 hourly rows by 184 columns from five sources,
  with provenance flags and cross-source agreement checks (`ml/build_india_dataset.py`).
- **Physical sanity checks in the India fetcher**, so a mislabelled fuel column is
  rejected at the door (finding 14).

- **A modern grid era.** The Simulator's Grid switch serves 46 nights of 2025 beside the
  original 2018 record (`era` on the API), with a day-ahead forecaster trained on
  2024 that captures 80.9% of the achievable saving on a year it never saw (finding 16).
- **A keyless live feed for India.** `GET /api/india/live` returns the newest day of
  Indian grid carbon intensity from Grid-India's daily report (no account, no key, about
  2.5 s uncached, cached after), shown in the India pane with its age. Columns are found by
  header, and a report that fails the physical checks is refused. `ml/live_check_india.py`
  tests it end to end against the real portal in one command: reachable, fresh,
  plausible, two independent parsers agree to 0.00 g/kWh, and fast.
- **A one-command live check of the ENTSO-E client** (`ml/live_check_entsoe.py`), which
  needs only a token; `backend/ENTSOE.md` has the signup steps and a ready-to-send email.

## Not yet built

Blocked on something outside the code (each was attempted):

- **Real inputs for the hosting-capacity figure** (charging sessions for this
  fleet, a metered feeder). `ml/sensitivity_hosting.py --feeder-csv --sessions-csv`
  re-runs the headline on them the moment they exist. ACN-Data is US cars and needs
  a free account. Spain's regulated residential profile (REE's P2.0TD coefficients)
  is the right open source for the baseline shape, but a search found the
  methodology documents and not a downloadable file; fetching it needs the exact
  REE/e-sios URL or a token.
- **A live test of the ENTSO-E client**, which has run only against fixtures. Needs a
  free ENTSO-E token that only the account holder can request (`backend/ENTSOE.md`).
- **Marginal rather than average carbon intensity.** Needs MOER data this
  project does not have; an estimate built from the generation mix would be a
  modelling exercise of its own, not the measurement the limitation asks for.
- **The rupee value of avoided transformer upgrades.** Needs a sourced price list.
  A search found one undated vendor quote (about Rs 2.65 lakh incl. GST for 100 kVA)
  and tender notices without award prices, which is not enough to put a figure on
  a headline. The route is a DISCOM letter-of-award for 100, 160 and 250 kVA units.

## Out of scope

Public DC fast-charging and depot fleets; battery degradation; transmission-level
market analysis; hardware-level transformer simulation; full cost-benefit
analysis of grid upgrades.

- **Signals & value pane.** An estimated marginal-emissions signal from public data (`/api/marginal`,
  `signal: "marginal"` on the scenario API) and a rupee range for the transformer upgrade coordinated charging
  avoids (`/api/upgrade-value`). Both are labelled estimates: the first is a proxy for MOER, the second rests on
  vendor asking prices. Findings 18 and 19.
- **Validation pane** (Spain, UK, India, Compare). The residential baseline behind the hosting-capacity headline
  checked against real smart-meter panels (GoiEner, Low Carbon London) and, for India, a published figure.
  `ml/validation/`, `GET /api/validation`, finding 21.
