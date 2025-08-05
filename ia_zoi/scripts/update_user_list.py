"""Atualiza a lista de opções do campo personalizado de atribuição.

Esta é uma versão simplificada do script ``update_user_list.py``
original.  Seu propósito é criar ou atualizar um campo personalizado
do tipo *single select* no GoHighLevel para permitir a atribuição de
contatos a um usuário.  A lista de opções é derivada dos nomes dos
usuários salvos em ``data/users.json``.

Se o campo já existir, suas opções são atualizadas.  Caso não exista,
é criado um novo campo.  As informações sobre o campo gerenciado (ID,
chave, nome e data da última atualização) são salvas em
``data/campo_gerenciado_detalhes.json`` para uso posterior.

Este script assume que há pelo menos uma localização configurada em
``data/installed_locations_data.json`` e que as credenciais de acesso
estão presentes em ``data/gohighlevel_token.json``.  Para personalizar
o nome do campo ou suas propriedades, ajuste o dicionário
``FIELD_PROPERTIES`` abaixo.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .. import config

# Diretórios e arquivos
# Utilize os caminhos definidos em ``config`` para garantir
# consistência com outros scripts.  Esses caminhos apontam
# para o diretório ``ia_zoi/data`` na raiz do projeto.
DATA_DIR: Path = config.DATA_DIR
LOCATIONS_FILE: Path = config.INSTALLED_LOCATIONS_FILE
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
USERS_FILE: Path = config.USERS_FILE
MANAGED_FIELD_FILE: Path = config.MANAGED_FIELD_DETAILS_FILE

# Configuração da API
API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"

# Propriedades do campo a ser gerenciado
FIELD_PROPERTIES: Dict[str, Any] = {
    "name": "Transferir para:",
    "dataType": "SINGLE_OPTIONS",
    "model": "contact",
    "fieldKey": "transferir_para_o_vendedor",
    "placeholder": "Selecione o vendedor para transferir",
    "position": 400,
}


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


def _get_first_location_id() -> Optional[str]:
    locations_data = _load_json(LOCATIONS_FILE)
    if locations_data and isinstance(locations_data, list) and locations_data:
        loc = locations_data[0]
        return loc.get("_id") or loc.get("id")
    return None


def _generate_options_from_users() -> List[Dict[str, str]]:
    users_data = _load_json(USERS_FILE, default={"users": []})
    user_names: List[str] = []
    if isinstance(users_data, dict) and isinstance(users_data.get("users"), list):
        for user in users_data["users"]:
            if not isinstance(user, dict):
                continue
            name = user.get("name", "").strip()
            if not name and (user.get("firstName") or user.get("lastName")):
                name = f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
            if name:
                user_names.append(name)
    # Remover duplicados e ordenar
    unique_names = sorted(dict.fromkeys(user_names))
    # Adicionar opção "Selecionar" ao final
    if "Selecionar" in unique_names:
        unique_names.remove("Selecionar")
    unique_names.append("Selecionar")
    # Converter para a estrutura esperada pela API: lista de objetos {"label":..., "value":...}
    return [{"label": name, "value": name} for name in unique_names]


def _fetch_custom_field(location_id: str, base_field_key: str, model_type: str, token: str) -> Optional[Dict[str, Any]]:
    """Procura um campo personalizado pelo fieldKey base (sem prefixo do modelo)."""
    expected_key = f"{model_type}.{base_field_key}"
    url = f"{API_BASE_URL}/locations/{location_id}/customFields"
    headers = {"Authorization": f"Bearer {token}", "Version": API_VERSION, "Accept": "application/json"}
    params = {"model": model_type}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        fields = data.get("customFields", [])
        if not fields and isinstance(data, list):
            fields = data
        for field in fields:
            if isinstance(field, dict) and field.get("fieldKey") == expected_key:
                return field
        return None
    except requests.exceptions.RequestException:
        return None


def _create_custom_field(location_id: str, options: List[Dict[str, str]], token: str) -> Optional[Dict[str, Any]]:
    url = f"{API_BASE_URL}/locations/{location_id}/customFields"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "name": FIELD_PROPERTIES["name"],
        "dataType": FIELD_PROPERTIES["dataType"],
        "model": FIELD_PROPERTIES["model"],
        "fieldKey": FIELD_PROPERTIES["fieldKey"],
        "placeholder": FIELD_PROPERTIES["placeholder"],
        "options": options,
        "position": FIELD_PROPERTIES["position"],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # A resposta pode conter "customField" ou o campo diretamente
        return data.get("customField", data)
    except requests.exceptions.RequestException:
        return None


def _update_custom_field(location_id: str, field_id: str, options: List[Dict[str, str]], token: str) -> bool:
    url = f"{API_BASE_URL}/locations/{location_id}/customFields/{field_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "options": options,
    }
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


def main() -> None:
    print("--- Script update_user_list ---")
    location_id = _get_first_location_id()
    if not location_id:
        print(f"[update_user_list] Nenhuma localização encontrada em {LOCATIONS_FILE}.")
        return
    token = _get_access_token_for_location(location_id)
    if not token:
        print("[update_user_list] Token não encontrado para a localização.")
        return
    options = _generate_options_from_users()
    # Procurar se o campo já existe
    existing_field = _fetch_custom_field(location_id, FIELD_PROPERTIES["fieldKey"], FIELD_PROPERTIES["model"], token)
    if existing_field and isinstance(existing_field, dict) and existing_field.get("id"):
        field_id = existing_field["id"]
        if _update_custom_field(location_id, field_id, options, token):
            print(f"[update_user_list] Campo existente atualizado (ID: {field_id}).")
            # Salvar detalhes do campo
            field_details = {
                "locationId": location_id,
                "model": FIELD_PROPERTIES["model"],
                "fieldKey_base_sent": FIELD_PROPERTIES["fieldKey"],
                "fieldKey_api_returned": existing_field.get("fieldKey"),
                "currentId": field_id,
                "name": FIELD_PROPERTIES["name"],
                "last_updated_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _save_json({"managed_custom_field": field_details}, MANAGED_FIELD_FILE)
        else:
            print(f"[update_user_list] Falha ao atualizar o campo (ID: {field_id}).")
    else:
        # Criar novo campo
        new_field = _create_custom_field(location_id, options, token)
        if new_field and isinstance(new_field, dict) and new_field.get("id"):
            field_id = new_field["id"]
            print(f"[update_user_list] Novo campo criado (ID: {field_id}).")
            field_details = {
                "locationId": location_id,
                "model": FIELD_PROPERTIES["model"],
                "fieldKey_base_sent": FIELD_PROPERTIES["fieldKey"],
                "fieldKey_api_returned": new_field.get("fieldKey"),
                "currentId": field_id,
                "name": FIELD_PROPERTIES["name"],
                "last_updated_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _save_json({"managed_custom_field": field_details}, MANAGED_FIELD_FILE)
        else:
            print("[update_user_list] Falha ao criar novo campo.")


if __name__ == "__main__":
    main()