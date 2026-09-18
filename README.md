# GridWise LLM — Smart Campus Energy Optimization API

LLM-assisted operator-note interpretation + linear-programming energy scheduling for the
BUP CSE Fest 2026 preliminary hackathon (Smart Campus Energy Optimization Challenge).

## Pipeline

```
Energy data + operator notes
        │
        ▼
LLM Interpreter (Groq primary, OpenRouter fallback)
        │  raw, untrusted directive JSON
        ▼
Guardrail Validator (deterministic; coerces anything malformed to no_op)
        │  validated directives
        ▼
Math Optimizer (PuLP/CBC linear program, minimizes grid cost)
        │  hourly_plan
        ▼
Replay Validator (independently recomputes totals + re-checks every rule)
        │
        ▼
API Response
```

If **both** LLM providers fail, or either returns output that fails guardrail
validation for any note, the service falls back to safe `no_op` interpretation for
the unresolved notes rather than crashing or inventing a rule — it always still
returns a valid, optimal 24-hour schedule.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # then fill in GROQ_API_KEY / OPENROUTER_API_KEY
```

## Run locally

```bash
uvicorn app.main:app --reload --port 8000
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/optimize-energy -H "Content-Type: application/json" -d @sample_request.json
```

## Run with Docker

```bash
docker build -t gridwise-llm .
docker run --rm -p 8000:8000 --env-file .env gridwise-llm
```

## Tests

```bash
pytest -q
```

Test layers:
- `tests/test_guardrails.py`, `tests/test_effective_params.py` — deterministic validation/constraint-application unit tests, including malformed/adversarial LLM output (invented types, infinite/NaN values, duplicate note indices).
- `tests/test_optimizer.py` — LP correctness per directive type, energy balance, end-of-day neutrality, and a regression test for the charge/discharge-cancellation serialization bug.
- `tests/test_llm_interpreter.py` — provider fallback chain (hard errors **and** malformed-but-valid-JSON output both trigger fallback).
- `tests/test_api.py` — full HTTP integration, plus edge cases (blank notes, duplicate hours, negative/NaN values, battery ordering violations) that must return clean `400`s.

## Public sample regression

Organizer-provided public sample cases are **not included in this repo** (they must
be supplied by you/the organizers). Once you have `sample_cases/public_samples.json`
in the documented shape (see `scripts/run_public_samples.py` docstring), run:

```bash
python scripts/run_public_samples.py sample_cases/public_samples.json --use-expected-directives
```

This exercises the optimizer + guardrail + replay path directly against each
sample's known-correct directives, isolating math/schedule correctness from live
LLM interpretation accuracy. To test the full pipeline including the LLM, POST each
sample's `request` to a running server instead.

## Deployment (Render)

`render.yaml` is configured for Render's free web-service plan. Set `GROQ_API_KEY`
and `OPENROUTER_API_KEY` as environment variables in the Render dashboard (they are
marked `sync: false` and are never committed).

**Known risk:** Render's free plan spins the service down after ~15 minutes of
inactivity; the next request pays a cold-start penalty of roughly a minute, which can
blow through the judge harness's latency thresholds on the first hit. If the
evaluation window matters, either keep the service warm with a periodic health-check
ping during the round, or upgrade to a paid instance type before judging starts.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key (primary LLM) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id |
| `GROQ_REASONING_EFFORT` | `low` | Lower reasoning effort trims latency/tokens for this extraction task |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (fallback LLM) |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4-flash-0731:free` | OpenRouter free-tier model id |
| `LLM_TIMEOUT_SECONDS` | `6` | Per-provider HTTP timeout |

Both configured models were verified live against the deployed keys; Groq's older
`llama-3.3-70b-versatile` and OpenRouter's `meta-llama/*:free` slugs are no longer
served on free tiers as of this writing — recheck availability before relying on any
specific model id.

## Known limitations / follow-ups

- LLM interpretation accuracy (paraphrase robustness, edge-case wording) is not
  covered by automated tests here — only guardrail/optimizer correctness is, since
  those don't require live API calls. Benchmark against the organizers' hidden-style
  paraphrases before the round if possible.
- The optimizer and replay validator share `build_effective_params` (single source of
  truth for "what a directive means mathematically"). This is intentional, but a bug
  there would affect both; `tests/test_effective_params.py` exercises that function
  directly and independently of both callers to catch regressions early.
- No authentication/rate limiting is implemented — out of scope per the problem
  statement, but worth knowing before exposing the deployed URL widely.
