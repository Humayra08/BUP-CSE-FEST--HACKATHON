import logging
from typing import List, Tuple

from app import guardrails
from app.llm_providers import groq_provider, openrouter_provider

logger = logging.getLogger("llm_interpreter")


def _fallback_all_no_op(operator_notes: List[str]) -> list:
    return [
        {
            "note_index": i,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "LLM interpretation unavailable; treated as no_op (not a genuine no_op judgment).",
        }
        for i in range(len(operator_notes))
    ]


async def interpret_notes(operator_notes: List[str], battery_capacity_kwh: float) -> Tuple[list, bool]:
    """Returns (directive_interpretation, degraded).

    degraded=False means a provider's output was fully valid and trustworthy end to end.
    degraded=True means every provider either errored or returned output that guardrails
    had to coerce for at least one note — the returned entries are a SAFE FAILURE fallback
    (never a crash, never an invented rule), but callers/observability should NOT treat
    those no_op entries as genuine interpretation successes.

    Validation happens BEFORE accepting a provider's output: a provider that returns
    syntactically valid JSON but semantically malformed directives (bad hours, out-of-range
    factor, wrong shape, etc.) is treated the same as a hard failure and triggers fallback
    to the next provider, rather than silently keeping the first provider's bad output.
    """
    for provider_name, provider in (("groq", groq_provider), ("openrouter", openrouter_provider)):
        try:
            raw = await provider.interpret(operator_notes)
        except Exception as exc:
            logger.warning("%s interpretation call failed: %s", provider_name, exc)
            continue

        entries, all_valid = guardrails.validate_directives(raw, len(operator_notes), battery_capacity_kwh)
        if all_valid:
            return entries, False

        logger.warning(
            "%s returned malformed/incomplete directives for one or more notes; trying next provider.",
            provider_name,
        )

    logger.error("All LLM providers failed or returned unusable output; falling back to safe no_op defaults.")
    return _fallback_all_no_op(operator_notes), True
