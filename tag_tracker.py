import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

# =========================
# Configurações
# =========================
TAG_NAME = "ia/atendimento/ativa"
STORE_PATH = Path("tag_ia_atendimento_ativa.json")
MESSAGE_STORE_PATH = Path("inbound_messages.json")
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

def load_message_store():
    if MESSAGE_STORE_PATH.exists():
        try:
            return json.loads(MESSAGE_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Falha lendo o inbound store; recriando.")
    return {"lastUpdate": now_iso(), "messages": []}


def save_message_store(store):
    store["lastUpdate"] = now_iso()
    MESSAGE_STORE_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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

    if TAG_NAME in tags:
        ids.add(contact_id)
    else:
        ids.discard(contact_id)

    store["contactIds"] = sorted(ids)  # opcional: manter ordenado
    save_store(store)

    return web.json_response({"ok": True, "present": TAG_NAME in tags})


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

    store = load_message_store()
    msgs = store.get("messages") or []
    msgs.append(event)
    store["messages"] = msgs
    save_message_store(store)

    return web.json_response({"ok": True})


def build_app():
    app = web.Application()
    app.add_routes(
        [
            web.get("/healthz", handle_health),
            web.get("/contacts/ativa", handle_list),
            web.post("/webhooks/ghl/contact-tag", handle_contact_tag),
            web.post("/webhooks/ghl/inbound-message", handle_inbound_message),
        ]
    )
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = build_app()
    web.run_app(app, port=PORT)


if __name__ == "__main__":
    main()