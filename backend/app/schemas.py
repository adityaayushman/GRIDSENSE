from pydantic import BaseModel, Field


class ScenarioRequest(BaseModel):
    ev_count: int = Field(80, ge=1, le=1000)
    charger_kw: float = Field(7.0, ge=1.4, le=22.0)
    arrival_hour: int = Field(18, ge=0, le=23, description="Typical arrival hour, 24h format")
    deadline_hour: int = Field(7, ge=0, le=23, description="Hour by which charging must complete (next day)")
    energy_per_vehicle_kwh: float = Field(9.2, ge=1.0, le=100.0)
    objective: str = Field("emissions", pattern="^(emissions|cost|peak)$")
    region: str = Field("ES")
    day: str | None = Field(
        None,
        description="ISO date of the measured charging night to simulate "
                    "(18:00 that day to 07:00 the next). Defaults to the median-saving night.",
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
    cost_reduction_pct: float
    currency: str
    energy_scheduled_kwh: float
    ev_count: int
    region: str
    day: str
