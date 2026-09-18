from app.guardrails import validate_directives


def test_valid_solar_reduction_passes_through():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
            "explanation": "panel cleaning",
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is True
    assert result[0]["applies"] is True
    assert result[0]["directive_type"] == "solar_reduction"
    assert result[0]["structured_adjustment"] == {"hours": [13, 14], "factor": 0.2}


def test_genuine_no_op_counts_as_valid():
    raw = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "irrelevant",
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is True
    assert result[0]["directive_type"] == "no_op"


def test_invented_type_coerced_to_no_op_and_marked_invalid():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_boost",
            "structured_adjustment": {"hours": [1], "factor": 2.0},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"
    assert result[0]["applies"] is False
    assert result[0]["structured_adjustment"] is None


def test_malformed_hours_coerced_to_no_op():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [5, 3, 3]},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_out_of_range_factor_coerced_to_no_op():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [1, 2], "factor": 1.5},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_infinite_grid_cap_rejected():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [1, 2], "max_grid_kwh": float("inf")},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_nan_reserve_rejected():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [1], "minimum_energy_kwh": float("nan")},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_reserve_exceeding_capacity_coerced_to_no_op():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [1], "minimum_energy_kwh": 9999},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_missing_note_index_defaults_to_no_op_and_marks_invalid():
    raw = []
    result, all_valid = validate_directives(raw, num_notes=2, battery_capacity_kwh=500)
    assert all_valid is False
    assert len(result) == 2
    assert all(d["directive_type"] == "no_op" for d in result)


def test_duplicate_note_index_in_raw_output_marks_invalid():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [1]},
        },
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [2]},
        },
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert len(result) == 1


def test_directive_type_as_list_does_not_crash():
    raw = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": ["solar_reduction"],
            "structured_adjustment": {"hours": [1], "factor": 0.5},
        }
    ]
    result, all_valid = validate_directives(raw, num_notes=1, battery_capacity_kwh=500)
    assert all_valid is False
    assert result[0]["directive_type"] == "no_op"


def test_returns_one_entry_per_note_in_order():
    raw = [
        {"note_index": 1, "applies": False, "directive_type": "no_op", "structured_adjustment": None},
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [10, 11]},
        },
    ]
    result, all_valid = validate_directives(raw, num_notes=2, battery_capacity_kwh=500)
    assert all_valid is True
    assert [d["note_index"] for d in result] == [0, 1]
    assert result[0]["directive_type"] == "no_discharge_window"
    assert result[1]["directive_type"] == "no_op"


def test_completely_garbage_input_never_raises():
    result, all_valid = validate_directives(
        [{"nonsense": True}, "not a dict", None], num_notes=3, battery_capacity_kwh=500
    )
    assert all_valid is False
    assert len(result) == 3
    assert all(d["directive_type"] == "no_op" for d in result)
