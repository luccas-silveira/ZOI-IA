from __future__ import annotations

"""Interpretação de imagens (URL -> descrição objetiva em texto).

Utiliza modelo de visão da OpenAI (ex.: gpt-4o-mini) quando disponível. Em
caso de falha ou ausência de chave, retorna string vazia.
"""

import io
import logging
import os
from typing import Iterable, Optional, Tuple

import httpx

try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

from .config import (
    IMAGE_MAX_MB,
    IMAGE_MIME_WHITELIST,
    IMAGE_EXT_WHITELIST,
    GHL_API_URL,
    VISION_MODEL,
)
from .storage import load_location_token


def is_image_mime(mime: Optional[str]) -> bool:
    if not mime:
        return False
    m = mime.split(";")[0].strip().lower()
    return m in IMAGE_MIME_WHITELIST or m.startswith("image/")


def is_image_extension(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        from urllib.parse import urlparse

        path = (urlparse(url).path or "").lower()
        allowed = {ext.strip().lower().lstrip('.') for ext in IMAGE_EXT_WHITELIST if ext}
        for ext in allowed:
            if path.endswith('.' + ext):
                return True
        return False
    except Exception:
        return False


async def _download_image(url: str, *, max_bytes: int) -> Tuple[bytes, Optional[str]]:
    headers = {}
    token = load_location_token()
    if token:
        try:
            if GHL_API_URL and url.lower().startswith(GHL_API_URL.lower()):
                headers["Authorization"] = f"Bearer {token}"
        except Exception:
            pass

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type")
        # tamanho
        clen = resp.headers.get("content-length")
        if clen and int(clen) > max_bytes:
            raise ValueError("image_too_large")
        buf = io.BytesIO()
        async for chunk in resp.aiter_bytes():
            buf.write(chunk)
            if buf.tell() > max_bytes:
                raise ValueError("image_too_large")
        return buf.getvalue(), ctype


async def describe_image_from_url(url: str) -> str:
    """Gera uma descrição concisa da imagem (pt-BR)."""
    # Não precisamos enviar o binário; o modelo aceita URL pública.
    if AsyncOpenAI is None or not os.getenv("OPENAI_API_KEY"):
        logging.warning("OpenAI indisponível para visão; retornando vazio.")
        return ""
    try:
        client = AsyncOpenAI()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Descreva objetivamente a imagem em português, em 1–2 frases. "
                            "Se houver texto legível, inclua-o de forma sucinta."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        resp = await client.chat.completions.create(model=VISION_MODEL, messages=messages)
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # pragma: no cover
        logging.exception("Falha ao descrever imagem: %s", exc)
        return ""


def extract_image_urls(payload: dict) -> list[str]:
    """Extrai URLs de imagem a partir de diversos formatos de payload."""
    urls: list[str] = []
    if not isinstance(payload, dict):
        return urls

    candidates: Iterable = []
    for key in ("attachments", "messageAttachments", "media", "medias"):
        val = payload.get(key)
        if isinstance(val, list):
            candidates = list(candidates) + val

    for item in candidates:
        if isinstance(item, str):
            if is_image_extension(item):
                urls.append(item)
            continue
        if isinstance(item, dict):
            mime = item.get("mimeType") or item.get("contentType") or item.get("mime")
            url = (
                item.get("url")
                or item.get("fileUrl")
                or item.get("link")
                or item.get("linkUrl")
            )
            if not url:
                continue
            if mime:
                if is_image_mime(mime):
                    urls.append(str(url))
            else:
                if is_image_extension(url):
                    urls.append(str(url))
    return urls

