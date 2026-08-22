# GridSense

**Live:** https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app
· [Simulator](https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app/) · [Existing vs GridSense](https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app/#comparison) · [Grid headroom](https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app/#hosting)
· [API health](https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app/api/health) · [days](https://gridsense-app-adityaasahoo-gmailcoms-projects.vercel.app/api/days)

Both tiers run from one Vercel project, so the dashboard and the API share an
origin. The split `gridsense-es` / `gridsense-api-es` pair this used to name has
been superseded.

Carbon-aware EV charging optimization — a full-stack system that schedules
residential EV charging against **measured** grid carbon-intensity and price
data instead of naive arrival-time charging, and quantifies what that actually
saves.

**Problem:** most EVs charge the moment their owner gets home (5–9pm),
overlapping the grid's existing demand peak — the window when utilities lean on
carbon-intensive peaker plants. GridSense reschedules that load using a
linear-programming optimizer, and shows the before/after impact on a live
dashboard.

**Hosting capacity.** The finding with money attached: on a 1,250 kW street
transformer serving 200 homes, charging on arrival supports **200 EVs** before
the median night exceeds the rating. Coordinating the street against the
transformer supports **1,254** — a **6.3×** gain — because the binding constraint
moves from instantaneous power to energy: charging on arrival uses one or two
hours of a thirteen-hour window and leaves the rest empty. That is a deferred
capital upgrade, not a rounding error. See the **Grid headroom** pane.

(An earlier version of this claimed 14×, on a fleet where every car arrived at
exactly 18:00. That assumption inflates it: staggered arrivals triple what dumb
charging can host. 6.3× is the defensible figure — see [FINDINGS.md](FINDINGS.md).)

**What the data says.** Backtested over every complete overnight window in
ENTSO-E's 2018 Spanish record, the median night saves **3.3%** of charging
emissions and the fleet-wide total is **10.4%** — not the flat 30%+ a smooth
synthetic curve suggests. The saving is long-tailed: 38% of nights save under
1%, while 17% save over 20%. The objectives genuinely conflict, too — the
cheapest hour and the cleanest hour coincide on only 14% of nights, so
minimizing cost can *raise* emissions. The dashboard shows those as increases
rather than hiding them. See [`ml/README.md`](ml/README.md) for the analysis.

## Documents

- [FEATURES.md](FEATURES.md) — what is built, what is not, what is out of scope
- [FINDINGS.md](FINDINGS.md) — every result with the script that reproduces it,
  including the hypotheses that failed
- [ml/README.md](ml/README.md) — the analysis and how to re-run it

## Architecture

```
backend/     FastAPI + PuLP optimization engine (Python)
frontend/    React + TypeScript dashboard (Vite)
```

- **Optimizer** (`backend/app/optimizer.py`) — LP model minimizing carbon,
  cost, or peak load, subject to each vehicle's energy requirement, charger
  power limit, arrival/deadline window, and an optional shared feeder limit.

  > **What the LP is actually for.** Without a constraint linking vehicles the
  > problem is *separable*: each vehicle independently fills its own cleanest
  > hours, and a greedy loop reproduces the LP's objective to within 1e-6.
  > Vehicle heterogeneity does not change this — differing arrivals, energies and
  > charger ratings still separate. The optimizer earns its keep only under a
  > **coupling** constraint, of which this model has two: the `peak` objective,
  > and the feeder-capacity limit. Given a 180 kW feeder, greedy peaks at 485 kW
  > and simply breaks it; the LP lands on 180 kW exactly.
  > `test_without_a_coupling_constraint_the_lp_only_matches_greedy` pins this
  > down so the claim cannot silently rot.
- **API** (`backend/app/main.py`) — `POST /api/scenario` runs a full
  naive-vs-optimized comparison for one measured grid night and returns hourly
  series + summary stats; `GET /api/days` lists the nights available to
  simulate. Interactive docs at `/docs` once running.
- **Data** (`backend/app/data_sources.py`) — serves measured Spanish grid days
  from `backend/app/data/grid_days.json`: carbon intensity derived from the
  ENTSO-E generation mix weighted by IPCC AR5 lifecycle emission factors, and
  day-ahead market price plus Spain's flat PVPC access component. Each stored
  day is an 18:00→07:00 charging night, so indices 0-7 are the following
  morning. Only the residential baseline load remains synthetic — ENTSO-E
  reports system-wide load, which cannot be scaled to one feeder without an
  assumption.

  > Spain rather than California because it is one of the few countries where
  > ordinary households are billed at genuinely hourly-varying prices (PVPC),
  > which is the premise the cost objective depends on.

  > The derived series is *average* carbon intensity, not *marginal*. Load
  > shifting responds to the marginal rate; closing that gap needs MOER data
  > this dataset does not carry. `ml/src/carbon.py` estimates a system marginal
  > rate (228 vs 267 gCO2eq/kWh average) but the served series is the average.

## Running locally

### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt is runtime-only
cp .env.example .env
uvicorn app.main:app --reload
```
API now running at http://localhost:8000, docs at http://localhost:8000/docs

### Tests
```bash
cd backend
pytest tests/ -v
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Dashboard now running at http://localhost:5173

## Deploying

Both tiers ship from **one** Vercel project, built from this repo on every push
to `main`. The root `vercel.json` routes `/api/*` to the Python function and
everything else to the static Vite output, so the dashboard and the API share an
origin.

That removes two moving parts: requests are same-origin so CORS is not
load-bearing in production, and the frontend no longer needs the API hostname
baked in at build time.

> `.vercel.app` hostnames are globally unique, not per-account. `gridsense`,
> `gridsense-app` and `gridsense-api` are all taken by unrelated projects, so
> confirm the alias a deploy actually returns rather than assuming it from the
> project name.

### Backend → Vercel

`backend/vercel.json` uses the legacy `builds`/`routes` form rather than
`rewrites`. This is deliberate: `rewrites` rewrites the request *path*, so the
ASGI app receives `/api/index` and every route 404s. `routes` with a `dest`
preserves the original path.

`backend/api/index.py` is the entrypoint — it prepends the deployment root to
`sys.path` so `app.main` resolves, then re-exports the FastAPI `app`.

PuLP's bundled CBC solver (7.2 MB, Linux x86-64) runs fine in the serverless
sandbox; a full 80-vehicle scenario solves in well under a second.

Point a Vercel project at `backend/` as its root directory and deploy.

### Frontend → Vercel

Root directory `frontend/`. Set `VITE_API_BASE` to the API URL — either as a
Vercel env var (Production + Preview + Development) or via `.env.production`.

### CORS

`app/main.py` accepts an exact allowlist via `ALLOWED_ORIGINS` **and** a pattern
via `ALLOWED_ORIGIN_REGEX`, which defaults to:

```
^https://gridsense[a-z0-9-]*\.vercel\.app$
```

The pattern exists because Vercel mints a fresh hostname for every preview
deployment, which an exact list can't cover. Both anchors matter — without `$`,
`https://gridsense.evil.com` would be admitted.

### Backend on Render (container)

The API also runs as a Docker container, which is the better fit if you want a
warm process rather than a serverless function — the LP solver benefits from not
re-initialising per request.

Deploy: Render dashboard -> **New -> Blueprint** -> pick this repo. `render.yaml`
at the repo root describes the whole service, so there is nothing to fill in.
It comes up at `https://gridsense-api-es.onrender.com`:

- Build context is `backend/`, which is required — the Dockerfile `COPY`s
  `requirements.txt` and `app/` as top-level paths.
- `app/data/grid_days.json` lives inside `app/`, so the measured grid data is
  baked into the image. No volume, no fetch-on-boot, no external dependency at
  runtime.
- The container binds Render's injected `$PORT`. The `CMD` is in **shell form**
  deliberately: the exec form does no variable expansion, so `${PORT}` would be
  passed to uvicorn as a literal string and the service would fail its health
  check.
- Health checks hit `/api/health`.
- **The service name matters.** `onrender.com` hostnames are globally unique,
  not per-account: `gridsense-api` is already an unrelated FastAPI service, and
  claiming a taken name silently gets you a suffixed hostname instead. Check
  first with `curl -sI https://<name>.onrender.com | grep x-render-routing` —
  `no-server` means it is free.
- **CORS needs no dashboard input.** The app's `ALLOWED_ORIGIN_REGEX` default
  already admits this project's `*.vercel.app` frontends, including the fresh
  hostname Vercel mints for every preview deploy. Set `ALLOWED_ORIGINS` only for
  an origin outside that pattern, such as a custom domain.

Then point the frontend at it by setting `VITE_API_BASE` to the Render URL and
rebuilding (see the gotcha below — a restart is not enough).

Note the free instance sleeps after ~15 minutes idle and takes ~50s to wake. The
dashboard's `warmUp()` ping covers some of that, but not a fully cold start.

### Gotchas

- **Changing `VITE_API_BASE` requires a Vercel *rebuild***, not just a restart —
  Vite bakes the value into the bundle at build time.
- **`<project>.vercel.app` is globally unique, not per-account.** `gridsense`,
  `gridsense-app` and `gridsense-api` are each taken by unrelated projects,
  which is why the live URL carries the account-scoped suffix rather than a
  short name. Always confirm the alias a deploy actually returns rather than
  assuming it from the project name.
- **Cold starts.** The dashboard fires a `/api/health` ping on mount
  (`warmUp()` in `frontend/src/api.ts`) so the function is warm by the time the
  visitor hits Run. On Vercel that saves ~1-2s; on a Render free-tier container,
  which spins down after ~15 minutes idle, it saves ~50s.
- **`requirements.txt` is runtime-only** — it is what both the container image
  and the Vercel function install, so anything added there ships to production.
  Tests install `requirements-dev.txt`, which layers `pytest` on top.
  `python-dotenv`, `sqlalchemy` and `psycopg2-binary` were dropped: nothing
  imports them, and they cost build time on every deploy.

## Roadmap
- [x] Forecasting layer — day-ahead carbon-intensity model trained and evaluated
      (`ml/`); the demo currently serves measured curves rather than forecasts
- [ ] Multi-region comparison (e.g. coal-heavy vs. renewables-heavy grid)
- [ ] Persist simulation runs to Postgres
- [x] Feeder-capacity constraint UI (grid-strain visualization)
- [ ] V2G scenario mode

## Data sources

In use:
- [ENTSO-E via Kaggle](https://www.kaggle.com/datasets/nicholasjhana/energy-consumption-generation-prices-and-weather)
  (CC0) — hourly Spanish generation mix and day-ahead prices, 2015-2018
- IPCC AR5 WG3 Annex III — lifecycle emission factors per fuel

Not yet wired in:
- [WattTime API](https://www.watttime.org/api-documentation/) — true marginal
  emissions (MOER), which would close the average-vs-marginal gap
- [ElectricityMaps](https://docs.electricitymaps.com/) — live carbon intensity
- [ACN-Data (Caltech)](https://ev.caltech.edu/dataset) — real EV charging
  sessions, to replace the assumed arrival/energy distributions
