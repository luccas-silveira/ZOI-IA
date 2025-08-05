"""Obtém o token inicial (access e refresh) a partir de um código de autorização.

Para executar este script você precisa do `client_id`, `client_secret` e do
`authorization_code` fornecido pelo fluxo OAuth do GoHighLevel.  Estes
valores devem ser configurados como variáveis de ambiente (ou em
`.env`) com os nomes ``GHL_CLIENT_ID``, ``GHL_CLIENT_SECRET`` e
``GHL_AUTH_CODE``.  O tipo de usuário (``Company`` ou ``Location``)
deve ser definido em ``GHL_USER_TYPE`` (padrão: Company).

O script realiza uma requisição ``POST /oauth/token`` com
``grant_type=authorization_code`` e grava a resposta em
``data/gohighlevel_token.json`` para uso pelos demais scripts.

Uso:

.. code-block:: bash

    python -m ia_zoi.scripts.init_token

"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import requests

from .. import config

# Endpoint para troca do código de autorização
TOKEN_ENDPOINT: str = "https://services.leadconnectorhq.com/oauth/token"

def main() -> None:
    print("--- Script init_token ---")
    client_id: Optional[str] = config.GHL_CLIENT_ID
    client_secret: Optional[str] = config.GHL_CLIENT_SECRET
    auth_code: Optional[str] = config.GHL_AUTH_CODE
    user_type: str = config.GHL_USER_TYPE or "Company"
    if not client_id or not client_secret or not auth_code:
        print(
            "[init_token] Variáveis GHL_CLIENT_ID, GHL_CLIENT_SECRET ou GHL_AUTH_CODE não configuradas."
            " Defina-as no .env ou no ambiente."
        )
        return
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "user_type": user_type,
    }
    # Opcional: se a aplicação utilizar redirect_uri para obter o código, inclua-o aqui
    redirect_uri: Optional[str] = getattr(config, "GHL_REDIRECT_URI", None) or None
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(TOKEN_ENDPOINT, data=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()
        # Salvar em arquivo
        token_file: Path = config.GHL_TOKEN_FILE
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with token_file.open("w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=4, ensure_ascii=False)
        print(f"[init_token] Token inicial salvo em {token_file}.")
    except requests.exceptions.RequestException as exc:
        print(f"[init_token] Falha ao obter token inicial: {exc}")
        if hasattr(exc, "response") and exc.response is not None:
            try:
                print(f"Resposta da API: {exc.response.text}")
            except Exception:
                pass

if __name__ == "__main__":
    main()