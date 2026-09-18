from app.optimizer import build_effective_params
from tests.conftest import make_battery, make_hours


def test_no_directives_leaves_base_params_unchanged():
    hours = make_hours()
    battery = make_battery(minimum=50)
    effective_solar, min_reserve, no_charge, no_discharge, max_grid = build_effective_params(hours, battery, [])
    assert effective_solar == [h["solar_kwh"] for h in hours]
    assert min_reserve == [50.0] * 24
    assert no_charge == [False] * 24
    assert no_discharge == [False] * 24
    assert max_grid == [None] * 24


def test_solar_reduction_only_affects_listed_hours():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [10, 11], "factor": 0.5},
        }
    ]
    effective_solar, *_ = build_effective_params(hours, battery, directives)
    assert effective_solar[10] == hours[10]["solar_kwh"] * 0.5
    assert effective_solar[11] == hours[11]["solar_kwh"] * 0.5
    assert effective_solar[9] == hours[9]["solar_kwh"]


def test_min_reserve_takes_max_of_base_and_directive():
    hours = make_hours()
    battery = make_battery(minimum=50)
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [5], "minimum_energy_kwh": 30},
        },
        {
            "note_index": 1,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [6], "minimum_energy_kwh": 80},
        },
    ]
    _, min_reserve, *_ = build_effective_params(hours, battery, directives)
    assert min_reserve[5] == 50  # base (50) wins over directive's lower 30
    assert min_reserve[6] == 80  # directive's higher value wins over base 50


def test_no_charge_and_no_discharge_flags_isolated_per_hour():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [3, 4]},
        },
        {
            "note_index": 1,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [5]},
        },
    ]
    _, _, no_charge, no_discharge, _ = build_effective_params(hours, battery, directives)
    assert no_charge[3] and no_charge[4] and not no_charge[5]
    assert no_discharge[5] and not no_discharge[3] and not no_discharge[4]


def test_multiple_max_grid_windows_take_the_tighter_cap():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [0], "max_grid_kwh": 100},
        },
        {
            "note_index": 1,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [0], "max_grid_kwh": 60},
        },
    ]
    *_, max_grid = build_effective_params(hours, battery, directives)
    assert max_grid[0] == 60


def test_non_applying_directives_are_ignored():
    hours = make_hours()
    battery = make_battery()
    directives = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
        }
    ]
    effective_solar, min_reserve, no_charge, no_discharge, max_grid = build_effective_params(
        hours, battery, directives
    )
    assert effective_solar == [h["solar_kwh"] for h in hours]
    assert no_charge == [False] * 24
