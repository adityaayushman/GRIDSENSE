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

# Comma-separated list; set ALLOWED_ORIGINS to the deployed frontend URL in
# production (e.g. https://gridsense.vercel.app). Defaults to local dev ports.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


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

        carbon = data_sources.get_carbon_intensity(req.region)
        price = data_sources.get_price(req.region)
        baseline = data_sources.get_residential_baseline_kw(household_count=req.ev_count)

        result = run_scenario(
            vehicles=vehicles,
            carbon_intensity=carbon,
            residential_baseline_kw=baseline,
            price=price,
            objective=req.objective,  # type: ignore[arg-type]
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
        cost_naive_usd=round(result.cost_naive, 2),
        cost_optimized_usd=round(result.cost_optimized, 2),
        cost_reduction_pct=result.cost_reduction_pct,
        energy_scheduled_kwh=round(req.ev_count * req.energy_per_vehicle_kwh, 1),
        ev_count=req.ev_count,
        region=req.region,
    )
