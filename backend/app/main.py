import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import data_sources, store
from app.optimizer import Vehicle, run_scenario
from app.schemas import FleetGroup, HourlySeries, ScenarioRequest, ScenarioResponse

app = FastAPI(
    title="GridSense API",
    description="Carbon-aware EV charging scheduling — optimization engine API.",
    version="0.1.0",
)

# Comma-separated exact origins; defaults to the local dev ports.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

# Vercel assigns the frontend a generated hostname per deployment (previews get
# a fresh one every push), so an exact allowlist cannot cover them. This pattern
# admits this project's own vercel.app subdomains and nothing else — note the
# anchors, without which "https://gridsense.evil.com" would match.
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX", r"^https://gridsense[a-z0-9-]*\.vercel\.app$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/forecast")
def forecast_info(era: str = "2018"):
    """Provenance of the day-ahead forecast the scheduler can run against."""
    try:
        return data_sources.forecast_meta(era)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/days")
def days(era: str = "2018"):
    """Charging nights available to simulate in an era, and which one is served by default."""
    try:
        available = data_sources.available_days(era)
        return {
            "days": available,
            "default": data_sources.default_day(era),
            "count": len(available),
            "region": "ES",
            "era": era,
            "eras": data_sources.eras(),
            "year_stats": data_sources.year_stats(era),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/scenario", response_model=ScenarioResponse)
def run_scenario_endpoint(req: ScenarioRequest):
    try:
        groups = req.fleet or [FleetGroup(
            count=req.ev_count, energy_per_vehicle_kwh=req.energy_per_vehicle_kwh,
            charger_kw=req.charger_kw, arrival_hour=req.arrival_hour,
            deadline_hour=req.deadline_hour,
        )]
        total_vehicles = sum(g.count for g in groups)
        if total_vehicles > 1000:
            raise ValueError(f"fleet totals {total_vehicles} vehicles; the limit is 1000")
        vehicles = [
            Vehicle(
                id=f"g{gi}v{i}",
                energy_needed_kwh=g.energy_per_vehicle_kwh,
                charger_kw=g.charger_kw,
                arrival_hour=g.arrival_hour,
                deadline_hour=g.deadline_hour,
                discharge_kw=g.charger_kw if req.allow_v2g else 0.0,
                battery_kwh=60.0,
                # Arriving part-charged: a pack that is already full has nothing
                # to lend, and one that is empty cannot lend before it charges.
                arrival_soc_kwh=25.0,
                reserve_kwh=12.0,
                max_export_kwh=req.v2g_export_cap_kwh,
            )
            for gi, g in enumerate(groups)
            for i in range(g.count)
        ]

        day = data_sources.resolve_day(req.day, req.era)
        carbon = data_sources.get_carbon_intensity(req.region, day, req.era)
        price = data_sources.get_price(req.region, day, req.era)
        baseline = data_sources.get_residential_baseline_kw(household_count=total_vehicles)

        forecast = data_sources.get_carbon_forecast(req.region, day, req.era)
        # Schedule on the forecast when asked, but always score against `carbon`,
        # which is what actually happened. Falls back to perfect foresight when a
        # night has no forecast attached rather than failing the request.
        use_forecast = bool(req.use_forecast and forecast)

        result = run_scenario(
            vehicles=vehicles,
            carbon_intensity=carbon,
            residential_baseline_kw=baseline,
            price=price,
            objective=req.objective,  # type: ignore[arg-type]
            feeder_capacity_kw=req.feeder_capacity_kw,
            schedule_carbon=forecast if use_forecast else None,
            allow_v2g=req.allow_v2g,
            gate_min_saving_pct=req.gate_min_saving_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    hourly = [
        HourlySeries(
            hour=h,
            label=f"{h:02d}:00",
            naive_kw=round(result.hourly_naive_load_kw[h], 2),
            optimized_kw=round(result.hourly_optimized_load_kw[h], 2),
            carbon_intensity=result.hourly_carbon_intensity[h],
            price=price[h],
        )
        for h in range(24)
    ]

    response = ScenarioResponse(
        hourly=hourly,
        peak_naive_kw=round(result.peak_naive_kw, 2),
        peak_optimized_kw=round(result.peak_optimized_kw, 2),
        peak_reduction_pct=result.peak_reduction_pct,
        emissions_naive_kg=round(result.emissions_naive_kg, 2),
        emissions_optimized_kg=round(result.emissions_optimized_kg, 2),
        emissions_reduction_pct=result.emissions_reduction_pct,
        cost_naive=round(result.cost_naive, 2),
        cost_optimized=round(result.cost_optimized, 2),
        exported_kwh=result.exported_kwh,
        used_v2g=req.allow_v2g,
        cost_reduction_pct=result.cost_reduction_pct,
        currency=data_sources.CURRENCY,
        energy_scheduled_kwh=round(sum(g.count * g.energy_per_vehicle_kwh for g in groups), 1),
        ev_count=total_vehicles,
        region=req.region,
        day=day,
        feeder_capacity_kw=result.feeder_capacity_kw,
        naive_overload_hours=result.naive_overload_hours,
        naive_overload_peak_kw=result.naive_overload_peak_kw,
        used_forecast=use_forecast,
        forecast_available=forecast is not None,
        hourly_forecast=forecast,
        gate_applied=result.gate_applied,
        gate_acted=result.gate_acted,
        gate_expected_saving_pct=result.gate_expected_saving_pct,
        gate_reason=result.gate_reason,
        era=req.era,
    )
    run_id = store.save_run(req.model_dump(exclude_none=True), response.model_dump(exclude={"hourly", "hourly_forecast"}))
    response.run_id = run_id
    return response


@app.get("/api/runs")
def list_runs(limit: int = 20):
    """Recently recorded runs, newest first. Needs DATABASE_URL (see app/store.py)."""
    if not store.enabled():
        raise HTTPException(status_code=501, detail=store.why_disabled())
    return {"runs": store.recent(max(1, min(limit, 200)))}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    if not store.enabled():
        raise HTTPException(status_code=501, detail=store.why_disabled())
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return run

