"""Configuração interativa do fluxo OAuth 2.0 para o IA‑ZOI.

Este script simplifica o processo de obtenção do ``access_token`` e do
``refresh_token`` para a API do GoHighLevel. Ele orienta o usuário a
fornecer as credenciais do aplicativo (Client ID e Client Secret), abre
o link de consentimento para instalar a aplicação no GoHighLevel,
recebe o código de autorização gerado e finalmente troca esse código
pelos tokens de acesso e atualização. As credenciais e tokens são
persistidos em ``.env`` e em ``data/gohighlevel_token.json``.

Execute este script a partir da raiz do projeto:

    python -m ia_zoi.scripts.oauth_setup

Requisitos:
    - python-dotenv (para carregar e salvar variáveis do .env)
    - webbrowser (biblioteca padrão) para abrir a URL de autorização
    - requests
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

try:
    import webbrowser  # noqa: WPS433
except ImportError:
    webbrowser = None  # type: ignore

try:
    from dotenv import load_dotenv, set_key
except Exception:
    load_dotenv = None  # type: ignore
    set_key = None  # type: ignore

from .. import config


def _load_env_file(env_path: Path) -> None:
    """Carrega o arquivo .env se a biblioteca python-dotenv estiver disponível."""
    if load_dotenv is None:
        return
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Atualiza ou adiciona uma variável no arquivo .env."""
    if set_key is None:
        return
    try:
        set_key(str(env_path), key, value)
    except Exception:
        # Se falhar, simplesmente ignore; o usuário ainda pode editar manualmente
        pass


