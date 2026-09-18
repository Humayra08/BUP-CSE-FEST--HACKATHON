from typing import List

import pulp

HOURS = range(24)


def _hour_set(hours: List[int]) -> set:
    return set(hours)


def build_effective_params(hours_data: list, battery: dict, directives: List[dict]):
    """Applies validated (applies=true) directives to produce per-hour effective
    solar, min reserve, no-charge/no-discharge flags, and max-grid caps."""
    effective_solar = [h["solar_kwh"] for h in hours_data]
    min_reserve = [battery["minimum_energy_kwh"]] * 24
    no_charge = [False] * 24
    no_discharge = [False] * 24
    max_grid = [None] * 24

    for d in directives:
        if not d.get("applies"):
            continue
        adj = d["structured_adjustment"]
        dtype = d["directive_type"]
        dhours = adj["hours"]

        if dtype == "solar_reduction":
            factor = adj["factor"]
            for h in dhours:
                effective_solar[h] = hours_data[h]["solar_kwh"] * factor

        elif dtype == "minimum_battery_reserve":
            level = adj["minimum_energy_kwh"]
            for h in dhours:
                min_reserve[h] = max(min_reserve[h], level)

        elif dtype == "no_charge_window":
            for h in dhours:
                no_charge[h] = True

        elif dtype == "no_discharge_window":
            for h in dhours:
                no_discharge[h] = True

        elif dtype == "max_grid_window":
            cap = adj["max_grid_kwh"]
            for h in dhours:
                max_grid[h] = cap if max_grid[h] is None else min(max_grid[h], cap)

    return effective_solar, min_reserve, no_charge, no_discharge, max_grid


def solve_schedule(hours_data: list, battery: dict, directives: List[dict], time_limit: float = None) -> List[dict]:
    """hours_data: list of 24 dicts with hour/demand_kwh/solar_kwh/tariff_bdt_per_kwh, sorted by hour.
    battery: dict with capacity_kwh/initial_energy_kwh/minimum_energy_kwh/max_charge_kwh_per_hour/max_discharge_kwh_per_hour.
    Returns hourly_plan as a list of 24 dicts, or raises RuntimeError if infeasible."""
    effective_solar, min_reserve, no_charge, no_discharge, max_grid = build_effective_params(
        hours_data, battery, directives
    )

    capacity = battery["capacity_kwh"]
    initial_energy = battery["initial_energy_kwh"]
    max_charge_rate = battery["max_charge_kwh_per_hour"]
    max_discharge_rate = battery["max_discharge_kwh_per_hour"]

    prob = pulp.LpProblem("gridwise_schedule", pulp.LpMinimize)

    grid = {h: pulp.LpVariable(f"grid_{h}", lowBound=0) for h in HOURS}
    solar_used = {h: pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h]) for h in HOURS}
    charge = {
        h: pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=0 if no_charge[h] else max_charge_rate)
        for h in HOURS
    }
    discharge = {
        h: pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=0 if no_discharge[h] else max_discharge_rate)
        for h in HOURS
    }
    batt_energy = {
        h: pulp.LpVariable(f"batt_energy_{h}", lowBound=min_reserve[h], upBound=capacity) for h in HOURS
    }

    prob += pulp.lpSum(grid[h] * hours_data[h]["tariff_bdt_per_kwh"] for h in HOURS)

    for h in HOURS:
        prev_energy = initial_energy if h == 0 else batt_energy[h - 1]
        prob += batt_energy[h] == prev_energy + charge[h] - discharge[h]

        prob += (
            grid[h] + solar_used[h] + discharge[h] == hours_data[h]["demand_kwh"] + charge[h]
        )

        if max_grid[h] is not None:
            prob += grid[h] <= max_grid[h]

    prob += batt_energy[23] == initial_energy

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit) if time_limit else pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)

    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"Optimizer failed to find a feasible schedule: {pulp.LpStatus[prob.status]}")

    plan = []
    prev_energy = initial_energy
    for h in HOURS:
        c = charge[h].value() or 0.0
        d = discharge[h].value() or 0.0
        # The LP relaxation can assign positive charge and discharge in the same
        # hour when they cancel out cost-wise (e.g. charge=55, discharge=55 nets
        # to no real battery movement). Serializing whichever var is "bigger" as
        # the plan's action silently drops the other, breaking energy balance on
        # replay. Collapse to the net action instead — under this challenge's
        # lossless battery model, canceling equal charge/discharge is equivalent
        # to idle for every rule (balance, state, cost, rate limits, windows).
        net = c - d
        if net > 1e-6:
            action, magnitude = "charge", net
        elif net < -1e-6:
            action, magnitude = "discharge", -net
        else:
            action, magnitude = "idle", 0.0

        energy_after = prev_energy + net

        plan.append(
            {
                "hour": h,
                "grid_kwh": max(0.0, grid[h].value() or 0.0),
                "solar_used_kwh": max(0.0, solar_used[h].value() or 0.0),
                "battery_action": action,
                "battery_kwh": magnitude,
                "battery_energy_after_kwh": energy_after,
            }
        )
        prev_energy = energy_after

    return plan
