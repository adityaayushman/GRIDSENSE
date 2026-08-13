# GridSense

Carbon-aware EV charging optimization — a full-stack system that schedules
residential EV charging against real marginal-emissions data instead of
naive arrival-time charging, and quantifies the reduction in peak grid load
and CO₂ emissions.

**Problem:** most EVs charge the moment their owner gets home (5–9pm),
overlapping the grid's existing demand peak — the exact window when utilities
lean on carbon-intensive peaker plants. GridSense reschedules that load using
a linear-programming optimizer, and shows the before/after impact on a live
dashboard.

## Architecture

```
backend/     FastAPI + PuLP optimization engine (Python)
frontend/    React + TypeScript dashboard (Vite)
```

- **Optimizer** (`backend/app/optimizer.py`) — LP model minimizing marginal
  emissions, cost, or peak load, subject to each vehicle's energy requirement,
  charger power limit, and arrival/deadline window.
- **API** (`backend/app/main.py`) — `POST /api/scenario` runs a full
  naive-vs-optimized comparison and returns hourly series + summary stats.
  Interactive docs at `/docs` once running.
- **Data** (`backend/app/data_sources.py`) — synthetic 24h carbon-intensity,
  time-of-use price, and residential-load curves by default; swap in a real
  WattTime or ElectricityMaps API call by setting `USE_LIVE_DATA=true` and
  `WATTTIME_TOKEN` in `.env`. The price curve models PG&E's EV2-A residential
  EV tariff (off-peak / part-peak / peak steps).

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

Backend on Render (Docker, free tier), frontend on Vercel. **Deploy the backend
first** — Vite inlines `VITE_API_BASE` at build time, so the frontend has to
know the API URL before it is built.

### 1. Push to GitHub
```bash
git remote add origin git@github.com:<you>/gridsense.git
git push -u origin main
```
This is also what makes the CI workflow in `.github/workflows/ci.yml` start running.

### 2. Backend → Render
Render reads `render.yaml` at the repo root (Blueprint deploy):

1. Render dashboard → **New → Blueprint** → select the repo.
2. It picks up the `gridsense-api` web service. Leave `USE_LIVE_DATA=false`.
3. Set `ALLOWED_ORIGINS` — you don't have the Vercel URL yet, so put
   `http://localhost:5173` for now and come back to it in step 4.
4. Deploy, then confirm `https://<your-service>.onrender.com/api/health`
   returns `{"status":"ok"}`.

The container binds `$PORT`, which Render injects; health checks hit
`/api/health`.

### 3. Frontend → Vercel

1. Vercel → **Add New → Project** → select the repo.
2. **Root Directory: `frontend`** — this is a monorepo, and Vercel defaults to
   the repo root, where there is no `package.json`.
3. Add env var `VITE_API_BASE=https://<your-service>.onrender.com` (no
   trailing slash) for Production, Preview, and Development.
4. Deploy.

### 4. Close the CORS loop
Back in Render, set `ALLOWED_ORIGINS` to your Vercel production URL, plus the
preview wildcard if you want PR previews to work:

```
ALLOWED_ORIGINS=https://gridsense.vercel.app
```

Render restarts the service on env change. Without this, the browser blocks
every API call.

### Gotchas

- **Changing `VITE_API_BASE` requires a Vercel *rebuild***, not just a restart —
  Vite bakes the value into the bundle at build time.
- **Free-tier cold starts.** Render spins the service down after ~15 minutes
  idle; the next request takes ~50s. The dashboard fires a `/api/health` ping on
  page load (`warmUp()` in `frontend/src/api.ts`) so the container wakes while
  the visitor is reading, but the very first request after a long idle can
  still be slow.
- `sqlalchemy` and `psycopg2-binary` are in `requirements.txt` but currently
  unused (they are there for the Postgres roadmap item). Dropping them shortens
  Render build times.

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
