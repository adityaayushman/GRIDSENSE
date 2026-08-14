# GridSense

**Live demo:** https://gridsense-es.vercel.app
**API:** https://gridsense-api-es.vercel.app ([health](https://gridsense-api-es.vercel.app/api/health) · [days](https://gridsense-api-es.vercel.app/api/days))

Carbon-aware EV charging optimization — a full-stack system that schedules
residential EV charging against **measured** grid carbon-intensity and price
data instead of naive arrival-time charging, and quantifies what that actually
saves.

**Problem:** most EVs charge the moment their owner gets home (5–9pm),
overlapping the grid's existing demand peak — the window when utilities lean on
carbon-intensive peaker plants. GridSense reschedules that load using a
linear-programming optimizer, and shows the before/after impact on a live
dashboard.

**What the data says.** Backtested over every complete overnight window in
ENTSO-E's 2018 Spanish record, the median night saves **3.3%** of charging
emissions and the fleet-wide total is **10.4%** — not the flat 30%+ a smooth
synthetic curve suggests. The saving is long-tailed: 38% of nights save under
1%, while 17% save over 20%. The objectives genuinely conflict, too — the
cheapest hour and the cleanest hour coincide on only 14% of nights, so
minimizing cost can *raise* emissions. The dashboard shows those as increases
rather than hiding them. See [`ml/README.md`](ml/README.md) for the analysis.

## Architecture

```
backend/     FastAPI + PuLP optimization engine (Python)
frontend/    React + TypeScript dashboard (Vite)
```

- **Optimizer** (`backend/app/optimizer.py`) — LP model minimizing marginal
  emissions, cost, or peak load, subject to each vehicle's energy requirement,
  charger power limit, and arrival/deadline window.
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
pip install -r requirements.txt
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

Both tiers currently run on Vercel as two projects:

| Project | Serves | URL |
| --- | --- | --- |
| `gridsense-es` | Vite static build of `frontend/` | https://gridsense-es.vercel.app |
| `gridsense-api-es` | `backend/` as a Python serverless function | https://gridsense-api-es.vercel.app |

**Deploy the backend first.** Vite inlines `VITE_API_BASE` at build time, so the
frontend must know the API URL before it is built.

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

### Alternative: backend on Render

`render.yaml` and `backend/Dockerfile` are still maintained, so the API can run
as a container instead. Blueprint-deploy the repo on Render; the container binds
the injected `$PORT` and health checks hit `/api/health`. Set `ALLOWED_ORIGINS`
to the frontend URL.

### Gotchas

- **Changing `VITE_API_BASE` requires a Vercel *rebuild***, not just a restart —
  Vite bakes the value into the bundle at build time.
- **`<project>.vercel.app` is globally unique, not per-account.** `gridsense`
  was already taken by an unrelated project, which is why the frontend is
  `gridsense-dashboard`. Always confirm the alias a deploy actually returns
  rather than assuming it from the project name.
- **Cold starts.** The dashboard fires a `/api/health` ping on mount
  (`warmUp()` in `frontend/src/api.ts`) so the function is warm by the time the
  visitor hits Run. On Vercel that saves ~1-2s; on a Render free-tier container,
  which spins down after ~15 minutes idle, it saves ~50s.
- `sqlalchemy` and `psycopg2-binary` are in `requirements.txt` but currently
  unused (they are there for the Postgres roadmap item). The Vercel deployment
  installs a trimmed set without them.

## Roadmap
- [ ] Forecasting layer (predict next-day marginal emissions) feeding the optimizer
- [ ] Multi-region comparison (e.g. coal-heavy vs. renewables-heavy grid)
- [ ] Persist simulation runs to Postgres
- [ ] Feeder-capacity constraint UI (grid-strain visualization)
- [ ] V2G scenario mode

## Data sources
- [WattTime API](https://www.watttime.org/api-documentation/) — marginal emissions
- [ElectricityMaps](https://docs.electricitymaps.com/) — alternative carbon intensity source
- [ACN-Data (Caltech)](https://ev.caltech.edu/dataset) — real EV charging session data
