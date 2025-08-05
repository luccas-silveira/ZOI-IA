"""Configuração interativa do fluxo OAuth 2.0 para o IA‑ZOI (versão atualizada).

Esta versão do script mantém o mesmo propósito do original – obter o
``access_token`` e o ``refresh_token`` junto à API do GoHighLevel e
persisti‑los nos arquivos ``.env`` e ``data/gohighlevel_token.json`` –
mas com algumas melhorias:

1. Variáveis já definidas no ``.env`` não são solicitadas novamente. O
   usuário só é questionado quando uma informação estiver ausente.
2. Quando o ``redirect_uri`` apontar para ``localhost``, o servidor
   temporário para captura do código de autorização é sempre iniciado,
   sem solicitar confirmação. Para outros ``redirect_uri``, o link de
   autorização é aberto automaticamente se possível.
3. Após receber e salvar os tokens de agência, o script executa
   ``fetch_locations.main()`` para obter as localizações onde o app
   está instalado e ``refresh_tokens.manage_location_tokens()`` para
   gerar os tokens específicos de cada localização. Dessa forma,
   comandos dependentes de tokens de localização (como ``get_users``)
   funcionam imediatamente depois do OAuth.

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
from urllib.parse import urlencode, urlparse, parse_qs

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
    """Executa o assistente interativo para configuração do OAuth atualizado."""
    # Determinar o caminho do .env no projeto
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    # Carregar variáveis existentes
    _load_env_file(env_path)
    print("=== Assistente de Configuração OAuth GoHighLevel (Atualizado) ===")

    # Buscar valores existentes do ambiente
    current_client_id = os.getenv("GHL_CLIENT_ID") or None
    current_client_secret = os.getenv("GHL_CLIENT_SECRET") or None
    current_redirect = os.getenv("GHL_REDIRECT_URI") or None
    current_user_type = os.getenv("GHL_USER_TYPE") or "Company"

    # Perguntar apenas quando o valor estiver ausente
    client_id: Optional[str] = current_client_id
    if not client_id:
        client_id = prompt_input("Informe o GHL_CLIENT_ID")
        if client_id:
            _update_env_file(env_path, "GHL_CLIENT_ID", client_id)

    client_secret: Optional[str] = current_client_secret
    if not client_secret:
        client_secret = prompt_input("Informe o GHL_CLIENT_SECRET", secret=True)
        if client_secret:
            _update_env_file(env_path, "GHL_CLIENT_SECRET", client_secret)

    user_type: str = current_user_type
    if os.getenv("GHL_USER_TYPE") is None:
        user_type = prompt_input("Tipo de usuário (Company ou Location)", default=user_type) or user_type
        if user_type:
            _update_env_file(env_path, "GHL_USER_TYPE", user_type)

    redirect_uri: Optional[str] = current_redirect
    if redirect_uri is None:
        redirect_uri = prompt_input(
            "Informe o redirect_uri (mesmo utilizado na configuração do app; deixe em branco para omitir)",
            default=current_redirect,
        )
        if redirect_uri:
            _update_env_file(env_path, "GHL_REDIRECT_URI", redirect_uri)

    # Compor a URL de autorização
    base_url = "https://marketplace.leadconnectorhq.com/oauth/chooselocation"
    # Se não houver redirect_uri, definir um padrão para permitir que o fluxo prossiga
    effective_redirect = redirect_uri or "https://example.com/callback"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": effective_redirect,
        # Escopos mínimos necessários; não inclua offline_access pois não é suportado
        "scope": "businesses.readonly businesses.write calendars.readonly calendars.write calendars/events.readonly calendars/events.write calendars/groups.readonly calendars/groups.write calendars/resources.write calendars/resources.readonly campaigns.readonly conversations.readonly conversations.write conversations/message.write conversations/message.readonly conversations/reports.readonly conversations/livechat.write contacts.readonly contacts.write objects/schema.readonly objects/schema.write objects/record.readonly objects/record.write associations.write associations.readonly associations/relation.readonly associations/relation.write courses.write courses.readonly forms.readonly forms.write invoices.readonly invoices.write invoices/schedule.readonly invoices/schedule.write invoices/template.readonly invoices/template.write invoices/estimate.write invoices/estimate.readonly links.readonly lc-email.readonly links.write locations.readonly locations/customValues.readonly locations/customValues.write locations/customFields.readonly locations/customFields.write locations/tasks.readonly locations/tasks.write locations/tags.readonly locations/tags.write locations/templates.readonly medias.readonly medias.write funnels/redirect.readonly funnels/page.readonly funnels/funnel.readonly funnels/pagecount.readonly funnels/redirect.write opportunities.readonly opportunities.write payments/orders.readonly payments/orders.write payments/integration.readonly payments/integration.write payments/transactions.readonly payments/subscriptions.readonly payments/custom-provider.readonly payments/custom-provider.write products.readonly products.write products/prices.readonly products/prices.write products/collection.readonly products/collection.write saas/location.read saas/location.write socialplanner/oauth.readonly socialplanner/oauth.write socialplanner/post.readonly socialplanner/post.write socialplanner/account.readonly socialplanner/account.write socialplanner/csv.readonly socialplanner/csv.write socialplanner/category.readonly socialplanner/tag.readonly store/shipping.readonly store/shipping.write store/setting.readonly store/setting.write surveys.readonly users.readonly workflows.readonly emails/builder.write emails/builder.readonly emails/schedule.readonly wordpress.site.readonly blogs/post.write blogs/post-update.write blogs/check-slug.readonly blogs/category.readonly blogs/author.readonly socialplanner/category.write socialplanner/tag.write blogs/posts.readonly blogs/list.readonly",
    }
    auth_url = f"{base_url}?{urlencode(params)}"

    print(
        textwrap.dedent(
            f"""
            -------------------------------------------------------------
            Será necessário autorizar o aplicativo no GoHighLevel.
            Caso tenha configurado um redirect_uri local (por exemplo,
            http://localhost:5000/callback), o script iniciará um servidor
            temporário para capturar automaticamente o código de autorização.
            Caso contrário, a URL de autorização será aberta automaticamente.
            -------------------------------------------------------------
            """
        ).strip()
    )

    use_local_server = False
    code_from_server: Optional[str] = None
    # Verificar se o redirect_uri é local (localhost) para captura automática
    if effective_redirect.startswith("http://localhost"):
        use_local_server = True

    if use_local_server:
        # Extraia porta e caminho
        parsed = urlparse(effective_redirect)
        host = parsed.hostname or "localhost"
        port = parsed.port or 80
        path = parsed.path or "/"
        code_holder: dict[str, str] = {}

        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        import time

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
                        b" Autorizacao concluida. Voce ja pode voltar ao terminal. "
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
        # Exibir a URL para o usuário abrir (fallback)
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
        # Abrir automaticamente se possível (sem perguntar)
        if webbrowser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass
        # Obter código manualmente
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

    # Chamar scripts adicionais para obter locations e tokens por location
    try:
        # Importação tardia para evitar dependência circular
        from .fetch_locations import main as fetch_locations_main

        print("🔍 Buscando localizações instaladas...")
        fetch_locations_main()
    except Exception as exc:
        print(f"[oauth_setup] Erro ao executar fetch_locations: {exc}")

    try:
        from .refresh_tokens import manage_location_tokens

        print("🔄 Atualizando tokens das localizações...")
        manage_location_tokens()
    except Exception as exc:
        print(f"[oauth_setup] Erro ao atualizar tokens das localizações: {exc}")


def main() -> None:
    interactive_setup()


if __name__ == "__main__":
    main()