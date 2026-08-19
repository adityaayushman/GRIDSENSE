import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import data_sources
from app.optimizer import Vehicle, run_scenario
from app.schemas import HourlySeries, ScenarioRequest, ScenarioResponse

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


@app.get("/api/days")
def days():
    """Charging nights available to simulate, and which one is served by default."""
    available = data_sources.available_days()
    return {
        "days": available,
        "default": data_sources.default_day(),
        "count": len(available),
        "region": "ES",
    }


@app.post("/api/scenario", response_model=ScenarioResponse)
def run_scenario_endpoint(req: ScenarioRequest):
    try:
        vehicles = [
            Vehicle(
                id=f"v{i}",
                energy_needed_kwh=req.energy_per_vehicle_kwh,
                charger_kw=req.charger_kw,
                arrival_hour=req.arrival_hour,
                deadline_hour=req.deadline_hour,
            )
            for i in range(req.ev_count)
        ]

        day = data_sources.resolve_day(req.day)
        carbon = data_sources.get_carbon_intensity(req.region, day)
        price = data_sources.get_price(req.region, day)
        baseline = data_sources.get_residential_baseline_kw(household_count=req.ev_count)

        result = run_scenario(
            vehicles=vehicles,
            carbon_intensity=carbon,
            residential_baseline_kw=baseline,
            price=price,
            objective=req.objective,  # type: ignore[arg-type]
            feeder_capacity_kw=req.feeder_capacity_kw,
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

    return ScenarioResponse(
        hourly=hourly,
        peak_naive_kw=round(result.peak_naive_kw, 2),
        peak_optimized_kw=round(result.peak_optimized_kw, 2),
        peak_reduction_pct=result.peak_reduction_pct,
        emissions_naive_kg=round(result.emissions_naive_kg, 2),
        emissions_optimized_kg=round(result.emissions_optimized_kg, 2),
        emissions_reduction_pct=result.emissions_reduction_pct,
        cost_naive=round(result.cost_naive, 2),
        cost_optimized=round(result.cost_optimized, 2),
        cost_reduction_pct=result.cost_reduction_pct,
        currency=data_sources.CURRENCY,
        energy_scheduled_kwh=round(req.ev_count * req.energy_per_vehicle_kwh, 1),
        ev_count=req.ev_count,
        region=req.region,
        day=day,
        feeder_capacity_kw=result.feeder_capacity_kw,
        naive_overload_hours=result.naive_overload_hours,
        naive_overload_peak_kw=result.naive_overload_peak_kw,
    )
