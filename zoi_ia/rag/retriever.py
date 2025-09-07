from __future__ import annotations

from typing import List

from .index import search


def build_context_snippets(items: List[dict], max_chars: int = 320) -> str:
    lines: List[str] = []
    for it in items:
        body = (it.get("body") or "").strip().replace("\n", " ")
        if len(body) > max_chars:
            body = body[: max_chars - 3] + "..."
        direction = it.get("direction") or ""
        lines.append(f"- ({direction}) {body}")
    return "\n".join(lines)


async def retrieve_context(contact_id: str, query: str, k: int = 5) -> str:
    items = await search(contact_id, query=query, k=k)
    if not items:
        return ""
    return build_context_snippets(items)

