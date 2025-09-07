import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

from config import STORE_PATH, MESSAGES_DIR, LOCATION_TOKEN_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_store() -> Dict[str, Any]:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Falha lendo o store; recriando.")
    return {"lastUpdate": _now_iso(), "contactIds": []}


def save_store(store: Dict[str, Any]) -> None:
    store["lastUpdate"] = _now_iso()
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_contact_messages(contact_id: str) -> Dict[str, Any]:
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = MESSAGES_DIR / f"{contact_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("messages", [])
            data.setdefault("context", "")
            return data
        except Exception:
            logging.exception("Falha lendo o histórico de %s; recriando.", contact_id)
    return {"lastUpdate": _now_iso(), "messages": [], "context": ""}


def save_contact_messages(contact_id: str, store: Dict[str, Any]) -> None:
    store["lastUpdate"] = _now_iso()
    store.setdefault("context", "")
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = MESSAGES_DIR / f"{contact_id}.json"
    path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_location_token() -> Optional[str]:
    try:
        data = json.loads(LOCATION_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        logging.exception("Falha lendo location_token.json")
        return None


def load_location_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Retorna o access token e o location id."""
    try:
        data = json.loads(LOCATION_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token"), data.get("location_id")
    except Exception:
        logging.exception("Falha lendo location_token.json")
        return None, None

