"""Atribui um contato a um usuário específico no GoHighLevel.

Este script é invocado pelo roteador quando um contato deve ser
transferido para um usuário selecionado.  Ele lê o token adequado
para a localização a partir de ``data/installed_locations_data.json``
ou, se ausente, usa o token de agência em ``data/gohighlevel_token.json``.
Em seguida, faz uma requisição ``PUT`` à API para atualizar o campo
``assignedTo`` do contato com o ID do usuário.

Uso:

.. code-block:: bash

    python -m ia_zoi.scripts.process_contact_assignment <contact_id> <location_id> <user_id>

Retorna status de sucesso ou exibe mensagens de erro no console.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .. import config

# Localização dos arquivos de dados
# Use os caminhos de ``config`` para garantir que lemos os mesmos
# arquivos utilizados pelos demais componentes.  O diretório de dados
# é ``ia_zoi/data``.
DATA_DIR: Path = config.DATA_DIR
LOCATIONS_FILE: Path = config.INSTALLED_LOCATIONS_FILE
TOKEN_FILE: Path = config.GHL_TOKEN_FILE

API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"


def _load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_access_token_for_location(location_id: str) -> Optional[str]:
    locations_data = _load_json(LOCATIONS_FILE)
    token: Optional[str] = None
    if locations_data and isinstance(locations_data, list):
        for loc in locations_data:
            if isinstance(loc, dict) and (loc.get("_id") == location_id or loc.get("id") == location_id):
                token_data = loc.get("location_specific_token_data")
                if token_data and token_data.get("access_token"):
                    token = token_data["access_token"]
                    break
    if not token:
        token_data = _load_json(TOKEN_FILE)
        if token_data and token_data.get("access_token"):
            token = token_data["access_token"]
    return token


def _update_contact_assignment(contact_id: str, user_id: str, token: str) -> bool:
    url = f"{API_BASE_URL}/contacts/{contact_id}"
    payload: Dict[str, Any] = {"assignedTo": user_id}
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[process_contact_assignment] Erro ao atualizar contato: {exc}")
        try:
            if hasattr(exc, "response") and exc.response is not None:
                print(f"[process_contact_assignment] Resposta da API: {exc.response.text}")
        except Exception:
            pass
        return False


def main() -> None:
    print("--- Script process_contact_assignment ---")
    if len(sys.argv) != 4:
        print("Uso: python -m ia_zoi.scripts.process_contact_assignment <contact_id> <location_id> <user_id>")
        return
    contact_id, location_id, user_id = sys.argv[1], sys.argv[2], sys.argv[3]
    print(f"Contato: {contact_id}\nLocation: {location_id}\nUser: {user_id}")
    token = _get_access_token_for_location(location_id)
    if not token:
        print("[process_contact_assignment] Token não encontrado para a localização.")
        return
    if _update_contact_assignment(contact_id, user_id, token):
        print("[process_contact_assignment] Contato atribuído com sucesso.")
    else:
        print("[process_contact_assignment] Falha ao atribuir contato.")


if __name__ == "__main__":
    main()