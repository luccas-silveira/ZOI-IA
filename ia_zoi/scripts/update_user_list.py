"""Atualiza ou cria um campo personalizado de atribuição no GoHighLevel.

Este script mantém a lista de opções de um campo personalizado do tipo
*single select* sincronizada com a relação de usuários da subconta.
Ele deve ser executado sempre que novos usuários forem criados ou
periodicamente por um agendador.  O nome do campo e a chave base são
configurados via dicionário ``FIELD_PROPERTIES``.  Por padrão o
campo é criado no modelo ``contact``, mas você pode alterar o
alvo definindo a variável de ambiente ``ASSIGNMENT_FIELD_MODEL`` ou
``CUSTOM_FIELD_MODEL`` (por exemplo, ``opportunity``) antes de rodar
o script.

Ao executar, o script:

1. Carrega a lista de usuários de ``data/users.json`` e gera uma
   lista de opções (rótulos e valores).
2. Recupera o ID da primeira localização instalada em
   ``data/installed_locations_data.json``.
3. Lê o token de acesso da subconta ou, se ausente, da agência em
   ``data/gohighlevel_token.json``.
4. Procura o campo já existente pelo ``fieldKey`` e ``model``; se
   encontrado, atualiza suas opções. Caso contrário, cria um novo.
5. Persiste detalhes do campo (ID, modelo, nome, chave) em
   ``data/campo_gerenciado_detalhes.json`` para consumo pelos
   webhooks.

Uso típico:

    python -m ia_zoi.scripts.get_users
    python -m ia_zoi.scripts.update_user_list

Alternativamente, configure um agendador (por exemplo, APScheduler) para
executar esses scripts a cada N horas.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ia_zoi import config

# Diretórios e arquivos
DATA_DIR: Path = config.DATA_DIR
LOCATIONS_FILE: Path = config.INSTALLED_LOCATIONS_FILE
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
USERS_FILE: Path = config.USERS_FILE
MANAGED_FIELD_FILE: Path = config.MANAGED_FIELD_DETAILS_FILE

# Configuração da API
API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"

# Propriedades padrão do campo de atribuição.
# Você pode alterar ``name``, ``fieldKey`` ou outros valores conforme
# necessário.  O ``model`` será sobrescrito dinamicamente se você
# definir ``ASSIGNMENT_FIELD_MODEL`` ou ``CUSTOM_FIELD_MODEL``.
FIELD_PROPERTIES: Dict[str, Any] = {
    "name": "Transferir para:",
    "dataType": "SINGLE_OPTIONS",
    "model": "contact",
    "fieldKey": "transferir_para_o_vendedor",
    "placeholder": "Selecione o vendedor para transferir",
    # A posição é opcional e deve ser string se fornecida. Comentada para evitar erros de trim.
    # "position": "400",
}

# Sobrescrever o modelo do campo se variável de ambiente estiver definida
_env_model = os.getenv("ASSIGNMENT_FIELD_MODEL") or os.getenv("CUSTOM_FIELD_MODEL")
if _env_model:
    # Normalizar para minúsculas e remover espaços
    _env_model = _env_model.strip().lower()
    # A API espera "contact" ou "opportunity".  Mantemos valor
    # fornecido para dar flexibilidade, mas alertamos se for outro.
    FIELD_PROPERTIES["model"] = _env_model


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
    """Obtém o token de acesso específico da localização ou, se ausente, o token de agência."""
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


def _get_first_location_id() -> Optional[str]:
    """Retorna o ID da primeira localização instalada, se houver."""
    locations_data = _load_json(LOCATIONS_FILE)
    if locations_data and isinstance(locations_data, list) and locations_data:
        loc = locations_data[0]
        return loc.get("_id") or loc.get("id")
    return None


def _generate_options_from_users() -> List[Dict[str, str]]:
    """
    Gera a lista de opções a partir do arquivo de usuários.

    A API do GoHighLevel espera que cada opção possua as chaves
    ``key`` e ``label`` (ambas strings). A omissão de ``key`` causa
    um erro ``v.trim is not a function`` no endpoint, pois o backend
    tenta aplicar ``trim()`` em um valor inexistente. Por isso,
    retornamos um dicionário com ``key`` e ``label`` iguais ao nome.
    
    Também adicionamos uma opção "Selecionar" ao final para permitir
    que nenhum vendedor seja escolhido explicitamente.
    """
    users_data = _load_json(USERS_FILE, default={"users": []})
    user_names: List[str] = []
    if isinstance(users_data, dict) and isinstance(users_data.get("users"), list):
        for user in users_data["users"]:
            if not isinstance(user, dict):
                continue
            # Tentar extrair o nome completo; alguns eventos retornam "name"
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
    # A API aceita "key", "label" e (muitas vezes) "value".
    # Para máxima compatibilidade, fornecemos todas as três.  O ``key``
    # é uma versão normalizada do nome (minúsculas e espaços substituídos
    # por hífens) e será usado internamente pela API.  O ``label`` é
    # exibido ao usuário no dropdown, e ``value`` é igual ao nome para
    # ser retornado no webhook.
    options: List[Dict[str, str]] = []
    for name in unique_names:
        # Normalizar chave: minúsculo, remover espaços excedentes e
        # substituir espaços por hífens.  Mantemos caracteres acentuados.
        key_normalized = "-".join(name.strip().lower().split())
        options.append({"key": key_normalized, "label": name, "value": name})
    return options


def _fetch_custom_field(location_id: str, base_field_key: str, model_type: str, token: str) -> Optional[Dict[str, Any]]:
    """Procura um campo personalizado pelo fieldKey base e modelo."""
    expected_key = f"{model_type}.{base_field_key}"
    url = f"{API_BASE_URL}/locations/{location_id}/customFields"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    params = {"model": model_type}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        fields = data.get("customFields", [])
        if not fields and isinstance(data, list):
            fields = data
        for field in fields:
            if not isinstance(field, dict):
                continue
            # A API retorna o fieldKey completo (ex: "contact.transferir_para_o_vendedor")
            if field.get("fieldKey") == expected_key:
                return field
        return None
    except requests.exceptions.RequestException:
        return None


def _create_custom_field(location_id: str, options: List[Dict[str, str]], token: str) -> Optional[Dict[str, Any]]:
    """Cria um novo campo personalizado com as opções fornecidas."""
    # Endpoint para criação de campo. A API aceita o modelo via query string (model=contact/opportunity)
    url = f"{API_BASE_URL}/locations/{location_id}/customFields"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Monta o payload base; o modelo permanece apenas no query param para maior compatibilidade
    payload = {
        "name": FIELD_PROPERTIES["name"],
        "dataType": FIELD_PROPERTIES["dataType"],
        "fieldKey": FIELD_PROPERTIES["fieldKey"],
        "placeholder": FIELD_PROPERTIES["placeholder"],
        "options": options,
        # Note: position omitted because passing a numeric value triggers a v.trim error in the API
    }
    # Define os parâmetros de consulta; incluir o modelo (contact/opportunity)
    params = {"model": FIELD_PROPERTIES["model"]}
    try:
        resp = requests.post(url, headers=headers, params=params, json=payload, timeout=15)
        # Se a API retornar erro, registre código e corpo para depuração
        if not resp.ok:
            print(
                f"[update_user_list] Erro ao criar campo: status={resp.status_code}, resposta={resp.text}"
            )
            resp.raise_for_status()
        data = resp.json()
        # Alguns endpoints retornam diretamente a lista de campos e não a chave customField
        return data.get("customField", data)
    except requests.exceptions.RequestException as exc:
        print(f"[update_user_list] Exceção ao criar campo: {exc}")
        return None


def _update_custom_field(location_id: str, field_id: str, options: List[Dict[str, str]], token: str) -> bool:
    """Atualiza as opções de um campo personalizado existente."""
    # Endpoint para atualização de campo. A API também aceita o modelo via query string.
    url = f"{API_BASE_URL}/locations/{location_id}/customFields/{field_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"options": options}
    # Parâmetro de consulta para o modelo
    params = {"model": FIELD_PROPERTIES["model"]}
    try:
        resp = requests.put(url, headers=headers, params=params, json=payload, timeout=15)
        if not resp.ok:
            print(
                f"[update_user_list] Erro ao atualizar campo: status={resp.status_code}, resposta={resp.text}"
            )
            resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[update_user_list] Exceção ao atualizar campo: {exc}")
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
    existing_field = _fetch_custom_field(
        location_id,
        FIELD_PROPERTIES["fieldKey"],
        FIELD_PROPERTIES["model"],
        token,
    )
    if existing_field and isinstance(existing_field, dict) and existing_field.get("id"):
        field_id = existing_field["id"]
        if _update_custom_field(location_id, field_id, options, token):
            print(f"[update_user_list] Campo existente atualizado (ID: {field_id}).")
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