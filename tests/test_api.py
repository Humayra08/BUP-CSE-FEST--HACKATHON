import pytest
from fastapi.testclient import TestClient

from app import llm_interpreter
from app.main import app
from tests.conftest import make_battery, make_hours

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_optimize_energy_end_to_end(monkeypatch):
    async def fake_interpret(notes, battery_capacity_kwh):
        entries = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
                "explanation": "Solar reduced for maintenance.",
            },
            {
                "note_index": 1,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [14, 15]},
                "explanation": "Charging paused.",
            },
            {
                "note_index": 2,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Irrelevant to the energy schedule.",
            },
        ]
        return entries, False

    monkeypatch.setattr(llm_interpreter, "interpret_notes", fake_interpret)

    payload = {
        "scenario_id": "GRID-101",
        "operator_notes": [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "The cafeteria menu changes tomorrow.",
        ],
        "hours": make_hours(),
        "battery": make_battery(),
    }

    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    assert body["scenario_id"] == "GRID-101"
    assert len(body["directive_interpretation"]) == 3
    assert [d["note_index"] for d in body["directive_interpretation"]] == [0, 1, 2]
    assert len(body["hourly_plan"]) == 24
    assert body["total_cost_bdt"] > 0
    assert "total_grid_kwh" in body
    assert "peak_grid_kwh" in body
    assert isinstance(body["plan_summary"], str) and body["plan_summary"]


def test_malformed_json_returns_400():
    resp = client.post("/optimize-energy", content=b"{not json", headers={"content-type": "application/json"})
    assert resp.status_code == 400


def test_invalid_schema_returns_400():
    resp = client.post("/optimize-energy", json={"scenario_id": "X"})
    assert resp.status_code == 400


def test_blank_operator_note_returns_400_with_json_safe_details():
    payload = {
        "scenario_id": "GRID-BLANK",
        "operator_notes": ["   "],
        "hours": make_hours(),
        "battery": make_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    # Must be plain JSON-serializable content, not a raw Python exception object leaking through.
    body = resp.json()
    assert "details" in body


def test_duplicate_hour_returns_400():
    hours = make_hours()
    hours[1] = dict(hours[0])  # duplicate hour 0, missing hour 1
    payload = {
        "scenario_id": "GRID-DUP",
        "operator_notes": ["A note."],
        "hours": hours,
        "battery": make_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400


def test_negative_demand_returns_400():
    hours = make_hours()
    hours[0]["demand_kwh"] = -5
    payload = {
        "scenario_id": "GRID-NEG",
        "operator_notes": ["A note."],
        "hours": hours,
        "battery": make_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400


def test_initial_energy_below_minimum_returns_400():
    payload = {
        "scenario_id": "GRID-BATT",
        "operator_notes": ["A note."],
        "hours": make_hours(),
        "battery": make_battery(initial=10, minimum=50),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
