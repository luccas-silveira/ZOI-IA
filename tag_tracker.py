import base64
import json
import logging
from aiohttp import web

from zoi_ia.ai_agent import generate_reply
from zoi_ia.config import (
    TAG_NAME,
    PORT,
    VERIFY_SIGNATURE,
    PUBLIC_KEY_PEM,
    RAG_ENABLED,
    RAG_K,
    RAG_MIN_SIM,
    TRANSCRIBE_AUDIO,
    LOG_WEBHOOKS,
)
from zoi_ia.storage import (
    load_store,
    save_store,
    load_contact_messages,
    save_contact_messages,
)
from zoi_ia.clients.ghl_client import (
    fetch_conversation_messages,
    send_outbound_message,
)
from zoi_ia.services.context_service import update_context
from zoi_ia.rag.index import upsert_messages
from zoi_ia.rag.retriever import retrieve_context
from zoi_ia.transcriber import extract_audio_urls, transcribe_from_url
from zoi_ia.vision import extract_image_urls, describe_image_from_url
# =========================
# Configurações
# =========================

PROCESSED_TAGS = set()
PROCESSED_MESSAGES = set()
PROCESSED_OUTBOUND_MESSAGES = set()
AI_GENERATED_MESSAGES = set()

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
        # garante estrutura mínima do fluxo
        msg_store.setdefault("flow", {"current_step": "", "checklist": []})
        conversation_id = msg_store.get("conversationId")
        if conversation_id:
            history = await fetch_conversation_messages(conversation_id)
            msg_store["messages"] = history
            msg_store["historyFetched"] = True
            if RAG_ENABLED:
                # indexa histórico inicial
                await upsert_messages(contact_id, history)
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
    if LOG_WEBHOOKS:
        try:
            logging.info("Inbound RAW: %s", raw.decode("utf-8", errors="replace"))
        except Exception:
            logging.info("Inbound RAW: <binary %d bytes>", len(raw))

    sig = request.headers.get("x-wh-signature") or request.headers.get("X-Wh-Signature")
    if sig and not verify_signature(raw, sig):
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if LOG_WEBHOOKS:
        logging.info("Inbound JSON: %s", json.dumps(event, ensure_ascii=False))

    wh_id = event.get("webhookId")
    if wh_id:
        if wh_id in PROCESSED_MESSAGES:
            return web.json_response({"ok": True, "dedup": True})
        PROCESSED_MESSAGES.add(wh_id)

    contact_id = event.get("contactId")
    if not contact_id:
        return web.json_response({"error": "missing contact id"}, status=422)
    body = event.get("body")
    orig_body = body
    conversation_id = event.get("conversationId")

    # Gate: só processa se o contato tiver a tag ativa
    store_tags = load_store()
    active_ids = set(store_tags.get("contactIds") or [])
    if contact_id not in active_ids:
        if LOG_WEBHOOKS:
            logging.info("Ignorando inbound: contato %s sem tag ativa", contact_id)
        return web.json_response({"ok": True, "ignored": True, "reason": "no_tag"})

    store = load_contact_messages(contact_id)
    store.setdefault("flow", {"current_step": "", "checklist": []})
    if conversation_id is not None:
        store["conversationId"] = conversation_id
        if not store.get("historyFetched"):
            history = await fetch_conversation_messages(conversation_id)
            store["messages"] = history
            store["historyFetched"] = True
    msgs = store.get("messages") or []
    msgs.insert(0, {
        "direction": "inbound",
        "body": body,
        "conversationId": conversation_id,
    })
    # Transcrição de áudios (se habilitado) — substitui o corpo do inbound
    if TRANSCRIBE_AUDIO:
        audio_urls = extract_audio_urls(event)
        if LOG_WEBHOOKS:
            logging.info("Audio URLs detectados: %s", audio_urls)
        transcripts: list[str] = []
        for url in audio_urls:
            text = await transcribe_from_url(url)
            if text:
                transcripts.append(text)
        if transcripts:
            new_body = "\n\n".join(transcripts)
            msgs[0]["body"] = new_body
            body = new_body

    # Descrição de imagens (se habilitado) — substitui ou concatena
    from zoi_ia.config import DESCRIBE_IMAGES  # import local para evitar ciclos
    if DESCRIBE_IMAGES:
        image_urls = extract_image_urls(event)
        if LOG_WEBHOOKS:
            logging.info("Image URLs detectados: %s", image_urls)
        descriptions: list[str] = []
        for url in image_urls:
            desc = await describe_image_from_url(url)
            if desc:
                descriptions.append(desc)
        if descriptions:
            # Se já substituímos por áudio, concatena; senão, substitui
            if body != orig_body and body:
                combined = [body] + descriptions
                new_body = "\n\n".join(combined)
            else:
                new_body = "\n\n".join(descriptions)
            msgs[0]["body"] = new_body
            body = new_body
    store["messages"] = msgs
    if len(store["messages"]) >= 30:
        await update_context(store)
    save_contact_messages(contact_id, store)
    if RAG_ENABLED:
        await upsert_messages(contact_id, [msgs[0]])

    store_tags = load_store()
    if contact_id in set(store_tags.get("contactIds") or []):
        extra = ""
        if RAG_ENABLED:
            # evita duplicar conteúdo que já está nas últimas mensagens
            last_msgs = (store.get("messages") or [])[:15]
            exclude = [m.get("body") or "" for m in last_msgs]
            extra = await retrieve_context(
                contact_id,
                body or "",
                k=RAG_K,
                min_sim=RAG_MIN_SIM,
                exclude_bodies=exclude,
            )
        else:
            extra = ""
        reply = await generate_reply(store, extra_context=(extra or None))
        if reply:
            ok = await send_outbound_message(contact_id, conversation_id, reply)
            if ok:
                AI_GENERATED_MESSAGES.add((conversation_id, reply))
                msgs = store.get("messages") or []
                msgs.insert(0, {
                    "direction": "outbound",
                    "body": reply,
                    "conversationId": conversation_id,
                })
                store["messages"] = msgs
                if len(store["messages"]) >= 30:
                    await update_context(store)
                save_contact_messages(contact_id, store)
                if RAG_ENABLED:
                    await upsert_messages(contact_id, [msgs[0]])

    return web.json_response({"ok": True})

