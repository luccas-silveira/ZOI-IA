import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
import httpx

from summarizer import summarize

# =========================
# Configurações
# =========================
TAG_NAME = "ia - ativa"
STORE_PATH = Path("tag_ia_atendimento_ativa.json")
MESSAGES_DIR = Path("messages")
LOCATION_TOKEN_PATH = Path("location_token.json")
PORT = 8081

# Opcional: verificar assinatura RSA dos webhooks (requer 'cryptography')
VERIFY_SIGNATURE = True

# Chave pública oficial (Webhook Authentication Guide)
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAokvo/r9tVgcfZ5DysOSC
Frm602qYV0MaAiNnX9O8KxMbiyRKWeL9JpCpVpt4XHIcBOK4u3cLSqJGOLaPuXw6
dO0t6Q/ZVdAV5Phz+ZtzPL16iCGeK9po6D6JHBpbi989mmzMryUnQJezlYJ3DVfB
csedpinheNnyYeFXolrJvcsjDtfAeRx5ByHQmTnSdFUzuAnC9/GepgLT9SM4nCpv
uxmZMxrJt5Rw+VUaQ9B8JSvbMPpez4peKaJPZHBbU3OdeCVx5klVXXZQGNHOs8gF
3kvoV5rTnXV0IknLBXlcKKAQLZcY/Q9rG6Ifi9c+5vqlvHPCUJFT5XUGG5RKgOKU
J062fRtN+rLYZUV+BjafxQauvC8wSWeYja63VSUruvmNj8xkx2zE/Juc+yjLjTXp
IocmaiFeAO6fUtNjDeFVkhf5LNb59vECyrHD2SQIrhgXpO4Q3dVNA5rw576PwTzN
h/AMfHKIjE4xQA1SZuYJmNnmVZLIZBlQAF9Ntd03rfadZ+yDiOXCCs9FkHibELhC
HULgCsnuDJHcrGNd5/Ddm5hxGQ0ASitgHeMZ0kcIOwKDOzOU53lDza6/Y09T7sYJ
PQe7z0cvj7aE4B+Ax1ZoZGPzpJlZtGXCsu9aTEGEnKzmsFqwcSsnw3JB31IGKAyk
T1hhTiaCeIY/OwwwNUY2yvcCAwEAAQ==
-----END PUBLIC KEY-----"""

# Memória (simples) para idempotência
PROCESSED_TAGS = set()
PROCESSED_MESSAGES = set()
PROCESSED_OUTBOUND_MESSAGES = set()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_store():
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Falha lendo o store; recriando.")
    # Apenas IDs
    return {"lastUpdate": now_iso(), "contactIds": []}

def save_store(store):
    store["lastUpdate"] = now_iso()
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

def load_contact_messages(contact_id: str):
    MESSAGES_DIR.mkdir(exist_ok=True)
    path = MESSAGES_DIR / f"{contact_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("messages", [])
            data.setdefault("context", "")
            return data
        except Exception:
            logging.exception("Falha lendo o histórico de %s; recriando.", contact_id)
    return {"lastUpdate": now_iso(), "messages": [], "context": ""}

def save_contact_messages(contact_id: str, store):
    store["lastUpdate"] = now_iso()
    store.setdefault("context", "")
    MESSAGES_DIR.mkdir(exist_ok=True)
    path = MESSAGES_DIR / f"{contact_id}.json"
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

async def update_context(store: dict, flush_all: bool = False) -> None:
    messages = store.get("messages") or []
    if not messages:
        return

    context = store.get("context") or ""

    if not flush_all and len(messages) < 30:
        return

    if flush_all:
        to_summarize = messages
        remaining = []
    else:
        to_summarize = messages[:15]
        remaining = messages[15:]

    combined = []
    if context:
        combined.append({"direction": "context", "body": context})
    combined.extend(to_summarize)
    store["context"] = await summarize(combined)
    store["messages"] = remaining

def load_location_token():
    try:
        data = json.loads(LOCATION_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        logging.exception("Falha lendo location_token.json")
        return None

async def fetch_conversation_messages(conversation_id: str, limit: int = 30):
    token = load_location_token()
    if not token:
        return []
    url = (
        f"https://services.leadconnectorhq.com/conversations/{conversation_id}/messages"
        f"?limit={limit}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Version": "2021-04-15",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
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

    messages = []
    for item in raw_messages:
        if not isinstance(item, dict):
            logging.warning("Mensagem inesperada no payload: %r", item)
            continue
        body = item.get("body") or item.get("text") or ""
        direction = item.get("direction") or item.get("messageDirection")
        direction = "outbound" if direction == "outbound" else "inbound"
        messages.append({
            "direction": direction,
            "body": body,
        })
    return messages

def verify_signature(payload_bytes: bytes, signature_b64: str) -> bool:
    if not VERIFY_SIGNATURE:
        return True
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
    except Exception:
        logging.warning("biblioteca 'cryptography' não instalada; pulando verificação de assinatura")
        return True  # aceite, mas logue

    try:
        pub = load_pem_public_key(PUBLIC_KEY_PEM)
        sig = base64.b64decode(signature_b64)
        pub.verify(sig, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception as e:
        logging.error("Assinatura inválida: %s", e)
        return False

async def handle_health(_req):
    return web.json_response({"ok": True})

async def handle_list(_req):
    store = load_store()
    # Retorna só os IDs atualmente com a tag
    return web.json_response(
        {
            "tag": TAG_NAME,
            "count": len(store["contactIds"]),
            "ids": store["contactIds"],
            "lastUpdate": store["lastUpdate"],
        }
    )

async def handle_contact_tag(request: web.Request):
    raw = await request.read()

    # Verifica assinatura se presente
    sig = request.headers.get("x-wh-signature") or request.headers.get("X-Wh-Signature")
    if sig and not verify_signature(raw, sig):
        return web.json_response({"error": "invalid signature"}, status=401)

    # Converte JSON
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    # Idempotência (se o webhookId vier no payload)
    wh_id = event.get("webhookId")
    if wh_id:
        if wh_id in PROCESSED_TAGS:
            return web.json_response({"ok": True, "dedup": True})
        PROCESSED_TAGS.add(wh_id)

    # Checa tipo do evento
    if event.get("type") != "ContactTagUpdate":
        return web.json_response({"ok": True, "ignored": True})

    tags = event.get("tags") or []
    contact_id = event.get("id")
    if not contact_id:
        return web.json_response({"error": "missing contact id"}, status=422)

    store = load_store()
    ids = set(store.get("contactIds") or [])
    had_tag = contact_id in ids
    has_tag_now = TAG_NAME in tags

    if has_tag_now and not had_tag:
        ids.add(contact_id)
        store["contactIds"] = sorted(ids)
        save_store(store)
        msg_store = load_contact_messages(contact_id)
        conversation_id = msg_store.get("conversationId")
        if conversation_id:
            history = await fetch_conversation_messages(conversation_id)
            msg_store["messages"] = history
            msg_store["historyFetched"] = True
        await update_context(msg_store, flush_all=True)
        save_contact_messages(contact_id, msg_store)
    elif not has_tag_now and had_tag:
        ids.discard(contact_id)
        store["contactIds"] = sorted(ids)
        save_store(store)
        msg_store = load_contact_messages(contact_id)
        await update_context(msg_store, flush_all=True)
        msg_store = {"messages": [], "context": msg_store.get("context", "")}
        save_contact_messages(contact_id, msg_store)
    else:
        if has_tag_now:
            ids.add(contact_id)
        else:
            ids.discard(contact_id)
        store["contactIds"] = sorted(ids)
        save_store(store)

    return web.json_response({"ok": True, "present": has_tag_now})

async def handle_inbound_message(request: web.Request):
    raw = await request.read()

    sig = request.headers.get("x-wh-signature") or request.headers.get("X-Wh-Signature")
    if sig and not verify_signature(raw, sig):
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    wh_id = event.get("webhookId")
    if wh_id:
        if wh_id in PROCESSED_MESSAGES:
            return web.json_response({"ok": True, "dedup": True})
        PROCESSED_MESSAGES.add(wh_id)

    contact_id = event.get("contactId")
    if not contact_id:
        return web.json_response({"error": "missing contact id"}, status=422)
    body = event.get("body")
    conversation_id = event.get("conversationId")

    store = load_contact_messages(contact_id)
    if conversation_id is not None:
        store["conversationId"] = conversation_id
        if not store.get("historyFetched"):
            history = await fetch_conversation_messages(conversation_id)
            store["messages"] = history
            store["historyFetched"] = True
    msgs = store.get("messages") or []
    msgs.append({
        "direction": "inbound",
        "body": body,
        "conversationId": conversation_id,
    })
    store["messages"] = msgs
    if len(store["messages"]) >= 30:
        await update_context(store)
    save_contact_messages(contact_id, store)

    return web.json_response({"ok": True})

async def handle_outbound_message(request: web.Request):
    raw = await request.read()

    sig = request.headers.get("x-wh-signature") or request.headers.get("X-Wh-Signature")
    if sig and not verify_signature(raw, sig):
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    wh_id = event.get("webhookId")
    if wh_id:
        if wh_id in PROCESSED_OUTBOUND_MESSAGES:
            return web.json_response({"ok": True, "dedup": True})
        PROCESSED_OUTBOUND_MESSAGES.add(wh_id)

    contact_id = event.get("contactId")
    if not contact_id:
        return web.json_response({"error": "missing contact id"}, status=422)
    body = event.get("body")
    conversation_id = event.get("conversationId")

    store = load_contact_messages(contact_id)
    if conversation_id is not None:
        store["conversationId"] = conversation_id
        if not store.get("historyFetched"):
            history = await fetch_conversation_messages(conversation_id)
            store["messages"] = history
            store["historyFetched"] = True
    msgs = store.get("messages") or []
    msgs.append({
        "direction": "outbound",
        "body": body,
        "conversationId": conversation_id,
    })
    store["messages"] = msgs
    if len(store["messages"]) >= 30:
        await update_context(store)
    save_contact_messages(contact_id, store)

    return web.json_response({"ok": True})

def build_app():
    app = web.Application()
    app.add_routes(
        [
            web.get("/healthz", handle_health),
            web.get("/contacts/ativa", handle_list),
            web.post("/webhooks/ghl/contact-tag", handle_contact_tag),
            web.post("/webhooks/ghl/inbound-message", handle_inbound_message),
            web.post("/webhooks/ghl/outbound-message", handle_outbound_message),
        ]
    )
    return app

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = build_app()
    web.run_app(app, port=PORT)

if __name__ == "__main__":
    main()
