"""Obtém as localizações onde o aplicativo está instalado.

Esta ferramenta consulta a API do GoHighLevel para descobrir em quais
subcontas ("locations") o aplicativo está instalado.  O resultado é
salvo em ``data/installed_locations_data.json``, que é utilizado pelos
demais scripts da aplicação.

Configuração:
  * Defina ``GHL_APP_ID`` com o ID do seu aplicativo.
  * Defina ``GHL_COMPANY_ID`` (ou ``AGENCY_COMPANY_ID``) com o ID da sua
    agência.  Se não informar explicitamente, o script tenta extrair
    ``companyId`` do arquivo ``gohighlevel_token.json``.

O token de acesso da agência deve estar presente em
``data/gohighlevel_token.json``.  Se o token estiver ausente ou
inválido, execute primeiro ``refresh_tokens.py``.

Uso:

.. code-block:: bash

    python -m ia_zoi.scripts.fetch_locations

"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .. import config

# Carregar variáveis do arquivo .env, se disponível.  Ao importar
# ``config``, o arquivo `.env` é carregado automaticamente por meio
# de ``config._load_env()``, desde que python-dotenv esteja
# instalado.  Se python-dotenv não estiver instalado, nenhuma
# variável adicional é carregada e o script dependerá das variáveis
# de ambiente existentes.

DATA_DIR: Path = config.DATA_DIR
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
OUTPUT_FILE: Path = config.INSTALLED_LOCATIONS_FILE

API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"
API_ENDPOINT: str = f"{API_BASE_URL}/oauth/installedLocations"


def _load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def fetch_locations(app_id: str, company_id: str, access_token: str) -> Optional[Any]:
    """Executa a chamada GET para /oauth/installedLocations e retorna o resultado.

    Args:
        app_id: ID do aplicativo no marketplace.
        company_id: ID da agência.
        access_token: token de acesso da agência.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    params = {
        "isInstalled": "true",
        "companyId": company_id,
        "appId": app_id,
    }
    try:
        resp = requests.get(API_ENDPOINT, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        print(f"[fetch_locations] Erro ao buscar localizações: {exc}")
        return None


def main() -> None:
    print("--- Script fetch_locations ---")
    app_id = os.getenv("GHL_APP_ID") or os.getenv("APP_ID")
    company_id_env = os.getenv("GHL_COMPANY_ID") or os.getenv("AGENCY_COMPANY_ID")
    if not app_id:
        print("[fetch_locations] Variável GHL_APP_ID (ou APP_ID) não definida. Defina-a no .env ou no ambiente.")
        return
    token_data = _load_json(TOKEN_FILE)
    if not token_data or not token_data.get("access_token"):
        print(f"[fetch_locations] Arquivo {TOKEN_FILE} ausente ou sem access_token. Atualize o token primeiro.")
        return
    access_token = token_data["access_token"]
    # Determinar companyId: primeiro usar env, depois token file
    company_id = company_id_env or token_data.get("companyId")
    if not company_id:
        print(
            "[fetch_locations] Company ID não encontrado. Defina GHL_COMPANY_ID no ambiente ou garanta que o token contenha companyId."
        )
        return
    result = fetch_locations(app_id, company_id, access_token)
    if result is None:
        return
    # Extrair lista de localizações
    if isinstance(result, dict) and "locations" in result:
        locations = result["locations"]
    elif isinstance(result, list):
        locations = result
    else:
        locations = [result]
    if _load_json(OUTPUT_FILE) != locations:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_FILE.open("w", encoding="utf-8") as f_out:
            json.dump(locations, f_out, indent=4, ensure_ascii=False)
        print(f"[fetch_locations] {len(locations)} localização(ões) salvas em {OUTPUT_FILE}.")
    else:
        print("[fetch_locations] Dados de localizações já atualizados; nenhuma alteração feita.")


if __name__ == "__main__":
    main()