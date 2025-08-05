"""Atualiza os tokens da agência e de cada localização no GoHighLevel.

Este script combina a lógica do ``update_all_tokens.py`` original em
um módulo único adaptado para a nova estrutura do projeto.  Ele lê o
token de agência (que contém ``refresh_token`` e ``companyId``) a
partir do arquivo JSON localizado em ``data/gohighlevel_token.json``,
solicita um novo ``access_token`` à API do GoHighLevel e grava os
dados atualizados no mesmo arquivo.  Em seguida, utiliza o token de
agência e o ``companyId`` para buscar tokens específicos para cada
localização listada em ``data/installed_locations_data.json``,
anexando o objeto retornado em ``location_specific_token_data``.

Credenciais sensíveis (``client_id`` e ``client_secret``) não são
embutidas no código.  Configure ``GHL_CLIENT_ID`` e ``GHL_CLIENT_SECRET``
em seu ambiente ou arquivo ``.env`` conforme definido em
``ia_zoi.config``.  Sem esses valores, o script emitirá um aviso e
abortará.

O script pode ser executado diretamente via:

.. code-block:: bash

    python -m ia_zoi.scripts.refresh_tokens

Ele é também invocado periodicamente pelo servidor Flask através do
agendador APScheduler definido em ``ia_zoi.web.server``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .. import config

# ``os`` é necessário para ler variáveis de ambiente de fallback.  Em
# versões anteriores deste arquivo, esse import estava ausente,
# provocando ``NameError`` quando ``os.getenv`` era utilizado em
# ``refresh_agency_token``.  Manter o import explícito evita esse
# problema e permite que ``os.getenv`` funcione corretamente.
import os

# Diretório de dados e arquivos de configuração
DATA_DIR: Path = config.DATA_DIR
GHL_TOKEN_FILE: Path = config.GHL_TOKEN_FILE
LOCATIONS_FILE: Path = config.INSTALLED_LOCATIONS_FILE

# Base da API e endpoints do GoHighLevel
API_BASE_URL: str = "https://services.leadconnectorhq.com"
TOKEN_ENDPOINT_PATH: str = "/oauth/token"
LOCATION_TOKEN_ENDPOINT_PATH: str = "/oauth/locationToken"
API_VERSION: str = "2021-07-28"

# Recuperar credenciais do ambiente via config.  Estas variáveis são
# carregadas de ``.env`` por ``config._load_env`` quando o módulo
# ``config`` é importado.  Caso não estejam configuradas, abortamos o
# refresh.
REFRESH_CLIENT_ID: Optional[str] = config.GHL_CLIENT_ID
REFRESH_CLIENT_SECRET: Optional[str] = config.GHL_CLIENT_SECRET


def _load_json(path: Path) -> Optional[Any]:
    """Carrega um arquivo JSON retornando ``None`` em caso de falha."""
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(data: Any, path: Path) -> bool:
    """Salva um objeto como JSON com codificação UTF-8."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def refresh_agency_token() -> bool:
    """Atualiza o token de agência usando o ``refresh_token`` salvo.

    Retorna ``True`` em caso de sucesso ou ``False`` caso ocorra algum
    erro.  O token atualizado é gravado de volta em ``GHL_TOKEN_FILE``.
    """
    if not REFRESH_CLIENT_ID or not REFRESH_CLIENT_SECRET:
        print("[refresh_tokens] GHL_CLIENT_ID/GHL_CLIENT_SECRET não configurados; abortando.")
        return False
    token_data = _load_json(GHL_TOKEN_FILE)
    if not token_data or "refresh_token" not in token_data:
        print(f"[refresh_tokens] refresh_token não encontrado em {GHL_TOKEN_FILE}.")
        return False
    # Determinar o tipo de usuário (Company ou Location).  Damos
    # prioridade ao valor presente no JSON de token (userType), em
    # seguida à configuração carregada pelo módulo config e, por
    # último, ao valor no ambiente.  Isso garante coerência entre
    # chamadas de refresh e o valor utilizado no fluxo inicial.
    user_type = token_data.get("userType") or config.GHL_USER_TYPE or os.getenv("GHL_USER_TYPE", "Company")
    refresh_payload = {
        "grant_type": "refresh_token",
        "client_id": REFRESH_CLIENT_ID,
        "client_secret": REFRESH_CLIENT_SECRET,
        "refresh_token": token_data["refresh_token"],
        "user_type": user_type,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    url = f"{API_BASE_URL}{TOKEN_ENDPOINT_PATH}"
    try:
        resp = requests.post(url, data=refresh_payload, headers=headers, timeout=30)
        resp.raise_for_status()
        new_token_data = resp.json()
        # Preserve campos que podem não vir na resposta
        for key in ("userType", "companyId"):
            if key not in new_token_data and key in token_data:
                new_token_data[key] = token_data[key]
        # Anotar timestamp de refresh
        timestamp = int(time.time())
        new_token_data["refreshed_at_unix_timestamp"] = timestamp
        new_token_data["refreshed_at_readable"] = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(timestamp))
        _save_json(new_token_data, GHL_TOKEN_FILE)
        print("[refresh_tokens] Token de agência atualizado com sucesso.")
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[refresh_tokens] Falha no refresh do token de agência: {exc}")
        return False


