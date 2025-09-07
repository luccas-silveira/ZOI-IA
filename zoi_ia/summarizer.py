import asyncio
import json
import logging
import os
from typing import Dict, List

from cachetools import TTLCache

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover - fallback se openai não instalado
    AsyncOpenAI = None

try:
    from transformers import pipeline  # type: ignore
except Exception:  # pragma: no cover - fallback se transformers não instalado
    pipeline = None

# cache com expiração para evitar custo repetido
_CACHE = TTLCache(maxsize=128, ttl=3600)
DEFAULT_MAX_MESSAGES = 50


async def summarize(messages: List[Dict[str, str]], max_messages: int = DEFAULT_MAX_MESSAGES, timeout: float = 10.0) -> str:
    """Gera um resumo textual das mensagens."""
    if not messages:
        return ""
    msgs = list(reversed(messages[:max_messages]))
    _CACHE.expire()
    key = json.dumps(msgs, ensure_ascii=False, sort_keys=True)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    text = "\n".join(f"{m.get('direction')}: {m.get('body')}" for m in msgs)
    summary = text
    try:
        if AsyncOpenAI:
            client = AsyncOpenAI()
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
                    messages=[
                        {"role": "system", "content": "Resuma a conversa de forma sucinta."},
                        {"role": "user", "content": text},
                    ],
                ),
                timeout=timeout,
            )
            summary = resp.choices[0].message.content.strip()
        elif pipeline:
            summarizer = pipeline("summarization")
            result = await asyncio.to_thread(
                summarizer, text, max_length=60, min_length=10, do_sample=False
            )
            summary = result[0]["summary_text"].strip()
    except Exception as exc:  # pragma: no cover - log e usa fallback
        logging.exception("Falha ao resumir mensagens: %s", exc)
    _CACHE[key] = summary
    return summary