def prompt_input(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    """Solicita entrada do usuário com valor padrão opcional."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    try:
        # Para valores secretos (Client Secret), não ecoar
        if secret:
            import getpass  # noqa: WPS433
            value = getpass.getpass(prompt)
        else:
            value = input(prompt)
    except EOFError:
        # Caso stdin esteja fechado (como ao chamar via script), retornar valor padrão
        value = default or ""
    return value.strip() or (default or "")


def interactive_setup() -> None:
    """Executa o assistente interativo para configuração do OAuth."""
    # Determinar o caminho do .env no projeto
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    # Carregar variáveis existentes
    _load_env_file(env_path)
    print("=== Assistente de Configuração OAuth GoHighLevel ===")
    # Buscar valores existentes ou vazios
    current_client_id = os.getenv("GHL_CLIENT_ID") or None
    current_client_secret = os.getenv("GHL_CLIENT_SECRET") or None
    current_redirect = os.getenv("GHL_REDIRECT_URI") or None
    current_user_type = os.getenv("GHL_USER_TYPE") or "Company"

    client_id = prompt_input("Informe o GHL_CLIENT_ID", default=current_client_id)
    client_secret = prompt_input("Informe o GHL_CLIENT_SECRET", default=current_client_secret, secret=True)
    user_type = prompt_input("Tipo de usuário (Company ou Location)", default=current_user_type) or "Company"
    # Redirecionamento opcional. Se não fornecido, não será enviado no POST
    redirect_uri = prompt_input(
        "Informe o redirect_uri (mesmo utilizado na configuração do app; deixe em branco para omitir)",
        default=current_redirect,
    )
    # Persistir no .env se set_key estiver disponível
    if client_id:
        _update_env_file(env_path, "GHL_CLIENT_ID", client_id)
    if client_secret:
        _update_env_file(env_path, "GHL_CLIENT_SECRET", client_secret)
    if redirect_uri:
        _update_env_file(env_path, "GHL_REDIRECT_URI", redirect_uri)
    if user_type:
        _update_env_file(env_path, "GHL_USER_TYPE", user_type)

    # Compor a URL de autorização
    base_url = "https://marketplace.leadconnectorhq.com/oauth/chooselocation"
    # Se não houver redirect_uri, definir um padrão para permitir que o fluxo prossiga,
    # mas avisaremos mais abaixo que pode causar erro.
    effective_redirect = redirect_uri or "https://example.com/callback"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": effective_redirect,
        # Escopos mínimos necessários; não inclua offline_access pois não é suportado
        "scope": "conversations/message.readonly conversations/message.write",
    }
    auth_url = f"{base_url}?{urlencode(params)}"

    print(
        textwrap.dedent(
            f"""
            -------------------------------------------------------------
            Será necessário autorizar o aplicativo no GoHighLevel.
            Caso tenha configurado um redirect_uri local (por exemplo,
            http://localhost:5000/callback), o script pode iniciar um servidor
            temporário para capturar automaticamente o código de autorização.
            Caso contrário, você poderá copiar manualmente o valor do código
            presente na URL após a autorização.
            -------------------------------------------------------------
            """
        ).strip()
    )

    use_local_server = False
    code_from_server: Optional[str] = None
    # Verificar se o redirect_uri é local (localhost) para oferecer captura automática
    if effective_redirect.startswith("http://localhost"):
        answer = prompt_input(
            "Deseja iniciar um servidor local para capturar o código automaticamente? (s/n)",
            default="s",
        )
        use_local_server = answer.lower().startswith("s")

    if use_local_server:
        # Extraia porta e caminho
        from urllib.parse import urlparse, parse_qs
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        import time

        parsed = urlparse(effective_redirect)
        host = parsed.hostname or "localhost"
        port = parsed.port or 80
        path = parsed.path or "/"
        code_holder: dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # type: ignore
                parsed_path = urlparse(self.path)
                params = parse_qs(parsed_path.query)
                if "code" in params:
                    code_holder["code"] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h3>Autorizacao concluida.</h3><p>Voce ja pode voltar ao terminal.</p></body></html>"
                    )
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Codigo nao encontrado.")

        server = HTTPServer((host, port), CallbackHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            textwrap.dedent(
                f"""
                🔌 Servidor local iniciado em {host}:{port}. Ao autorizar o aplicativo,
                o navegador redirecionará para {effective_redirect} e o código
                será capturado automaticamente.
                """
            ).strip()
        )

        # Abrir o link no navegador automaticamente se possível
        if webbrowser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass
        else:
            print(f"Abra esta URL no navegador para autorizar o app: {auth_url}")

        # Aguardar código
        print("⏳ Aguardando o código de autorização... (pressione Ctrl+C para cancelar)")
        while "code" not in code_holder:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                print("\nCancelado pelo usuário.")
                server.shutdown()
                sys.exit(1)
        # Código capturado
        auth_code = code_holder["code"]
        server.shutdown()
        print("✅ Código capturado com sucesso! Continuando...")
    else:
        # Exibir a URL para o usuário abrir
        print(
            textwrap.dedent(
                f"""
                Copie e cole o link abaixo no seu navegador para autorizar o aplicativo.
                Após conceder o acesso, você será redirecionado e o navegador
                incluirá um parâmetro `code` na URL. Copie apenas o valor do código
                e informe no próximo passo.

                {auth_url}
                """
            ).strip()
        )
        # Abrir automaticamente se o usuário desejar
        if webbrowser:
            try:
                open_now = prompt_input("Deseja abrir o link automaticamente? (s/n)", default="s")
                if open_now.lower().startswith("s"):
                    webbrowser.open(auth_url)
            except Exception:
                pass
        auth_code = prompt_input("Cole o código de autorização recebido")
        if not auth_code:
            print("❌ Nenhum código de autorização fornecido. Encerrando.")
            sys.exit(1)

    # Realizar a troca do código por tokens
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "user_type": user_type,
    }
    # Incluir redirect_uri somente se foi informado
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    print("\n🔄 Solicitando tokens...\n")
    try:
        response = requests.post(
            "https://services.leadconnectorhq.com/oauth/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Erro ao conectar: {exc}")
        sys.exit(1)
    if response.status_code not in (200, 201):
        print(f"❌ Falha ao obter tokens: {response.status_code}\nResposta: {response.text}")
        sys.exit(1)
    token_data = response.json()
    # Persistir tokens
    token_file = config.GHL_TOKEN_FILE
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with token_file.open("w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=4, ensure_ascii=False)
    print(f"✅ Tokens obtidos e salvos em {token_file}\n")


def main() -> None:
    interactive_setup()


if __name__ == "__main__":
    main()