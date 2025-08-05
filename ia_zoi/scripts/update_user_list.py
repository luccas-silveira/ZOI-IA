"""Obtém a lista de usuários (membros) da agência no GoHighLevel.

Este script consulta a API `/users` para recuperar todos os usuários
associados à `locationId` configurada e salva em `data/users.json`
para uso pelos demais scripts.

Configuração:
  * Defina `GHL_LOCATION_ID` no seu `.env` para indicar a localização.
  * Certifique-se de ter um `access_token` de agência válido em
    `data/gohighlevel_token.json` (via fluxo OAuth ou `refresh_tokens`).

Uso:
    python -m ia_zoi.scripts.get_users
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .. import config
from ..scripts.refresh_tokens import refresh_agency_token

# Caminhos dos arquivos
DATA_DIR: Path = config.DATA_DIR
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
OUTPUT_FILE: Path = config.USERS_FILE  # normalmente <DATA_DIR>/users.json

# API
API_BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
USERS_ENDPOINT = f"{API_BASE_URL}/users"


def _load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(data: Any, path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def fetch_users(access_token: str, location_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    Chama o endpoint /users?locationId=<location_id> e retorna a lista.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    params = {"locationId": location_id}
    try:
        resp = requests.get(USERS_ENDPOINT, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "users" in data:
            return data["users"]
        if isinstance(data, list):
            return data
        return [data]
    except requests.RequestException as exc:
        print(f"[get_users] Erro ao buscar usuários: {exc}")
        return None


def main() -> None:
    print("--- Script get_users ---")

    # 1) Atualiza token de agência
    if not refresh_agency_token():
        print("[get_users] Falha ao atualizar token de agência; abortando.")
        return

    # 2) Carrega token de arquivo
    token_data = _load_json(TOKEN_FILE) or {}
    access_token = token_data.get("access_token")
    if not access_token:
        print(f"[get_users] access_token não encontrado em {TOKEN_FILE}.")
        return

    # 3) Obtém locationId do .env
    location_id = os.getenv("GHL_LOCATION_ID")
    if not location_id:
        print("[get_users] GHL_LOCATION_ID não definido.")
        return

    # 4) Faz a requisição
    print(f"🔍 Buscando usuários para locationId={location_id}...")
    users = fetch_users(access_token, location_id)
    if users is None:
        return

    print(f"[get_users] {len(users)} usuários salvos em {OUTPUT_FILE}.")

    # 5) Grava o resultado
    if _save_json(users, OUTPUT_FILE):
        print(f"[get_users] JSON de usuários salvo com sucesso.")
    else:
        print(f"[get_users] Falha ao salvar JSON de usuários em {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()
