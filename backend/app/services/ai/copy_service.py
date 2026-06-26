"""GPT-5.5 phrasing layer over deterministic spatial facts, with template fallback.

The LLM never decides placements, sizes, or prices - it only rewrites the facts
dict into warmer prose. Any failure (no key, timeout, schema mismatch) falls
back to templates so copy NEVER 5xxs.
"""

import hashlib
import json
import logging
from typing import Any

from app.config import get_settings
from app.services.ai import templates
from app.services.spatial.cache import LRUCache

logger = logging.getLogger("zory.ai")

_client: Any = None
_copy_cache: LRUCache[dict] = LRUCache(get_settings().copy_cache_size)

SYSTEM_PROMPT = (
    "You are ZORY, a friendly interior shopping guide. "
    "Rephrase ONLY the provided facts into warm, plain English. "
    "Never invent dimensions, prices, products, or claims that are not in the facts. "
    "Money amounts in the facts already carry their currency code - repeat them "
    "verbatim if you mention them. Keep every field concise (under 60 words)."
)

DIRECTOR_SYSTEM_PROMPT = (
    "You are ZORY's layout director for FAMILY living rooms. A family living room is centred "
    "on the TV: seating faces the focal/TV wall so everyone can watch together. Using ONLY the "
    "room facts (each wall's length and clear run, doors/windows, total area), the user's "
    "preferences and the seating_capacity, decide which of the available_categories belong, how "
    "many of each, each item's priority (placement order, lower = earlier), and its tier "
    "(necessary = 'essential', optional = 'non_essential').\n"
    "SEATING - each sofa seats 3 people, each accent chair seats 1. To seat N people: use as many "
    "sofas as the seating needs (floor(N / 3), at least 1) BUT NEVER MORE than quantity_caps['sofa'] "
    "- a small room may allow only 1. Then add accent chairs for EVERY remaining seat: "
    "chairs = N - 3 x (sofas you used). Never leave the seating target short when the sofa cap bites. "
    "Examples: N=6, sofa cap 3 -> 2 sofas, 0 chairs; N=6, sofa cap 1 -> 1 sofa + 3 chairs; "
    "N=4 -> 1 sofa + 1 chair; N=8, sofa cap 2 -> 2 sofas + 2 chairs.\n"
    "TIER - sofa, tv_unit, rug, coffee_table, and the accent chairs needed to reach the seating "
    "target are 'essential'. side_table, lighting, storage, decor (and any extra seating) are "
    "'non_essential' - include them only if the room has space.\n"
    "QUANTITIES - respect quantity_caps. Prefer fewer pieces in small rooms; for LARGE rooms "
    "(high room_area_m2) scale non-essential quantities UP toward quantity_caps so the space "
    "doesn't look sparse. Never choose a category outside available_categories. "
    "Output only the structured plan."
)

# Per-kind system prompt; copy kinds share the rephrase-only prompt above.
SYSTEM_PROMPTS: dict[str, str] = {"layout_plan": DIRECTOR_SYSTEM_PROMPT}

SCHEMAS: dict[str, dict] = {
    "guide": {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "tip": {"type": ["string", "null"]},
        },
        "required": ["message", "tip"],
        "additionalProperties": False,
    },
    "why_it_fits": {
        "type": "object",
        "properties": {
            "why_product": {"type": "string"},
            "why_size": {"type": "string"},
            "why_placement": {"type": "string"},
        },
        "required": ["why_product", "why_size", "why_placement"],
        "additionalProperties": False,
    },
    "summary": {
        "type": "object",
        "properties": {
            "narrative": {"type": "string"},
            "upgrade_pitch": {"type": ["string", "null"]},
        },
        "required": ["narrative", "upgrade_pitch"],
        "additionalProperties": False,
    },
    "assistant": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "related_tip": {"type": ["string", "null"]},
        },
        "required": ["answer", "related_tip"],
        "additionalProperties": False,
    },
    "layout_plan": {
        "type": "object",
        "properties": {
            "archetype": {"type": "string"},
            "rationale": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "sofa", "tv_unit", "rug", "coffee_table", "side_table",
                                "accent_chair", "lighting", "storage", "decor",
                            ],
                        },
                        "quantity": {"type": "integer"},
                        "priority": {"type": "integer"},
                        "tier": {"type": "string", "enum": ["essential", "non_essential"]},
                    },
                    "required": ["category", "quantity", "priority", "tier"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["archetype", "rationale", "items"],
        "additionalProperties": False,
    },
}

TEMPLATES = {
    "guide": templates.guide_copy,
    "why_it_fits": templates.why_it_fits,
    "summary": templates.summary_narrative,
}


def _get_client():
    global _client
    settings = get_settings()
    if not settings.llm_enabled:
        return None
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )
    return _client


def _cache_key(kind: str, facts: dict) -> str:
    raw = kind + json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _llm_generate(kind: str, facts: dict, instruction: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None
    key = _cache_key(kind, facts)
    cached = _copy_cache.get(key)
    if cached is not None:
        return cached
    settings = get_settings()
    try:
        resp = await client.responses.create(
            model=settings.openai_model,
            reasoning={"effort": settings.reasoning_effort},
            input=[
                {"role": "system", "content": SYSTEM_PROMPTS.get(kind, SYSTEM_PROMPT)},
                {"role": "user", "content": instruction + "\nFACTS:\n" + json.dumps(facts, default=str)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": f"zory_{kind}",
                    "schema": SCHEMAS[kind],
                    "strict": True,
                }
            },
        )
        data = json.loads(resp.output_text)
        _copy_cache.put(key, data)
        return data
    except Exception as exc:  # noqa: BLE001 - any LLM failure falls back to templates
        logger.warning("LLM copy fallback (%s): %s", kind, exc)
        return None


INSTRUCTIONS = {
    "guide": "Write the guide message (and optional one-line tip) for this furnishing step.",
    "why_it_fits": "Explain why this product, why this size, and why this placement.",
    "summary": "Write a short room summary narrative (and optional upgrade pitch).",
    "assistant": "Answer the user's question using only the facts. If the facts cannot answer it, say so and give the closest helpful guidance.",
    "layout_plan": "Choose the categories, quantities, priority and tier for this family living room from the allowed values; apply the seating rule to seating_capacity.",
}


async def generate(kind: str, facts: dict) -> tuple[dict, str]:
    """Returns (copy dict, source) - source is 'llm' or 'template'."""
    data = await _llm_generate(kind, facts, INSTRUCTIONS[kind])
    if data is not None:
        return data, "llm"
    return TEMPLATES[kind](facts), "template"


async def assistant_answer(question: str, facts: dict) -> tuple[dict, str]:
    data = await _llm_generate("assistant", {"question": question, **facts}, INSTRUCTIONS["assistant"])
    if data is not None:
        return data, "llm"
    return templates.assistant_offline(facts), "offline"


def reset_client() -> None:
    global _client
    _client = None
    _copy_cache.clear()
