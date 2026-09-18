"""Regression runner for the organizers' public sample cases.

Usage:
    python scripts/run_public_samples.py sample_cases/public_samples.json

Expects a JSON file shaped as a list of objects, each with:
  - "request": the full POST /optimize-energy request body
  - "expected_total_cost_bdt" (optional): reference optimal cost to compare against
  - "expected_directives" (optional): list of {note_index, directive_type, applies}
    to check interpretation against, independent of the live LLM

This calls the FastAPI app in-process (no server/network needed) so it also works
offline against mocked directives if "expected_directives" is supplied via
--use-expected-directives, bypassing the LLM entirely to isolate optimizer/guardrail
correctness from language-model accuracy.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import guardrails, optimizer, replay_validator  # noqa: E402
from app.schemas import ScenarioRequest  # noqa: E402


def run_case(case: dict, use_expected_directives: bool) -> dict:
    request_body = case["request"]
    scenario = ScenarioRequest.model_validate(request_body)
    hours_sorted = sorted((h.model_dump() for h in scenario.hours), key=lambda h: h["hour"])
    battery = scenario.battery.model_dump()

    if use_expected_directives and "expected_directives" in case:
        raw = case["expected_directives"]
    else:
        raise SystemExit(
            "This runner only exercises the deterministic optimizer/guardrail path. "
            "Pass --use-expected-directives with a sample file that includes "
            "'expected_directives', or hit the live HTTP API for end-to-end LLM testing."
        )

    directive_interpretation, all_valid = guardrails.validate_directives(
        raw, len(scenario.operator_notes), battery["capacity_kwh"]
    )
    hourly_plan = optimizer.solve_schedule(hours_sorted, battery, directive_interpretation)
    is_valid, totals = replay_validator.replay_and_recompute(
        hourly_plan, hours_sorted, battery, directive_interpretation
    )

    result = {
        "scenario_id": scenario.scenario_id,
        "guardrails_all_valid": all_valid,
        "schedule_valid": is_valid,
        "totals": totals,
    }

    expected_cost = case.get("expected_total_cost_bdt")
    if expected_cost is not None and is_valid:
        result["cost_delta_bdt"] = round(totals["total_cost_bdt"] - expected_cost, 4)
        result["cost_matches"] = abs(result["cost_delta_bdt"]) <= max(0.01, 0.001 * expected_cost)

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples_file", type=Path)
    parser.add_argument(
        "--use-expected-directives",
        action="store_true",
        help="Bypass the LLM and use each case's 'expected_directives' to test optimizer/guardrail correctness in isolation.",
    )
    args = parser.parse_args()

    cases = json.loads(args.samples_file.read_text())
    failures = 0
    for case in cases:
        try:
            result = run_case(case, args.use_expected_directives)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {case.get('request', {}).get('scenario_id', '?')}: {exc}")
            failures += 1
            continue

        ok = result["schedule_valid"] and result.get("cost_matches", True)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] {json.dumps(result)}")

    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
