from typing import Dict, Any, List

from ..summarizer import summarize
from ..config import CONTEXT_SUMMARY_THRESHOLD, CONTEXT_CHUNK_SIZE


async def update_context(store: Dict[str, Any], flush_all: bool = False) -> None:
    messages: List[Dict[str, Any]] = store.get("messages") or []
    if not messages:
        return

    context = store.get("context") or ""

    # Resumo só quando atingir o limiar configurado (ou se for flush explícito)
    if not flush_all and len(messages) < CONTEXT_SUMMARY_THRESHOLD:
        return

    if flush_all:
        to_summarize = messages
        remaining: List[Dict[str, Any]] = []
    else:
        to_summarize = messages[-CONTEXT_CHUNK_SIZE:]
        remaining = messages[:-CONTEXT_CHUNK_SIZE]

    combined = list(to_summarize)
    if context:
        combined.append({"direction": "context", "body": context})
    store["context"] = await summarize(combined)
    store["messages"] = remaining
