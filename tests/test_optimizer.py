from app.optimizer import solve_schedule
from app.replay_validator import replay_and_recompute
from tests.conftest import make_battery, make_hours


def test_baseline_schedule_is_valid_and_balanced():
    hours = make_hours()
    battery = make_battery()
    plan = solve_schedule(hours, battery, directives=[])
    valid, totals = replay_and_recompute(plan, hours, battery, directives=[])
    assert valid
    assert totals["total_grid_kwh"] > 0
    assert len(plan) == 24


def test_no_charge_window_respected():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [10, 11, 12]},
        }
    ]
    plan = solve_schedule(hours, battery, directives)
    valid, _ = replay_and_recompute(plan, hours, battery, directives)
    assert valid
    for h in [10, 11, 12]:
        entry = plan[h]
        assert not (entry["battery_action"] == "charge" and entry["battery_kwh"] > 1e-6)


def test_solar_reduction_lowers_usable_solar():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [10, 11], "factor": 0.0},
        }
    ]
    plan = solve_schedule(hours, battery, directives)
    valid, _ = replay_and_recompute(plan, hours, battery, directives)
    assert valid
    assert plan[10]["solar_used_kwh"] <= 1e-6
    assert plan[11]["solar_used_kwh"] <= 1e-6


def test_minimum_battery_reserve_respected():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 300},
        }
    ]
    plan = solve_schedule(hours, battery, directives)
    valid, _ = replay_and_recompute(plan, hours, battery, directives)
    assert valid
    for h in [18, 19, 20]:
        assert plan[h]["battery_energy_after_kwh"] >= 300 - 0.01


def test_max_grid_window_respected():
    hours = make_hours(demand=120.0)
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [0, 1], "max_grid_kwh": 50},
        }
    ]
    plan = solve_schedule(hours, battery, directives)
    valid, _ = replay_and_recompute(plan, hours, battery, directives)
    assert valid
    assert plan[0]["grid_kwh"] <= 50.01
    assert plan[1]["grid_kwh"] <= 50.01


def test_end_of_day_neutrality():
    hours = make_hours()
    battery = make_battery()
    plan = solve_schedule(hours, battery, directives=[])
    assert abs(plan[23]["battery_energy_after_kwh"] - battery["initial_energy_kwh"]) <= 0.01


def test_no_hour_reports_simultaneous_charge_and_discharge():
    """Regression for a bug where the LP relaxation could assign positive charge AND
    discharge in the same hour (e.g. charge=55, discharge=55 netting to zero real
    movement), and the naive serializer reported only the charge side — silently
    dropping the discharge and breaking energy balance on replay. Every plan entry
    must report a single net action consistent with battery_energy_after_kwh."""
    hours = make_hours(demand=200.0, tariff=8.0)  # flat tariff maximizes LP degeneracy
    battery = make_battery()
    plan = solve_schedule(hours, battery, directives=[])
    valid, _ = replay_and_recompute(plan, hours, battery, directives=[])
    assert valid
    for entry in plan:
        assert entry["battery_action"] in {"charge", "discharge", "idle"}
        if entry["battery_action"] == "idle":
            assert entry["battery_kwh"] == 0.0
