from typing import List

from app import config
from app.llm_providers.base import call_openai_compatible


async def interpret(operator_notes: List[str]) -> list:
    return await call_openai_compatible(
        url=config.GROQ_URL,
        api_key=config.GROQ_API_KEY,
        model=config.GROQ_MODEL,
        operator_notes=operator_notes,
        timeout=config.LLM_TIMEOUT_SECONDS,
        extra_payload={"reasoning_effort": config.GROQ_REASONING_EFFORT},
    )
