from __future__ import annotations

"""Transcrição de áudios (URL -> texto).

Suporta URLs diretas (S3/HTTPS) e, quando possível, URLs do LeadConnector/GHL
utilizando o token de Location como Bearer. Usa OpenAI Whisper (modelo
configurável) quando disponível. Em caso de falha, retorna string vazia.
"""

import io
import logging
import os
from typing import Iterable, Optional, Tuple

import httpx

try:  # OpenAI opcional
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

from .config import (
    AUDIO_MAX_MB,
    AUDIO_MIME_WHITELIST,
    AUDIO_EXT_WHITELIST,
    GHL_API_URL,
    TRANSCRIPTION_MODEL,
)
from .storage import load_location_token


def is_audio_mime(mime: Optional[str]) -> bool:
    if not mime:
        return False
    m = mime.split(";")[0].strip().lower()
    return m in AUDIO_MIME_WHITELIST or m.startswith("audio/")


def is_audio_extension(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        from urllib.parse import urlparse

        path = (urlparse(url).path or "").lower()
        # normaliza a whitelist (sem pontos, sem espaços)
        allowed = {ext.strip().lower().lstrip('.') for ext in AUDIO_EXT_WHITELIST if ext}
        for ext in allowed:
            if path.endswith('.' + ext):
                return True
        return False
    except Exception:
        return False


def _guess_filename(url: str, content_type: Optional[str]) -> str:
    # tenta inferir extensão a partir do content-type
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        mapping = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/aac": ".aac",
            "audio/mp4": ".m4a",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/3gpp": ".3gp",
            "audio/3gpp2": ".3g2",
        }
        ext = mapping.get(ct)
        if ext:
            return f"audio{ext}"
    # fallback: usa o final do path da URL ou um nome genérico
    try:
        from urllib.parse import urlparse

        path = urlparse(url).path or "audio"
        base = path.split("/")[-1] or "audio"
        return base
    except Exception:
        return "audio.bin"


async def _download_audio(url: str, *, max_bytes: int) -> Tuple[bytes, Optional[str]]:
    headers = {}
    token = load_location_token()
    # Se a URL for do domínio do GHL, adiciona Bearer; senão, tenta sem header.
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

        # Verifica tamanho antes/depois
        clen = resp.headers.get("content-length")
        if clen and int(clen) > max_bytes:
            raise ValueError("audio_too_large")

        buf = io.BytesIO()
        async for chunk in resp.aiter_bytes():
            buf.write(chunk)
            if buf.tell() > max_bytes:
                raise ValueError("audio_too_large")
        return buf.getvalue(), ctype


def _mk_named_buffer(data: bytes, filename: str) -> io.BytesIO:
    # OpenAI SDK espera um objeto com atributo `.name`.
    bio = io.BytesIO(data)
    try:
        setattr(bio, "name", filename)
    except Exception:
        pass
    return bio


async def transcribe_from_url(url: str) -> str:
    """Baixa o áudio de `url` e retorna a transcrição em texto.

    Usa `TRANSCRIPTION_MODEL` com OpenAI quando disponível. Em caso de erro,
    loga e retorna string vazia.
    """
    try:
        data, ctype = await _download_audio(url, max_bytes=AUDIO_MAX_MB * 1024 * 1024)
        # Se o Content-Type não parecer de áudio, mas a extensão indicar que é,
        # seguimos em frente; caso contrário, ignoramos.
        if ctype and not is_audio_mime(ctype):
            if not is_audio_extension(url):
                logging.info("Ignorando URL não‑áudio (%s): %s", ctype, url)
                return ""
        filename = _guess_filename(url, ctype)
    except Exception as exc:
        logging.exception("Falha ao baixar áudio: %s", exc)
        return ""

    if AsyncOpenAI is None or not os.getenv("OPENAI_API_KEY"):
        logging.warning("OpenAI indisponível para transcrição; retornando vazio.")
        return ""

    try:
        client = AsyncOpenAI()
        filebuf = _mk_named_buffer(data, filename)
        resp = await client.audio.transcriptions.create(model=TRANSCRIPTION_MODEL, file=filebuf)
        # OpenAI v1 retorna campo `text`
        text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else None)
        return (text or "").strip()
    except Exception as exc:  # pragma: no cover
        logging.exception("Falha na transcrição do áudio: %s", exc)
        return ""


def extract_audio_urls(payload: dict) -> list[str]:
    """Extrai possíveis URLs de áudio de diferentes formatos de payload.

    Considera campos comuns: `attachments`, `messageAttachments`, `media`, `medias`.
    Cada item pode ter `url`, `fileUrl`, `link`, `linkUrl`. Filtra por MIME
    type quando disponível.
    """
    urls: list[str] = []
    if not isinstance(payload, dict):
        return urls

    candidates: Iterable = []
    for key in ("attachments", "messageAttachments", "media", "medias"):
        val = payload.get(key)
        if isinstance(val, list):
            candidates = list(candidates) + val

    for item in candidates:
        # Lista de strings (ex.: ["https://.../file.oga"]) -> usa extensão
        if isinstance(item, str):
            if is_audio_extension(item):
                urls.append(item)
            continue

        # Objetos com metadata (url + mime)
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
                if is_audio_mime(mime):
                    urls.append(str(url))
            else:
                # Sem MIME: decide pela extensão
                if is_audio_extension(url):
                    urls.append(str(url))
    return urls
