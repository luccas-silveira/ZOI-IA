import logging
import os
from pathlib import Path

try:  # pragma: no cover - openai is opcional
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None


_PROMPT_PATH = Path(__file__).with_name("prompt.md")


def _system_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "Você é um assistente que responde de forma educada."

async def generate_reply(store: dict) -> str:
    """Gera uma resposta usando as últimas 15 mensagens + contexto.

    - Mapeia inbound -> role=user e outbound -> role=assistant
    - Mantém ordem cronológica (antiga -> recente)
    - Inclui system com prompt.md e, se existir, um system extra com o contexto resumido
    """
    context = store.get("context") or ""
    raw_messages = store.get("messages") or []

    convo: list[dict] = []
    for m in raw_messages:
        if m.get("direction") in {"inbound", "outbound"}:
            convo.append(m)
        if len(convo) >= 15:
            break

    if not convo:
        return ""

    has_inbound = any(m.get("direction") == "inbound" for m in convo)
    if not has_inbound:
        return ""

    if AsyncOpenAI is None:
        return ""

    chat_messages = [
        {"role": "system", "content": _system_prompt()},
    ]
    if context:
        chat_messages.append({
            "role": "system",
            "content": f"Contexto resumido (não compartilhar com o cliente):\n{context}",
        })

    for m in reversed(convo):
        role = "user" if m.get("direction") == "inbound" else "assistant"
        body = m.get("body") or ""
        chat_messages.append({"role": role, "content": str(body)})

    try:
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=chat_messages,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # pragma: no cover
        logging.exception("Falha gerando resposta: %s", exc)
        return ""
