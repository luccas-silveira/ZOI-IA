from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from config import EMBEDDINGS_DIR
from rag.embedding import embed_texts


@dataclass
class IndexedItem:
    id: str
    direction: str
    body: str
    ts: float


def _paths(contact_id: str) -> Tuple[Path, Path]:
    base = EMBEDDINGS_DIR / f"{contact_id}"
    npz = base.with_suffix(".npz")
    meta = base.with_suffix(".meta.json")
    return npz, meta


def load_index(contact_id: str) -> Tuple[np.ndarray, List[str], List[Dict]]:
    npz_path, meta_path = _paths(contact_id)
    if not npz_path.exists() or not meta_path.exists():
        return np.zeros((0, 0), dtype=np.float32), [], []
    # Lê meta primeiro (ids e demais campos ficam aqui)
    meta: List[Dict] = json.loads(meta_path.read_text(encoding="utf-8"))

    # Tenta carregar vetores sem pickle; se o arquivo for legado com arrays-objeto,
    # faz migração automática regravando sem o campo "ids".
    vectors: np.ndarray
    try:
        data = np.load(npz_path, allow_pickle=False)
        keys = set(getattr(data, "files", []) or [])
        if "vectors" not in keys:
            logging.warning("Índice sem 'vectors' para %s; reiniciando.", contact_id)
            return np.zeros((0, 0), dtype=np.float32), [], []
        vectors = data["vectors"].astype(np.float32)
        if "ids" in keys:
            # Arquivo legado: regrava sem 'ids'
            try:
                _save_index(contact_id, vectors, [], meta)
                logging.info("Indice %s migrado para formato sem 'ids'", contact_id)
            except Exception:
                logging.exception("Falha migrando índice legado para %s", contact_id)
    except ValueError:
        # Último recurso: carrega com pickle apenas para extrair 'vectors' e regravar limpo
        try:
            data = np.load(npz_path, allow_pickle=True)
            vectors = data["vectors"].astype(np.float32)
            _save_index(contact_id, vectors, [], meta)
            logging.info("Indice %s migrado (allow_pickle) para formato seguro", contact_id)
        except Exception:
            logging.exception("Falha lendo índice (allow_pickle) para %s", contact_id)
            return np.zeros((0, 0), dtype=np.float32), [], []
    except Exception:
        logging.exception("Falha lendo índice de embeddings para %s", contact_id)
        return np.zeros((0, 0), dtype=np.float32), [], []

    # Ajusta tamanhos caso haja divergência
    n = min(vectors.shape[0], len(meta))
    if vectors.shape[0] != n:
        vectors = vectors[:n]
    if len(meta) != n:
        meta = meta[:n]
    ids = [str(m.get("id", i)) for i, m in enumerate(meta)]
    return vectors, ids, meta


def _save_index(contact_id: str, vectors: np.ndarray, ids: List[str], meta: List[Dict]) -> None:
    npz_path, meta_path = _paths(contact_id)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    # salva apenas vetores; ids ficam no meta JSON
    np.savez_compressed(npz_path, vectors=vectors.astype(np.float32))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_id(direction: str, body: str) -> str:
    # ID determinístico baseado no conteúdo; simples e suficiente para deduplicar
    return f"{direction}:{abs(hash(body))}"


async def upsert_messages(contact_id: str, messages: List[Dict]) -> None:
    if not messages:
        return

    existing_vecs, existing_ids, existing_meta = load_index(contact_id)
    have = set(existing_ids)

    new_items: List[IndexedItem] = []
    for m in messages:
        direction = m.get("direction") or "inbound"
        body = (m.get("body") or "").strip()
        if not body:
            continue
        iid = m.get("id") or _mk_id(direction, body)
        if iid in have:
            continue
        ts = float(m.get("ts") or time.time())
        new_items.append(IndexedItem(id=iid, direction=direction, body=body, ts=ts))

    if not new_items:
        return

    texts = [it.body for it in new_items]
    vecs = await embed_texts(texts)  # (n, d)

    # ajustar dimensão caso índice existente tenha dim diferente
    if existing_vecs.size == 0:
        merged_vecs = vecs
    else:
        d_old = existing_vecs.shape[1]
        d_new = vecs.shape[1]
        if d_old == d_new:
            merged_vecs = np.vstack([existing_vecs, vecs])
        elif d_old > d_new:
            pad = np.zeros((vecs.shape[0], d_old - d_new), dtype=np.float32)
            merged_vecs = np.vstack([existing_vecs, np.hstack([vecs, pad])])
        else:
            pad_old = np.zeros((existing_vecs.shape[0], d_new - d_old), dtype=np.float32)
            merged_vecs = np.vstack([np.hstack([existing_vecs, pad_old]), vecs])

    merged_ids = existing_ids + [it.id for it in new_items]
    merged_meta = existing_meta + [it.__dict__ for it in new_items]

    _save_index(contact_id, merged_vecs, merged_ids, merged_meta)


async def search(contact_id: str, query: str, k: int = 5) -> List[Dict]:
    from numpy.linalg import norm

    if not query:
        return []
    vectors, ids, meta = load_index(contact_id)
    if vectors.size == 0:
        return []

    query_vec = (await embed_texts([query]))[0]

    # cosine similarity
    q = query_vec
    # pad/trunc se precisar
    d = vectors.shape[1]
    if q.shape[0] < d:
        q = np.pad(q, (0, d - q.shape[0]))
    elif q.shape[0] > d:
        q = q[:d]
    sims = (vectors @ q) / (norm(vectors, axis=1) * (norm(q) or 1.0))

    idxs = np.argsort(-sims)[:k]
    results = []
    for i in idxs:
        mi = int(i)
        item = dict(meta[mi])
        item["score"] = float(sims[mi])
        results.append(item)
    return results
