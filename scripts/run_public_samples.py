"""Regression runner for the organizers' public sample cases
(sample_cases/public_samples.json, official GridWise pack schema: top-level
"cases": [{"input": <request>, "expected_output": {...}}, ...]).

Two modes:

  --deterministic (default): bypasses the LLM and feeds each case's own
    expected_output.directive_interpretation straight into guardrails ->
    optimizer -> replay_validator. Isolates optimizer/guardrail/replay
    correctness from live LLM accuracy — this is what should be run in CI /
    before every commit, since it needs no API keys and is fast.

  --live: calls the FastAPI app's real LLM interpretation path (needs
    GROQ_API_KEY / OPENROUTER_API_KEY in the environment) and compares the
    LLM's interpretation against each case's expected directive_type/hours/
    applies, then checks the resulting schedule and cost.

Usage:
    python scripts/run_public_samples.py                # deterministic
    python scripts/run_public_samples.py --live          # full pipeline incl. LLM
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import guardrails, llm_interpreter, optimizer, replay_validator  # noqa: E402
from app.schemas import ScenarioRequest  # noqa: E402

DEFAULT_SAMPLES = Path(__file__).resolve().parent.parent / "sample_cases" / "public_samples.json"
COST_TOL_FRACTION = 0.001  # 0.1% relative, floor of 0.01 BDT per spec's numeric tolerance


def _adjustment_matches(actual: dict, expected: dict) -> bool:
    if actual is None or expected is None:
        return actual == expected
    if actual.get("hours") != expected.get("hours"):
        return False
    for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if key in expected and abs(actual.get(key, float("nan")) - expected[key]) > 0.01:
            return False
    return True


def _score_interpretation(actual: list, expected: list) -> dict:
    total = len(expected)
    matched = 0
    mismatches = []
    for exp in expected:
        idx = exp["note_index"]
        act = next((a for a in actual if a["note_index"] == idx), None)
        ok = (
            act is not None
            and act["applies"] == exp["applies"]
            and act["directive_type"] == exp["directive_type"]
            and _adjustment_matches(act.get("structured_adjustment"), exp.get("structured_adjustment"))
        )
        if ok:
            matched += 1
        else:
            mismatches.append({"note_index": idx, "expected": exp, "actual": act})
    return {"matched": matched, "total": total, "mismatches": mismatches}


def run_deterministic(case: dict) -> dict:
    scenario = ScenarioRequest.model_validate(case["input"])
    hours_sorted = sorted((h.model_dump() for h in scenario.hours), key=lambda h: h["hour"])
    battery = scenario.battery.model_dump()

    expected_directives = case["expected_output"]["directive_interpretation"]
    directive_interpretation, all_valid = guardrails.validate_directives(
        expected_directives, len(scenario.operator_notes), battery["capacity_kwh"]
    )
    hourly_plan = optimizer.solve_schedule(hours_sorted, battery, directive_interpretation)
    is_valid, totals = replay_validator.replay_and_recompute(
        hourly_plan, hours_sorted, battery, directive_interpretation
    )

    expected_cost = case["expected_output"]["total_cost_bdt"]
    cost_ok = is_valid and abs(totals.get("total_cost_bdt", float("inf")) - expected_cost) <= max(
        0.01, COST_TOL_FRACTION * expected_cost
    )

    return {
        "id": case["id"],
        "guardrails_all_valid": all_valid,
        "schedule_valid": is_valid,
        "totals": totals,
        "expected_cost": expected_cost,
        "cost_ok": cost_ok,
        "pass": is_valid and cost_ok,
    }


async def run_live(case: dict) -> dict:
    scenario = ScenarioRequest.model_validate(case["input"])
    hours_sorted = sorted((h.model_dump() for h in scenario.hours), key=lambda h: h["hour"])
    battery = scenario.battery.model_dump()

    directive_interpretation, degraded = await llm_interpreter.interpret_notes(
        scenario.operator_notes, battery["capacity_kwh"]
    )
    interp_score = _score_interpretation(directive_interpretation, case["expected_output"]["directive_interpretation"])

    hourly_plan = optimizer.solve_schedule(hours_sorted, battery, directive_interpretation)
    is_valid, totals = replay_validator.replay_and_recompute(
        hourly_plan, hours_sorted, battery, directive_interpretation
    )

    expected_cost = case["expected_output"]["total_cost_bdt"]
    cost_ok = is_valid and abs(totals.get("total_cost_bdt", float("inf")) - expected_cost) <= max(
        0.01, COST_TOL_FRACTION * expected_cost
    )

    return {
        "id": case["id"],
        "degraded": degraded,
        "interpretation_matched": f"{interp_score['matched']}/{interp_score['total']}",
        "mismatches": interp_score["mismatches"],
        "schedule_valid": is_valid,
        "totals": totals,
        "expected_cost": expected_cost,
        "cost_ok": cost_ok,
        "pass": is_valid and cost_ok and interp_score["matched"] == interp_score["total"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("samples_file", type=Path, nargs="?", default=DEFAULT_SAMPLES)
    parser.add_argument("--live", action="store_true", help="Exercise the real LLM interpretation path.")
    args = parser.parse_args()

    pack = json.loads(args.samples_file.read_text(encoding="utf-8"))
    cases = pack["cases"]

    failures = 0
    for case in cases:
        try:
            result = asyncio.run(run_live(case)) if args.live else run_deterministic(case)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {case['id']}: {exc!r}")
            failures += 1
            continue

        status = "PASS" if result["pass"] else "FAIL"
        if not result["pass"]:
            failures += 1
        print(f"[{status}] {case['id']}: {json.dumps(result, default=str)}")

    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
