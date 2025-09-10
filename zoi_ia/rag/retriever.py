from __future__ import annotations

from typing import Iterable, List, Set

from .index import search
from ..config import RAG_MAX_SNIPPET_CHARS, RAG_MIN_SIM


def _normalize_text(s: str) -> str:
    return (s or "").strip().replace("\n", " ")


def build_context_snippets(items: List[dict], max_chars: int = RAG_MAX_SNIPPET_CHARS) -> str:
    lines: List[str] = []
    for it in items:
        body = _normalize_text(it.get("body") or "")
        if len(body) > max_chars:
            body = body[: max_chars - 3] + "..."
        direction = it.get("direction") or ""
        lines.append(f"- ({direction}) {body}")
    return "\n".join(lines)


async def retrieve_context(
    contact_id: str,
    query: str,
    k: int,
    *,
    min_sim: float = RAG_MIN_SIM,
    exclude_bodies: Iterable[str] | None = None,
) -> str:
    items = await search(contact_id, query=query, k=k)
    if not items:
        return ""

    normalized_exclude: Set[str] = set()
    if exclude_bodies:
        normalized_exclude = { _normalize_text(b) for b in exclude_bodies if b }

    filtered: List[dict] = []
    for it in items:
        score = float(it.get("score") or 0.0)
        if score < min_sim:
            continue
        body_norm = _normalize_text(it.get("body") or "")
        if body_norm and body_norm in normalized_exclude:
            continue
        filtered.append(it)

    if not filtered:
        return ""
    return build_context_snippets(filtered)
