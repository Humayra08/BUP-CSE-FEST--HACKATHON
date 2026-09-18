import pytest

from app import llm_interpreter


@pytest.mark.asyncio
async def test_falls_back_to_openrouter_when_groq_errors(monkeypatch):
    async def fake_groq(notes, battery_capacity_kwh):
        raise RuntimeError("groq down")

    async def fake_openrouter(notes, battery_capacity_kwh):
        return [
            {
                "note_index": 0,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "from openrouter",
            }
        ]

    monkeypatch.setattr(llm_interpreter.groq_provider, "interpret", fake_groq)
    monkeypatch.setattr(llm_interpreter.openrouter_provider, "interpret", fake_openrouter)

    result, degraded = await llm_interpreter.interpret_notes(["irrelevant note"], battery_capacity_kwh=500)
    assert degraded is False
    assert result[0]["explanation"] == "from openrouter"


@pytest.mark.asyncio
async def test_falls_back_to_openrouter_when_groq_returns_malformed_directives(monkeypatch):
    """A provider can return valid JSON with semantically invalid directives (bad hours,
    invented type, out-of-range factor). That must trigger fallback just like a hard
    error, not be silently accepted as the final answer."""

    async def fake_groq(notes, battery_capacity_kwh):
        return [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_boost",  # not a supported type
                "structured_adjustment": {"hours": [1], "factor": 5},
            }
        ]

    async def fake_openrouter(notes, battery_capacity_kwh):
        return [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [1, 2]},
                "explanation": "from openrouter",
            }
        ]

    monkeypatch.setattr(llm_interpreter.groq_provider, "interpret", fake_groq)
    monkeypatch.setattr(llm_interpreter.openrouter_provider, "interpret", fake_openrouter)

    result, degraded = await llm_interpreter.interpret_notes(["note"], battery_capacity_kwh=500)
    assert degraded is False
    assert result[0]["directive_type"] == "no_charge_window"
    assert result[0]["explanation"] == "from openrouter"


@pytest.mark.asyncio
async def test_falls_back_to_no_op_when_both_providers_fail(monkeypatch):
    async def fake_fail(notes, battery_capacity_kwh):
        raise RuntimeError("down")

    monkeypatch.setattr(llm_interpreter.groq_provider, "interpret", fake_fail)
    monkeypatch.setattr(llm_interpreter.openrouter_provider, "interpret", fake_fail)

    result, degraded = await llm_interpreter.interpret_notes(["note a", "note b"], battery_capacity_kwh=500)
    assert degraded is True
    assert len(result) == 2
    assert all(d["directive_type"] == "no_op" for d in result)


@pytest.mark.asyncio
async def test_uses_groq_result_when_it_succeeds(monkeypatch):
    async def fake_groq(notes, battery_capacity_kwh):
        return [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": [1, 2]},
                "explanation": "from groq",
            }
        ]

    async def fail_if_called(notes, battery_capacity_kwh):
        raise AssertionError("openrouter should not be called")

    monkeypatch.setattr(llm_interpreter.groq_provider, "interpret", fake_groq)
    monkeypatch.setattr(llm_interpreter.openrouter_provider, "interpret", fail_if_called)

    result, degraded = await llm_interpreter.interpret_notes(["note a"], battery_capacity_kwh=500)
    assert degraded is False
    assert result[0]["explanation"] == "from groq"
