from pydantic import BaseModel, Field


class FleetGroup(BaseModel):
    """One kind of vehicle in a mixed fleet: scooters, rickshaws and cars differ in
    energy, charger rating and when they are parked."""
    count: int = Field(..., ge=1, le=1000)
    energy_per_vehicle_kwh: float = Field(..., ge=0.5, le=100.0)
    charger_kw: float = Field(..., ge=0.3, le=22.0)
    arrival_hour: int = Field(18, ge=0, le=23)
    deadline_hour: int = Field(7, ge=0, le=23)


class ScenarioRequest(BaseModel):
    ev_count: int = Field(80, ge=1, le=1000)
    charger_kw: float = Field(7.0, ge=1.4, le=22.0)
    arrival_hour: int = Field(18, ge=0, le=23, description="Typical arrival hour, 24h format")
    deadline_hour: int = Field(7, ge=0, le=23, description="Hour by which charging must complete (next day)")
    energy_per_vehicle_kwh: float = Field(9.2, ge=1.0, le=100.0)
    objective: str = Field("emissions", pattern="^(emissions|cost|peak)$")
    region: str = Field("ES")
    era: str = Field(
        "2018", pattern="^(2018|2025)$",
        description="Which grid to schedule against: 2018 (the original record) or 2025 "
                    "(the grid as it is now: roughly half the carbon intensity and three "
                    "times the solar).",
    )
    day: str | None = Field(
        None,
        description="ISO date of the measured charging night to simulate "
                    "(18:00 that day to 07:00 the next). Defaults to the median-saving night.",
    )
    use_forecast: bool = Field(
        False,
        description="Schedule against the day-ahead forecast instead of the measured "
                    "curve. Results are always scored against what actually happened, so "
                    "this is what a real scheduler could have achieved; leaving it off is "
                    "perfect foresight and an upper bound.",
    )
    gate_min_saving_pct: float | None = Field(
        None, ge=0, le=50,
        description="Forecast gate. When scheduling on the day-ahead forecast, charge on "
                    "arrival instead unless the saving the forecast expects is at least this "
                    "many percent. Guards against the forecast's own error on flat nights, "
                    "where scheduling on it can be worse than not scheduling. 4 is the "
                    "value finding 13 settled on. Applies only with the emissions "
                    "objective, use_forecast, no feeder limit and no V2G; otherwise ignored "
                    "and the response says why.",
    )
    fleet: list[FleetGroup] | None = Field(
        None, max_length=12,
        description="A mixed fleet, as groups of identical vehicles. When given it replaces "
                    "ev_count, charger_kw, energy_per_vehicle_kwh, arrival_hour and "
                    "deadline_hour. The optimizer always supported heterogeneous vehicles; "
                    "this exposes it. The group sizes must total at most 1000.",
    )
    allow_v2g: bool = Field(
        False,
        description="Let vehicles discharge back to the grid. Round-trip losses are "
                    "charged to the export leg, and each vehicle keeps a reserve it "
                    "will not go below.",
    )
    v2g_export_cap_kwh: float | None = Field(
        6.0, ge=0, le=100,
        description="Cap on energy each vehicle exports over the night. Uncapped, the "
                    "schedule cycles packs repeatedly, because the model prices carbon "
                    "and money but not battery wear.",
    )
    feeder_capacity_kw: float | None = Field(
        None,
        ge=10,
        le=5000,
        description="Shared distribution-transformer limit in kW, applied to EV load plus "
                    "the residential baseline. Omit for an unconstrained feeder. This is the "
                    "only constraint that couples vehicles to each other, so it is what makes "
                    "the schedule a genuine optimisation rather than a per-vehicle greedy fill.",
    )


class HourlySeries(BaseModel):
    hour: int
    label: str
    naive_kw: float
    optimized_kw: float
    carbon_intensity: float
    price: float


class ScenarioResponse(BaseModel):
    hourly: list[HourlySeries]
    peak_naive_kw: float
    peak_optimized_kw: float
    peak_reduction_pct: float
    emissions_naive_kg: float
    emissions_optimized_kg: float
    emissions_reduction_pct: float
    cost_naive: float
    cost_optimized: float
    exported_kwh: float
    used_v2g: bool
    cost_reduction_pct: float
    currency: str
    energy_scheduled_kwh: float
    ev_count: int
    region: str
    day: str
    feeder_capacity_kw: float | None
    naive_overload_hours: int
    naive_overload_peak_kw: float
    used_forecast: bool
    forecast_available: bool
    hourly_forecast: list[float] | None
    gate_applied: bool = False
    gate_acted: bool = True
    gate_expected_saving_pct: float | None = None
    gate_reason: str | None = None
    run_id: int | None = None
    era: str = "2018"
