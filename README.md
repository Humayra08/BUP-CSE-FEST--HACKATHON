# ⚡ GridWise

LLM-assisted smart campus energy optimization service, built for the BUP CSE Fest 2026 Hackathon (Online Preliminary).

GridWise accepts a 24-hour campus energy scenario along with 1–3 natural-language operator notes, interprets those notes with a language model, validates the interpretation deterministically, and solves for the lowest-cost 24-hour grid/solar/battery schedule that satisfies every constraint.

- 🌐 Live API: `https://<your-render-url>.onrender.com`
- 🐳 Docker image: `<your-dockerhub-username>/gridwise-llm:latest`
- 🔌 Endpoints: `GET /health`, `POST /optimize-energy`

## 🧠 How it works

Operator notes are free text — "keep at least 50% of battery capacity from 6 PM to 9 PM," "don't charge between 2 and 4 PM" — and have to be turned into numbers an optimizer can use, without ever letting the language model's output be trusted blindly. The service is split into four stages:

1. **LLM interpreter** (`app/llm_interpreter.py`, `app/llm_providers/`) — sends the notes, along with the battery's capacity, to Groq (primary) or OpenRouter (fallback), and asks for one structured directive per note: `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, or `no_op`.
2. **Guardrail validator** (`app/guardrails.py`) — plain Python, no model involved. Checks that every directive has a valid type, in-range hours, and correctly shaped numeric fields. Anything malformed is coerced to a safe `no_op` rather than passed through, and triggers a retry against the fallback provider. If both providers fail, every note defaults to `no_op` instead of the service crashing or inventing a rule.
3. **Optimizer** (`app/optimizer.py`) — a linear program (PuLP, CBC solver) that minimizes grid cost across all 24 hours subject to energy balance, battery capacity and rate limits, end-of-day neutrality, and whatever directives survived validation.
4. **Replay validator** (`app/replay_validator.py`) — re-derives the schedule's validity and totals independently of the optimizer's own output, so a bug in step 3 can't silently reach the client.

The reasoning behind this split: the model only has to understand language, not guarantee correctness. Correctness comes from the deterministic layers on either side of it.

```
Energy Data + Operator Notes
        │
        ▼
  LLM Interpreter  ──▶  Guardrail Validator  ──▶  Math Optimizer  ──▶  Replay Validator  ──▶  API Response
  (Groq / OpenRouter)     (deterministic)          (PuLP / CBC)         (independent check)
```

## 📦 Requirements

Python 3.10+. Dependencies are listed in `requirements.txt` — FastAPI, Uvicorn, Pydantic v2, PuLP (ships its own CBC binary, nothing extra to install), httpx, python-dotenv, and pytest/pytest-asyncio for the test suite.

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in your keys. `.env` is gitignored and should never be committed.

```
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_REASONING_EFFORT=low
OPENROUTER_API_KEY=
OPENROUTER_MODEL=deepseek/deepseek-v4-flash-0731:free
LLM_TIMEOUT_SECONDS=6
```

At least one of `GROQ_API_KEY` or `OPENROUTER_API_KEY` is required. Everything else has a working default.

## 🚀 Running locally

```bash
git clone <this-repo-url>
cd BUP-CSE-FEST--HACKATHON

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env           # then fill in your API key(s)

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "GRID-101",
    "operator_notes": [
      "Solar output will drop to about 20% from 1 PM to 3 PM.",
      "Do not charge the battery between 2 PM and 4 PM."
    ],
    "hours": [ /* 24 entries: {"hour", "demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"} */ ],
    "battery": {
      "capacity_kwh": 500,
      "initial_energy_kwh": 200,
      "minimum_energy_kwh": 50,
      "max_charge_kwh_per_hour": 100,
      "max_discharge_kwh_per_hour": 100
    }
  }'
```

Ten fully worked example requests are in `sample_cases/public_samples.json`.

## 📡 API

**`GET /health`** — returns `{"status": "ok"}` once the service is ready.

**`POST /optimize-energy`** — takes `scenario_id`, `operator_notes` (1–3 strings), `hours` (24 entries), and `battery`. Returns:

- `directive_interpretation` — one entry per note, in order, with `applies`, `directive_type`, `structured_adjustment`, and `explanation`
- `hourly_plan` — 24 entries covering grid draw, solar use, and battery action/state for each hour
- `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh` — recomputed from the plan itself, not carried over from the optimizer
- `plan_summary` — a short natural-language recap

`400` for malformed or invalid requests, `500` for controlled internal failures — never a stack trace or raw exception in the response body. The exact schema is defined by the official Problem Statement and implemented in `app/schemas.py`.

## ✅ Testing

```bash
pytest -q
```

38 tests covering schema validation, guardrail coercion of bad LLM output, optimizer correctness (energy balance, battery bounds, directive enforcement, end-of-day neutrality), and the API contract, including provider fallback and malformed input.

To check the deterministic guardrail/optimizer path against the organizer's public samples without hitting a live LLM:

```bash
python scripts/run_public_samples.py sample_cases/public_samples.json --use-expected-directives
```

Separately, all 10 public sample cases were run end-to-end against a live instance of this service with real LLM calls: directive interpretation matched the expected output for all 10, every returned schedule replayed as valid, and total cost matched the reference optimum exactly, with response times consistently under 2 seconds.

## 🐳 Docker

```bash
docker pull <your-dockerhub-username>/gridwise-llm:latest

docker run --rm -p 8000:8000 \
  -e GROQ_API_KEY=your_key_here \
  -e OPENROUTER_API_KEY=your_key_here \
  <your-dockerhub-username>/gridwise-llm:latest

curl http://localhost:8000/health
```

The image listens on port 8000 (configurable via `PORT`), binds to `0.0.0.0`, and has no secrets baked in — keys are passed at `docker run` time. Build it yourself with:

```bash
docker build -t <your-dockerhub-username>/gridwise-llm:latest .
```

## ☁️ Deployment

Deployed on Render using `render.yaml`, which runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. `GROQ_API_KEY` and `OPENROUTER_API_KEY` are configured as Render secrets and are not part of the repository.

## ⚠️ Limitations

- LLM interpretation accuracy depends on the configured model and isn't guaranteed against every possible phrasing; malformed output is always caught by the guardrail layer and degrades to `no_op` rather than producing an incorrect schedule.
- The optimizer runs under a bounded time limit well inside the platform's 30-second request timeout; degenerate inputs could in theory approach that limit, in which case the service returns a controlled error rather than hanging.
- Only Groq and OpenRouter are wired up as providers — there's no offline fallback if both are unreachable.
- Render's free tier cold-starts after idle periods.

## 🛠️ Built with

FastAPI, Pydantic, PuLP/CBC, httpx, python-dotenv — see `requirements.txt` for exact versions. LLM inference via Groq and OpenRouter.
