"""Obtém as localizações onde o aplicativo está instalado.

Esta ferramenta consulta a API do GoHighLevel para descobrir em quais
subcontas ("locations") o aplicativo está instalado. Usa o endpoint
com query params (`isInstalled`, `companyId`, `appId`) conforme exigido
pelos endpoints da API. O resultado é salvo em
`data/installed_locations_data.json`, utilizado pelos demais scripts.

Configuração:
  * Defina `GHL_APP_ID` com o ID do seu aplicativo.
  * Defina `GHL_COMPANY_ID` (ou `AGENCY_COMPANY_ID`) com o ID da sua
    agência. Se não informar, extrai do token.

Uso:
    python -m ia_zoi.scripts.fetch_locations
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .. import config
from ..scripts.refresh_tokens import refresh_agency_token

# Diretórios e arquivos de configuração
DATA_DIR: Path = config.DATA_DIR
TOKEN_FILE: Path = config.GHL_TOKEN_FILE
OUTPUT_FILE: Path = config.INSTALLED_LOCATIONS_FILE

# API
API_BASE_URL = "https://services.leadconnectorhq.com"
API_ENDPOINT = f"{API_BASE_URL}/oauth/installedLocations"
API_VERSION = "2021-07-28"


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


def fetch_all_installations(
    access_token: str, company_id: str, app_id: str
) -> Optional[List[Dict[str, Any]]]:
    """
    Chama o endpoint com query params e retorna a lista de instalações.
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
        data = resp.json()
        if isinstance(data, dict) and "locations" in data:
            return data["locations"]
        if isinstance(data, list):
            return data
        return [data]
    except requests.RequestException as exc:
        print(f"[fetch_locations] Erro ao chamar endpoint com params: {exc}")
        return None


def main() -> None:
    print("--- Script fetch_locations ---")

    # 1. Garante token de agência válido
    if not refresh_agency_token():
        print("[fetch_locations] Falha ao atualizar token de agência; abortando.")
        return

    # 2. Carrega token do arquivo
    token_data = _load_json(TOKEN_FILE) or {}
    access_token = token_data.get("access_token")
    if not access_token:
        print(f"[fetch_locations] access_token não encontrado em {TOKEN_FILE}.")
        return

    # 3. Obtém appId e companyId
    app_id = os.getenv("GHL_APP_ID") or os.getenv("APP_ID")
    if not app_id:
        print("[fetch_locations] GHL_APP_ID não definido.")
        return
    company_id = os.getenv("GHL_COMPANY_ID") or token_data.get("companyId")
    if not company_id:
        print("[fetch_locations] GHL_COMPANY_ID ou companyId não definido.")
        return

    # 4. Busca todas as instalações
    print("🔍 Buscando todas instalações (com query params)...")
    installations = fetch_all_installations(access_token, company_id, app_id)
    if installations is None:
        return

    print(f"[fetch_locations] {len(installations)} localização(ões) retornadas pelo endpoint.")

    # 5. Salva se houver mudanças
    if _load_json(OUTPUT_FILE) != installations:
        if _save_json(installations, OUTPUT_FILE):
            print(f"[fetch_locations] Dados salvos em {OUTPUT_FILE}.")
        else:
            print(f"[fetch_locations] Falha ao salvar dados em {OUTPUT_FILE}.")
    else:
        print("[fetch_locations] Nenhuma mudança nos dados; arquivo já atualizado.")


if __name__ == "__main__":
    main()
