from typing import Dict, Any, List

from ..summarizer import summarize


async def update_context(store: Dict[str, Any], flush_all: bool = False) -> None:
    messages: List[Dict[str, Any]] = store.get("messages") or []
    if not messages:
        return

    context = store.get("context") or ""

    if not flush_all and len(messages) < 30:
        return

    if flush_all:
        to_summarize = messages
        remaining: List[Dict[str, Any]] = []
    else:
        to_summarize = messages[-15:]
        remaining = messages[:-15]

    combined = list(to_summarize)
    if context:
        combined.append({"direction": "context", "body": context})
    store["context"] = await summarize(combined)
    store["messages"] = remaining