def _fetch_location_token(location_id: str, company_id: str, access_token: str) -> Optional[Dict[str, Any]]:
    """Busca um token específico para a localização.

    Retorna o JSON retornado pela API ou ``None`` se houver erro.
    """
    payload = {"companyId": company_id, "locationId": location_id}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Version": API_VERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(f"{API_BASE_URL}{LOCATION_TOKEN_ENDPOINT_PATH}", data=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        print(f"[refresh_tokens] Falha ao obter token da localização {location_id}: {exc}")
        return None


def manage_location_tokens() -> bool:
    """Atualiza tokens específicos de cada localização listada.

    Lê ``installed_locations_data.json`` (lista de objetos contendo ``_id``) e
    faz uma chamada para cada localização.  O resultado é gravado no
    mesmo arquivo, dentro de ``location_specific_token_data``.
    """
    token_data = _load_json(GHL_TOKEN_FILE)
    if not token_data:
        print(f"[refresh_tokens] Não foi possível carregar {GHL_TOKEN_FILE} para tokens de localização.")
        return False
    access_token = token_data.get("access_token")
    company_id = token_data.get("companyId")
    if not access_token or not company_id:
        print("[refresh_tokens] access_token ou companyId ausente para tokens de localização.")
        return False
    locations = _load_json(LOCATIONS_FILE)
    if locations is None:
        print(f"[refresh_tokens] Arquivo de localizações {LOCATIONS_FILE} não encontrado ou inválido.")
        return False
    # Se estiver encapsulado em {"locations": [...]}, normalizar
    if isinstance(locations, dict) and "locations" in locations:
        locations = locations["locations"]
    if not isinstance(locations, list):
        print(f"[refresh_tokens] Conteúdo de {LOCATIONS_FILE} não é uma lista.")
        return False
    updated_locations: List[Dict[str, Any]] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        loc_id = loc.get("_id") or loc.get("id")
        if not loc_id:
            updated_locations.append(loc)
            continue
        token_json = _fetch_location_token(loc_id, company_id, access_token)
        if token_json:
            loc["location_specific_token_data"] = token_json
        updated_locations.append(loc)
    # Salvar lista atualizada diretamente
    if _save_json(updated_locations, LOCATIONS_FILE):
        print("[refresh_tokens] Tokens de localização atualizados com sucesso.")
        return True
    print("[refresh_tokens] Falha ao salvar tokens de localização atualizados.")
    return False


def main() -> None:
    print("--- Script refresh_tokens ---")
    start = time.time()
    if refresh_agency_token():
        manage_location_tokens()
    else:
        print("[refresh_tokens] Falha ao atualizar o token de agência; tokens de localização não serão atualizados.")
    end = time.time()
    print(f"[refresh_tokens] Execução finalizada em {end - start:.2f} segundos.")


if __name__ == "__main__":
    main()