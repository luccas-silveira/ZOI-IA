from __future__ import annotations

import os
from typing import List

import numpy as np

try:  # OpenAI embeddings se disponível
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

from ..config import EMBEDDING_MODEL


def _hash_embed(text: str, dim: int = 256) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for token in text.lower().split():
        h = hash(token) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec) or 1.0
    return (vec / norm).astype(np.float32)


async def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 256), dtype=np.float32)

    api_key = os.getenv("OPENAI_API_KEY")
    if AsyncOpenAI and api_key:
        try:
            client = AsyncOpenAI()
            resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            vecs = [np.array(d.embedding, dtype=np.float32) for d in resp.data]
            stacked = np.vstack(vecs)
            norms = np.linalg.norm(stacked, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return (stacked / norms).astype(np.float32)
        except Exception:  # pragma: no cover
            pass

    return np.vstack([_hash_embed(t) for t in texts]).astype(np.float32)

