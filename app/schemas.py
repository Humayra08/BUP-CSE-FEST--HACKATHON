import math
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

DIRECTIVE_TYPES = (
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
)


def _finite_non_negative(v: float, field_name: str) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number")
    if v < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return float(v)


# ---------- Request ----------

class HourEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, strict=True)
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float

    @field_validator("demand_kwh")
    @classmethod
    def check_demand(cls, v):
        return _finite_non_negative(v, "demand_kwh")

    @field_validator("solar_kwh")
    @classmethod
    def check_solar(cls, v):
        return _finite_non_negative(v, "solar_kwh")

    @field_validator("tariff_bdt_per_kwh")
    @classmethod
    def check_tariff(cls, v):
        return _finite_non_negative(v, "tariff_bdt_per_kwh")


class Battery(BaseModel):
    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float

    @field_validator(
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    )
    @classmethod
    def check_finite_non_negative(cls, v, info):
        return _finite_non_negative(v, info.field_name)

    @model_validator(mode="after")
    def check_ordering(self):
        if self.capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be positive")
        if not (0 <= self.minimum_energy_kwh <= self.capacity_kwh):
            raise ValueError("minimum_energy_kwh must be between 0 and capacity_kwh")
        if not (self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh):
            raise ValueError("initial_energy_kwh must be between minimum_energy_kwh and capacity_kwh")
        return self


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24)
    battery: Battery

    @field_validator("hours")
    @classmethod
    def hours_cover_0_23(cls, v: List[HourEntry]) -> List[HourEntry]:
        seen = sorted(h.hour for h in v)
        if seen != list(range(24)):
            raise ValueError("hours must contain exactly one entry for each hour 0-23, no duplicates")
        return v

    @field_validator("operator_notes")
    @classmethod
    def notes_non_empty(cls, v: List[str]) -> List[str]:
        if any(not isinstance(n, str) or not n.strip() for n in v):
            raise ValueError("operator_notes entries must be non-empty strings")
        return v


# ---------- Structured adjustments ----------

class SolarReductionAdj(BaseModel):
    hours: List[int]
    factor: float


class MinBatteryReserveAdj(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float


class NoChargeWindowAdj(BaseModel):
    hours: List[int]


class NoDischargeWindowAdj(BaseModel):
    hours: List[int]


class MaxGridWindowAdj(BaseModel):
    hours: List[int]
    max_grid_kwh: float


StructuredAdjustment = Union[
    SolarReductionAdj,
    MinBatteryReserveAdj,
    NoChargeWindowAdj,
    NoDischargeWindowAdj,
    MaxGridWindowAdj,
    None,
]


# ---------- Response ----------

class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    ]
    structured_adjustment: Optional[dict] = None
    explanation: str = ""


class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
