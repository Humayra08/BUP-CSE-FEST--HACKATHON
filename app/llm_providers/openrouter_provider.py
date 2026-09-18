from typing import List

from app import config
from app.llm_providers.base import call_openai_compatible


async def interpret(operator_notes: List[str]) -> list:
    return await call_openai_compatible(
        url=config.OPENROUTER_URL,
        api_key=config.OPENROUTER_API_KEY,
        model=config.OPENROUTER_MODEL,
        operator_notes=operator_notes,
        timeout=config.LLM_TIMEOUT_SECONDS,
        extra_headers={
            "HTTP-Referer": "https://fest.bupcopc.tech",
            "X-Title": "GridWise LLM",
        },
    )
