"""Obtém a lista de usuários do GoHighLevel e persiste localmente.

Este script lê a lista de localizações instaladas em
``data/installed_locations_data.json``, seleciona a primeira
localização e consulta a API do GoHighLevel para recuperar os usuários
associados a essa localização.  O resultado é mesclado com o arquivo
local ``data/users.json`` preservando o campo ``empresa_info`` (se
existir), e então salvo de volta no mesmo arquivo.

O objetivo principal é disponibilizar uma cópia local dos usuários
para que outros componentes possam mapear nomes para IDs.  Execute
este script via:

.. code-block:: bash

    python -m ia_zoi.scripts.get_users

"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .. import config

# Centralizar caminhos de dados usando o módulo de configuração.  Isso
# garante que todos os scripts utilizem o mesmo diretório "data"
DATA_DIR: Path = config.DATA_DIR
LOCATIONS_FILE: Path = config.INSTALLED_LOCATIONS_FILE
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
USERS_FILE: Path = config.USERS_FILE

API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(data: Any, path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def _get_access_token_for_location(location_id: str) -> Optional[str]:
    """Retorna o token adequado para a localização ou fallback para o token da agência."""
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
        # fallback para token da agência
        token_data = _load_json(TOKEN_FILE)
        if token_data and token_data.get("access_token"):
            token = token_data["access_token"]
    return token


def _fetch_users_from_api(location_id: str, access_token: str) -> Optional[List[Dict[str, Any]]]:
    endpoint_url = f"{API_BASE_URL}/users/"
    params = {"locationId": location_id}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(endpoint_url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("users", [])
    except requests.exceptions.RequestException as exc:
        print(f"[get_users] Erro ao buscar usuários: {exc}")
        return None


def main() -> None:
    print("--- Script get_users ---")
    locations_data = _load_json(LOCATIONS_FILE)
    if not locations_data or not isinstance(locations_data, list) or not locations_data:
        print(f"[get_users] Nenhuma localização encontrada em {LOCATIONS_FILE}.")
        return
    first_loc = locations_data[0]
    location_id = first_loc.get("_id") or first_loc.get("id")
    if not location_id:
        print("[get_users] ID da primeira localização não encontrado.")
        return
    token = _get_access_token_for_location(location_id)
    if not token:
        print("[get_users] Token não encontrado para a localização.")
        return
    fresh_users = _fetch_users_from_api(location_id, token)
    if fresh_users is None:
        print("[get_users] Falha ao obter usuários da API.")
        return
    # Carregar dados existentes para preservar empresa_info
    existing = _load_json(USERS_FILE, default={"users": []})
    existing_users = existing.get("users", []) if isinstance(existing, dict) else []
    empresa_map: Dict[str, Any] = {}
    for user in existing_users:
        if isinstance(user, dict) and "id" in user and "empresa_info" in user:
            empresa_map[user["id"]] = user["empresa_info"]
    final_users: List[Dict[str, Any]] = []
    for user in fresh_users:
        if not isinstance(user, dict):
            continue
        uid = user.get("id")
        empresa_info = user.get("empresa_info", {})
        if uid and uid in empresa_map:
            empresa_info = empresa_map[uid]
        if not isinstance(empresa_info, dict):
            empresa_info = {}
        empresa_info.setdefault("role", "Membro")
        empresa_info.setdefault("assigned_team_id", None)
        user["empresa_info"] = empresa_info
        final_users.append(user)
    if _save_json({"users": final_users}, USERS_FILE):
        print(f"[get_users] {len(final_users)} usuários salvos em {USERS_FILE}.")
    else:
        print(f"[get_users] Falha ao salvar {USERS_FILE}.")


if __name__ == "__main__":
    main()