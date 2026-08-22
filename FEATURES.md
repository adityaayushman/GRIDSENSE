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
- An over-tight feeder limit returns a planning answer, not `Infeasible` —
  `max_deliverable_kwh` bounds what fits under the limit and the error reports
  both numbers.
- Naive-schedule simulator for the "before" case.
- **20 unit tests**, including regression guards for the two defects found in
  this codebase: the cost objective silently having no price curve, and the LP
  matching greedy whenever no constraint couples vehicles.

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
- `GET /api/days` lists the nights available to simulate.
- `GET /api/health`. Swagger at `/docs`.
- CORS via an exact allowlist **and** an anchored origin pattern, since Vercel
  mints a new hostname per preview deploy.

## Frontend dashboard — built

Three deep-linkable panes:

- **Simulator** — scenario controls (EVs, charger rating, feeder capacity,
  measured night), a hero number that follows the selected objective, grid-load
  and carbon-intensity charts, and a grid-strain banner when naive breaches the
  transformer.
- **Existing vs GridSense** — capability matrix against charging-on-arrival and
  a synthetic-curve optimizer, decision-regret chart, savings distribution, and
  the LP-vs-greedy coupling table.
- **Grid headroom** — EV adoption sweep against transformer ratings, and the
  hosting-capacity table.

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
| `train.py` | Day-ahead forecaster, accuracy + decision regret |
| `export_grid_days.py` | The nights the API serves |
| `export_evidence.py` | The **Existing vs GridSense** pane's figures |
| `export_hosting_capacity.py` | The **Grid headroom** pane's figures |

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

## Not yet built

- **The forecaster is trained but not serving.** Ridge captures 68.5% of the
  achievable saving and exports as 15 coefficients, but the demo serves measured
  curves — i.e. perfect foresight. Wiring it in would let the dashboard show
  forecast-driven against perfect-foresight scheduling.
- **Marginal rather than average carbon intensity** — needs MOER data.
- **Heterogeneous fleets** — supported by the optimizer, not exposed by the API.
- **Postgres persistence** of simulation runs. `sqlalchemy`/`psycopg2` were
  *removed* from requirements: nothing imported them and they cost build time on
  every deploy.
- Multi-region comparison, V2G mode.
- Styled empty/error states — a cold API or a rejected night currently renders a
  bare text block.

## Out of scope

Public DC fast-charging and depot fleets; battery degradation; transmission-level
market analysis; hardware-level transformer simulation; full cost-benefit
analysis of grid upgrades.
