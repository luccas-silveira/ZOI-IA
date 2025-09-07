import asyncio
import logging
import random
from typing import List, Dict

import httpx

from ..config import (
    GHL_API_URL,
    GHL_MESSAGES_LIST_VERSION,
    GHL_MESSAGES_WRITE_VERSION,
    HTTP_TIMEOUT,
    HTTP_MAX_RETRIES,
    HTTP_BACKOFF_BASE,
)
from ..storage import load_location_token, load_location_credentials


def _should_retry(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in {429, 500, 502, 503, 504}
    return isinstance(exc, httpx.RequestError)


async def _request_with_retries(method: str, url: str, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
                resp.raise_for_status()
                return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _should_retry(exc) or attempt == HTTP_MAX_RETRIES - 1:
                break
            backoff = HTTP_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.1)
            logging.warning(
                "HTTP %s %s falhou (%s). Retentativa %d em %.2fs.",
                method,
                url,
                type(exc).__name__,
                attempt + 1,
                backoff,
            )
            await asyncio.sleep(backoff)
    raise last_exc  # type: ignore[misc]


async def fetch_conversation_messages(conversation_id: str, limit: int = 30) -> List[Dict]:
    token = load_location_token()
    if not token:
        return []
    url = f"{GHL_API_URL}/conversations/{conversation_id}/messages?limit={limit}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Version": GHL_MESSAGES_LIST_VERSION,
    }
    try:
        resp = await _request_with_retries("GET", url, headers=headers)
        payload = resp.json()
    except Exception:
        logging.exception("Falha buscando mensagens da conversa %s", conversation_id)
        return []

    raw_messages = payload.get("messages", [])
    if isinstance(raw_messages, dict):
        raw_messages = raw_messages.get("messages", [])
    if not isinstance(raw_messages, list):
        logging.warning("Formato inesperado de mensagens: %r", raw_messages)
        return []

    messages: List[Dict] = []
    for item in reversed(raw_messages):
        if not isinstance(item, dict):
            logging.warning("Mensagem inesperada no payload: %r", item)
            continue
        body = item.get("body") or item.get("text") or ""
        direction = item.get("direction") or item.get("messageDirection")
        direction = "outbound" if direction == "outbound" else "inbound"
        messages.append({"direction": direction, "body": body})
    return messages


async def send_outbound_message(contact_id: str, conversation_id: str, body: str) -> bool:
    token, location_id = load_location_credentials()
    if not token or not contact_id or not location_id:
        return False
    url = f"{GHL_API_URL}/conversations/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": GHL_MESSAGES_WRITE_VERSION,
    }
    payload = {
        "locationId": location_id,
        "contactId": contact_id,
        "message": body,
        "type": "SMS",
    }
    if conversation_id:
        payload["conversationId"] = conversation_id
    try:
        await _request_with_retries("POST", url, headers=headers, json=payload)
        return True
    except httpx.HTTPStatusError as exc:  # pragma: no cover
        logging.error("Erro HTTP %s: %s", exc.response.status_code, exc.response.text)
    except Exception:  # pragma: no cover
        logging.exception("Falha enviando mensagem para %s", contact_id)
    return False

