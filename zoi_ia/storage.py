import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

from pathlib import Path
from .config import STORE_PATH, MESSAGES_DIR, LOCATION_TOKEN_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def load_store() -> Dict[str, Any]:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Falha lendo o store; recriando.")
    return {"lastUpdate": _now_iso(), "contactIds": []}


def save_store(store: Dict[str, Any]) -> None:
    store["lastUpdate"] = _now_iso()
    payload = json.dumps(store, ensure_ascii=False, indent=2)
    _atomic_write(STORE_PATH, payload)


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
    path = MESSAGES_DIR / f"{contact_id}.json"
    payload = json.dumps(store, ensure_ascii=False, indent=2)
    _atomic_write(path, payload)


def load_location_token() -> Optional[str]:
    try:
        data = json.loads(LOCATION_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        logging.exception("Falha lendo location_token.json")
        return None


def load_location_credentials() -> Tuple[Optional[str], Optional[str]]:
    try:
        data = json.loads(LOCATION_TOKEN_PATH.read_text(encoding="utf-8"))
        return data.get("access_token"), data.get("location_id")
    except Exception:
        logging.exception("Falha lendo location_token.json")
        return None, None