async def handle_outbound_message(request: web.Request):
    raw = await request.read()
    if LOG_WEBHOOKS:
        try:
            logging.info("Outbound RAW: %s", raw.decode("utf-8", errors="replace"))
        except Exception:
            logging.info("Outbound RAW: <binary %d bytes>", len(raw))

    sig = request.headers.get("x-wh-signature") or request.headers.get("X-Wh-Signature")
    if sig and not verify_signature(raw, sig):
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if LOG_WEBHOOKS:
        logging.info("Outbound JSON: %s", json.dumps(event, ensure_ascii=False))

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
    # Gate: só processa se o contato tiver a tag ativa
    store_tags = load_store()
    active_ids = set(store_tags.get("contactIds") or [])
    if contact_id not in active_ids:
        if LOG_WEBHOOKS:
            logging.info("Ignorando outbound: contato %s sem tag ativa", contact_id)
        return web.json_response({"ok": True, "ignored": True, "reason": "no_tag"})

    if (conversation_id, body) in AI_GENERATED_MESSAGES:
        AI_GENERATED_MESSAGES.discard((conversation_id, body))
        return web.json_response({"ok": True, "ignored": True})

    store = load_contact_messages(contact_id)
    store.setdefault("flow", {"current_step": "", "checklist": []})
    if conversation_id is not None:
        store["conversationId"] = conversation_id
        if not store.get("historyFetched"):
            history = await fetch_conversation_messages(conversation_id)
            store["messages"] = history
            store["historyFetched"] = True
    msgs = store.get("messages") or []
    msgs.insert(0, {
        "direction": "outbound",
        "body": body,
        "conversationId": conversation_id,
    })
    store["messages"] = msgs
    if len(store["messages"]) >= 30:
        await update_context(store)
    save_contact_messages(contact_id, store)
    if RAG_ENABLED:
        await upsert_messages(contact_id, [msgs[0]])

    return web.json_response({"ok": True})

def build_app():
    app = web.Application()
    app.add_routes(
        [
            web.get("/healthz", handle_health),
            web.get("/contacts/ativa", handle_list),
            web.post("/webhooks/contact-tag", handle_contact_tag),
            web.post("/webhooks/inbound-message", handle_inbound_message),
            web.post("/webhooks/outbound-message", handle_outbound_message),
        ]
    )
    return app

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = build_app()
    web.run_app(app, port=PORT)

if __name__ == "__main__":
    main()
