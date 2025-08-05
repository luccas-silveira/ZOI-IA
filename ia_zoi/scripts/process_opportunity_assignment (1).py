"""Atribui um contato ao usuário selecionado via campo em uma oportunidade.

Este script é executado quando um evento de atualização de oportunidade
indica que o campo de atribuição de usuário foi alterado.  A meta é
pegar o ID do contato associado à oportunidade e atualizar o
campo ``assignedTo`` desse contato, delegando a mesma lógica de
atribuição usada para contatos.

O script aceita três argumentos de linha de comando: ``opportunity_id``,
``location_id`` e ``user_id``.  Ele lê o token adequado para a
localização a partir de ``data/installed_locations_data.json`` ou, se
ausente, usa o token de agência em ``data/gohighlevel_token.json``.  Em
seguida, consulta a API de oportunidades para obter o ID do contato
associado e chama o endpoint de atualização de contatos.

Uso:

    python -m ia_zoi.scripts.process_opportunity_assignment <opportunity_id> <location_id> <user_id>

Nota: este script é experimental e assume que o endpoint
``/opportunities/{opportunityId}`` retorna um objeto contendo
``contactId`` ou ``contact_id``.  Se o seu ambiente usar outra rota ou
campo, ajuste a função ``_get_contact_id_from_opportunity``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ia_zoi import config

# Localização dos arquivos de dados
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
    """Retorna o token específico da localização ou o token de agência."""
    locations_data = _load_json(LOCATIONS_FILE)
    token: Optional[str] = None
    if locations_data and isinstance(locations_data, list):
        for loc in locations_data:
            if not isinstance(loc, dict):
                continue
            loc_id = loc.get("_id") or loc.get("id")
            if loc_id == location_id:
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
    """Chama a API para atualizar o campo ``assignedTo`` de um contato."""
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
        print(f"[process_opportunity_assignment] Erro ao atualizar contato: {exc}")
        try:
            # Mostrar corpo de resposta se estiver disponível
            if hasattr(exc, "response") and exc.response is not None:
                print(f"[process_opportunity_assignment] Resposta da API: {exc.response.text}")
        except Exception:
            pass
        return False


def _get_contact_id_from_opportunity(opportunity_id: str, token: str) -> Optional[str]:
    """Obtém o contactId associado à oportunidade usando a API."""
    url = f"{API_BASE_URL}/opportunities/{opportunity_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if not isinstance(data, dict):
            return None
        # Tentar várias chaves possíveis
        contact_id = data.get("contactId") or data.get("contact_id") or data.get("contact_id")
        return str(contact_id) if contact_id else None
    except requests.exceptions.RequestException as exc:
        print(f"[process_opportunity_assignment] Erro ao buscar oportunidade: {exc}")
        try:
            if hasattr(exc, "response") and exc.response is not None:
                print(f"[process_opportunity_assignment] Resposta da API: {exc.response.text}")
        except Exception:
            pass
        return None


def main() -> None:
    print("--- Script process_opportunity_assignment ---")
    if len(sys.argv) != 4:
        print(
            "Uso: python -m ia_zoi.scripts.process_opportunity_assignment <opportunity_id> <location_id> <user_id>"
        )
        return
    opportunity_id, location_id, user_id = sys.argv[1], sys.argv[2], sys.argv[3]
    print(f"Oportunidade: {opportunity_id}\nLocation: {location_id}\nUser: {user_id}")
    token = _get_access_token_for_location(location_id)
    if not token:
        print("[process_opportunity_assignment] Token não encontrado para a localização.")
        return
    contact_id = _get_contact_id_from_opportunity(opportunity_id, token)
    if not contact_id:
        print(
            f"[process_opportunity_assignment] Não foi possível determinar o contato associado à oportunidade {opportunity_id}."
        )
        return
    if _update_contact_assignment(contact_id, user_id, token):
        print("[process_opportunity_assignment] Contato atribuído com sucesso.")
    else:
        print("[process_opportunity_assignment] Falha ao atribuir contato.")


if __name__ == "__main__":
    main()