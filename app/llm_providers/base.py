import json
from typing import List

import httpx

SYSTEM_PROMPT = """You are an operator-note interpreter for a campus energy scheduling system.

You will be given a list of natural-language operator notes (0-indexed) about a 24-hour energy schedule.
Convert each note into EXACTLY one directive using ONLY these types:

- solar_reduction: reduce usable solar during specific hours.
  structured_adjustment: {"hours": [int, ...], "factor": number}  (factor = fraction of solar that REMAINS, e.g. an 80% drop means factor=0.2)
- minimum_battery_reserve: keep battery energy at or above a level during specific hours.
  structured_adjustment: {"hours": [int, ...], "minimum_energy_kwh": number}
- no_charge_window: battery charging is unavailable during specific hours.
  structured_adjustment: {"hours": [int, ...]}
- no_discharge_window: battery discharging is unavailable during specific hours.
  structured_adjustment: {"hours": [int, ...]}
- max_grid_window: grid import may not exceed a stated amount during specific hours.
  structured_adjustment: {"hours": [int, ...], "max_grid_kwh": number}
- no_op: the note does NOT affect the 24-hour energy schedule (distractor / irrelevant note).
  structured_adjustment: null

Rules:
- Time windows use whole-hour integers 0-23. The start hour is INCLUDED and the end hour is EXCLUDED.
  Example: "1 PM to 3 PM" means hours [13, 14] (NOT 15).
- "hours" arrays must contain unique integers 0-23 in ascending order.
- For no_op: applies=false, directive_type="no_op", structured_adjustment=null.
- For every other type: applies=true and structured_adjustment must match the exact shape above.
- Do NOT invent a directive type outside the six listed. Do NOT invent demand, tariff, or battery numbers.
- If a note is ambiguous or does not describe an energy rule, use no_op.

Example notes and expected interpretation:
"Solar output will drop to about 20% from 1 PM to 3 PM." -> solar_reduction; hours [13,14]; factor 0.2
"Do not charge the battery between 2 PM and 4 PM." -> no_charge_window; hours [14,15]
"Keep at least 120 kWh in reserve from 6 PM until 9 PM." -> minimum_battery_reserve; hours [18,19,20]; minimum_energy_kwh 120
"The cafeteria menu changes tomorrow." -> no_op

Respond with STRICT JSON ONLY, no markdown, no commentary, in this exact shape:
{"directives": [
  {"note_index": 0, "applies": true, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [13,14], "factor": 0.2}, "explanation": "..."},
  ...
]}
One entry per note, in note_index order, covering every note exactly once.
"""


def build_messages(operator_notes: List[str]) -> list:
    numbered = "\n".join(f"{i}: {note}" for i, note in enumerate(operator_notes))
    user_prompt = f"Operator notes:\n{numbered}\n\nReturn the JSON now."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def parse_directives_json(raw_text: str) -> list:
    """Extract the directives list from a raw LLM text response. Raises on total failure."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)
    directives = data["directives"]
    if not isinstance(directives, list):
        raise ValueError("directives is not a list")
    return directives


async def call_openai_compatible(
    url: str,
    api_key: str,
    model: str,
    operator_notes: List[str],
    timeout: float,
    extra_headers: dict | None = None,
    extra_payload: dict | None = None,
) -> list:
    """Calls an OpenAI-compatible chat completions endpoint and returns parsed directives.
    Raises on HTTP/network error or on unparseable output — caller decides how to handle."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": build_messages(operator_notes),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 1200,
    }
    if extra_payload:
        payload.update(extra_payload)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    return parse_directives_json(content)
