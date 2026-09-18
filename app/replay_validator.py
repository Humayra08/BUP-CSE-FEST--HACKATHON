import math
from typing import List, Tuple

from app.optimizer import build_effective_params

TOL = 0.01
ALLOWED_ACTIONS = {"charge", "discharge", "idle"}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def replay_and_recompute(
    hourly_plan: List[dict], hours_data: list, battery: dict, directives: List[dict]
) -> Tuple[bool, dict]:
    """Independently re-verifies the plan against energy-balance, battery, solar, and
    directive rules, and recomputes total_grid_kwh/total_cost_bdt/peak_grid_kwh from
    the plan itself. Returns (is_valid, recomputed_totals)."""
    if not isinstance(hourly_plan, list) or len(hourly_plan) != 24:
        return False, {}

    hours_in_plan = [e.get("hour") for e in hourly_plan]
    if any(h is None or not isinstance(h, int) or isinstance(h, bool) for h in hours_in_plan):
        return False, {}
    # Reject duplicate/missing hours explicitly rather than letting a dict silently
    # collapse duplicates (which would validate an incomplete/inconsistent plan).
    if sorted(hours_in_plan) != list(range(24)):
        return False, {}

    effective_solar, min_reserve, no_charge, no_discharge, max_grid = build_effective_params(
        hours_data, battery, directives
    )

    capacity = battery["capacity_kwh"]
    initial_energy = battery["initial_energy_kwh"]
    max_charge_rate = battery["max_charge_kwh_per_hour"]
    max_discharge_rate = battery["max_discharge_kwh_per_hour"]

    by_hour = {e["hour"]: e for e in hourly_plan}

    valid = True
    prev_energy = initial_energy

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(24):
        e = by_hour[h]
        grid_kwh = e.get("grid_kwh")
        solar_used = e.get("solar_used_kwh")
        action = e.get("battery_action")
        batt_kwh = e.get("battery_kwh")
        energy_after = e.get("battery_energy_after_kwh")
        demand = hours_data[h]["demand_kwh"]
        tariff = hours_data[h]["tariff_bdt_per_kwh"]

        numeric_fields = (grid_kwh, solar_used, batt_kwh, energy_after)
        if not all(_finite(v) for v in numeric_fields):
            # NaN/inf/None/non-numeric would make every downstream `<`/`>` comparison
            # silently evaluate False, letting an invalid value slip through. Reject up front.
            valid = False
            continue

        if action not in ALLOWED_ACTIONS:
            valid = False
            continue

        if grid_kwh < -TOL or solar_used < -TOL or batt_kwh < -TOL:
            valid = False

        if solar_used > effective_solar[h] + TOL:
            valid = False

        charge_amt = batt_kwh if action == "charge" else 0.0
        discharge_amt = batt_kwh if action == "discharge" else 0.0
        if action == "idle" and abs(batt_kwh) > TOL:
            valid = False

        if charge_amt > max_charge_rate + TOL or (no_charge[h] and charge_amt > TOL):
            valid = False
        if discharge_amt > max_discharge_rate + TOL or (no_discharge[h] and discharge_amt > TOL):
            valid = False

        expected_energy = prev_energy + charge_amt - discharge_amt
        if abs(expected_energy - energy_after) > TOL:
            valid = False

        if energy_after < min_reserve[h] - TOL or energy_after > capacity + TOL:
            valid = False

        balance_lhs = grid_kwh + solar_used + discharge_amt
        balance_rhs = demand + charge_amt
        if abs(balance_lhs - balance_rhs) > TOL:
            valid = False

        if max_grid[h] is not None and grid_kwh > max_grid[h] + TOL:
            valid = False

        total_grid += grid_kwh
        total_cost += grid_kwh * tariff
        peak_grid = max(peak_grid, grid_kwh)

        prev_energy = energy_after

    if not valid:
        return False, {}

    if abs(prev_energy - initial_energy) > TOL:
        return False, {}

    totals = {
        "total_grid_kwh": round(total_grid, 4),
        "total_cost_bdt": round(total_cost, 4),
        "peak_grid_kwh": round(peak_grid, 4),
    }
    return True, totals
