import asyncio
import json
import secrets
import sys
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, parse_qs

import httpx
from aiohttp import web

# =========================
# Configurações padrão
# =========================
GHL_BASE_URL = "https://marketplace.gohighlevel.com"
GHL_API_URL = "https://services.leadconnectorhq.com"

# Redirect local - precisa bater com o que você configurar no app do Marketplace
DEFAULT_REDIRECT_URI = "http://localhost:8080/oauth/callback"
DEFAULT_SERVER_PORT = 8080

# Scopes recomendados (adicione/remova conforme seu app)
SCOPES = [
    "businesses.readonly",
    "businesses.write",
    "calendars.readonly",
    "companies.readonly",
    "calendars.write",
    "calendars/events.readonly",
    "calendars/events.write",
    "calendars/groups.readonly",
    "calendars/groups.write",
    "calendars/resources.readonly",
    "calendars/resources.write",
    "campaigns.readonly",
    "conversations.readonly",
    "conversations.write",
    "conversations/message.readonly",
    "conversations/message.write",
    "conversations/reports.readonly",
    "conversations/livechat.write",
    "contacts.readonly",
    "contacts.write",
    "objects/schema.readonly",
    "objects/schema.write",
    "objects/record.write",
    "objects/record.readonly",
    "associations.write",
    "associations.readonly",
    "associations/relation.readonly",
    "associations/relation.write",
    "courses.write",
    "courses.readonly",
    "forms.readonly",
    "forms.write",
    "invoices.readonly",
    "invoices.write",
    "invoices/schedule.readonly",
    "invoices/schedule.write",
    "invoices/template.readonly",
    "invoices/template.write",
    "invoices/estimate.readonly",
    "invoices/estimate.write",
    "links.readonly",
    "lc-email.readonly",
    "links.write",
    "locations.write",
    "locations.readonly",
    "locations/customValues.readonly",
    "locations/customValues.write",
    "locations/customFields.readonly",
    "locations/customFields.write",
    "locations/tasks.readonly",
    "locations/tasks.write",
    "locations/tags.readonly",
    "locations/tags.write",
    "locations/templates.readonly",
    "medias.readonly",
    "medias.write",
    "funnels/redirect.readonly",
    "funnels/page.readonly",
    "funnels/funnel.readonly",
    "funnels/pagecount.readonly",
    "funnels/redirect.write",
    "oauth.write",
    "oauth.readonly",
    "opportunities.readonly",
    "opportunities.write",
    "payments/orders.readonly",
    "payments/orders.write",
    "payments/integration.readonly",
    "payments/transactions.readonly",
    "payments/integration.write",
    "payments/subscriptions.readonly",
    "payments/coupons.readonly",
    "payments/coupons.write",
    "payments/custom-provider.readonly",
    "payments/custom-provider.write",
    "products.readonly",
    "products.write",
    "products/prices.readonly",
    "products/prices.write",
    "products/collection.readonly",
    "products/collection.write",
    "saas/company.read",
    "saas/location.read",
    "saas/company.write",
    "saas/location.write",
    "snapshots.readonly",
    "snapshots.write",
    "socialplanner/oauth.readonly",
    "socialplanner/oauth.write",
    "socialplanner/post.readonly",
    "socialplanner/post.write",
    "socialplanner/account.readonly",
    "socialplanner/account.write",
    "socialplanner/csv.readonly",
    "socialplanner/csv.write",
    "socialplanner/category.readonly",
    "socialplanner/tag.readonly",
    "store/shipping.readonly",
    "socialplanner/statistics.readonly",
    "store/shipping.write",
    "store/setting.readonly",
    "store/setting.write",
    "surveys.readonly",
    "users.readonly",
    "users.write",
    "workflows.readonly",
    "emails/builder.write",
    "emails/schedule.readonly",
    "emails/builder.readonly",
    "wordpress.site.readonly",
    "blogs/post.write",
    "blogs/post-update.write",
    "blogs/check-slug.readonly",
    "blogs/category.readonly",
    "blogs/author.readonly",
    "socialplanner/category.write",
    "socialplanner/tag.write",
    "custom-menu-link.readonly",
    "custom-menu-link.write",
    "blogs/posts.readonly",
    "blogs/list.readonly",
    "charges.readonly",
    "charges.write",
    "twilioaccount.read",
    "documents_contracts/list.readonly",
    "documents_contracts/sendLink.write",
    "documents_contracts_template/sendLink.write",
    "documents_contracts_template/list.readonly",
    "marketplace-installer-details.readonly",
    "knowledge-bases.write",
    "knowledge-bases.readonly",
]

# Onde salvar tokens
TOKEN_PATH = Path("agency_token.json")
LOCATION_TOKEN_PATH = Path("location_token.json")
# Header de versão exigido por diversas rotas do GHL
GHL_API_VERSION = "2021-07-28"


@dataclass
class TokenBundle:
    access_token: str
    token_type: str
    refresh_token: Optional[str]
    scope: Optional[str]
    user_type: Optional[str]
    expires_at: Optional[str]  # ISO string
    company_id: Optional[str] = None
    location_id: Optional[str] = None


async def exchange_code_for_tokens(
    client: httpx.AsyncClient,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> TokenBundle:
    """
    Troca o authorization code por access/refresh tokens.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        # Importante: para apps GHL o user_type costuma ser "Location" (se instalar direto numa subconta)
        # ou "Company" (se instalar no nível de Agência).
        "user_type": "Location",
    }

    resp = await client.post(
        f"{GHL_API_URL}/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    # calcula expires_at (se houver expires_in)
    expires_at = None
    if "expires_in" in payload:
        expires_at = (datetime.utcnow() + timedelta(seconds=int(payload["expires_in"]))).isoformat() + "Z"

    return TokenBundle(
        access_token=payload.get("access_token"),
        token_type=payload.get("token_type", "Bearer"),
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope"),
        user_type=payload.get("userType") or payload.get("user_type"),
        expires_at=expires_at,
        company_id=payload.get("companyId"),
        location_id=payload.get("locationId"),
    )


async def get_location_access_token(
    client: httpx.AsyncClient,
    agency_access_token: str,
    company_id: str,
    location_id: str,
) -> TokenBundle:
    """
    Usa o token de Agência (userType=Company) para gerar um token de Location.
    Endpoint: POST /oauth/locationToken
    """
    headers = {
        "Authorization": f"Bearer {agency_access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": GHL_API_VERSION,
    }
    body = {"companyId": company_id, "locationId": location_id}

    resp = await client.post(
        f"{GHL_API_URL}/oauth/locationToken",
        headers=headers,
        json=body,
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    expires_at = None
    if "expires_in" in payload:
        expires_at = (datetime.utcnow() + timedelta(seconds=int(payload["expires_in"]))).isoformat() + "Z"

    return TokenBundle(
        access_token=payload.get("access_token"),
        token_type=payload.get("token_type", "Bearer"),
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope"),
        user_type=payload.get("userType") or payload.get("user_type"),
        expires_at=expires_at,
        company_id=payload.get("companyId"),
        location_id=payload.get("locationId"),
    )


async def run_oauth_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    server_port: int = DEFAULT_SERVER_PORT,
):
    """
    Sobe servidor local, abre o navegador em /oauth/chooselocation e captura o code.
    """

    # estado anti-CSRF
    expected_state = secrets.token_urlsafe(32)

    # monta URL de autorização com todos os scopes
    auth_params = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "scope": " ".join(SCOPES),
        "state": expected_state,
    }
    auth_url = f"{GHL_BASE_URL}/oauth/chooselocation?{urlencode(auth_params)}"

    # future pra receber o code
    loop = asyncio.get_running_loop()
    code_future: asyncio.Future[str] = loop.create_future()

    async def handle_callback(request: web.Request):
        # parse da query
        query = parse_qs(request.query_string)
        state = query.get("state", [None])[0]
        if state != expected_state:
            return web.Response(text="Invalid state parameter", status=400)

        error = query.get("error", [None])[0]
        if error:
            desc = query.get("error_description", [""])[0]
            return web.Response(text=f"Authorization failed: {error} - {desc}", status=400)

        code = query.get("code", [None])[0]
        if not code:
            return web.Response(text="Missing authorization code", status=400)

        if not code_future.done():
            code_future.set_result(code)

        return web.Response(
            text=(
                "<html><body><h1>Autorização concluída!</h1>"
                "<p>Você já pode fechar esta aba.</p></body></html>"
            ),
            content_type="text/html",
        )

    # servidor local
    app = web.Application()
    app.router.add_get("/oauth/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", server_port)
    await site.start()

    print(f"↪️  Callback aguardando em: http://localhost:{server_port}/oauth/callback")
    print("🌐 Abrindo o navegador para autorizar o app...")
    print(f"   {auth_url}\n")

    # abre o browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("⚠️  Não consegui abrir o navegador automaticamente. Cole a URL acima no seu navegador.")

    # espera o code chegar pelo callback
    code = await code_future

    # fecha o servidor com um pequeno atraso para garantir resposta ao browser
    async def _cleanup():
        await asyncio.sleep(1.0)
        await runner.cleanup()

    asyncio.create_task(_cleanup())

    # troca code por token
    async with httpx.AsyncClient() as client:
        tokens = await exchange_code_for_tokens(
            client=client,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )

    # salva em agency_token.json (pode ser token de Location ou de Company, dependendo da instalação)
    TOKEN_PATH.write_text(json.dumps(asdict(tokens), indent=2, ensure_ascii=False))
    print(f"✅ Tokens salvos em: {TOKEN_PATH.resolve()}")

    # imprime um resumo
    print("\n— Resumo (Token atual) —")
    print("access_token:", (tokens.access_token[:24] + "...") if tokens.access_token else None)
    print("token_type:", tokens.token_type)
    print("refresh_token:", (tokens.refresh_token[:24] + "...") if tokens.refresh_token else None)
    print("user_type:", tokens.user_type)
    print("company_id:", tokens.company_id)
    print("location_id:", tokens.location_id)
    print("scope:", tokens.scope)
    print("expires_at:", tokens.expires_at)

    # =========================
    # Obter token de Location via token de Agência (opcional)
    # =========================
    try:
        resp = input("\nDeseja gerar e salvar o token de uma Location agora? (s/n): ").strip().lower()
        if resp == "s":
            location_id = input("Informe o ID da Location (subconta): ").strip()

            # Precisamos de um token de Agência (userType=Company) para chamar /oauth/locationToken.
            agency_access_token = tokens.access_token
            agency_user_type = (tokens.user_type or "").lower()

            # companyId pode vir do token de Agência; se não vier, perguntamos.
            company_id = tokens.company_id

            if not company_id:
                company_id = input("Informe o ID da Company (agência): ").strip()

            if agency_user_type != "company":
                print("\n⚠️  O token atual não é de Agência (userType=Company).")
                print("    A API /oauth/locationToken requer um access_token de Agência.")
                use_manual = input("Quer informar manualmente um access_token de Agência? (s/n): ").strip().lower()
                if use_manual == "s":
                    agency_access_token = input("Cole o access_token de Agência (Bearer): ").strip()
                else:
                    print("Operação cancelada. Encerrando sem gerar token de Location.")
                    return

            if not company_id:
                print("⚠️  companyId não informado. Encerrando sem gerar token de Location.")
                return

            async with httpx.AsyncClient() as client2:
                try:
                    loc_tokens = await get_location_access_token(
                        client=client2,
                        agency_access_token=agency_access_token,
                        company_id=company_id,
                        location_id=location_id,
                    )
                except httpx.HTTPStatusError as e:
                    # Tenta exibir corpo de erro para facilitar debug
                    body = ""
                    try:
                        body = e.response.text
                    except Exception:
                        pass
                    print(f"\n❌ Erro ao obter token da Location: HTTP {e.response.status_code}")
                    if body:
                        print(body)
                    return

            # Salva o token de Location
            LOCATION_TOKEN_PATH.write_text(json.dumps(asdict(loc_tokens), indent=2, ensure_ascii=False))
            print(f"\n✅ Token da Location salvo em: {LOCATION_TOKEN_PATH.resolve()}")

            # Resumo (Location)
            print("\n— Resumo (Location) —")
            print("access_token:", (loc_tokens.access_token[:24] + "...") if loc_tokens.access_token else None)
            print("token_type:", loc_tokens.token_type)
            print("refresh_token:", (loc_tokens.refresh_token[:24] + "...") if loc_tokens.refresh_token else None)
            print("user_type:", loc_tokens.user_type)
            print("company_id:", loc_tokens.company_id)
            print("location_id:", loc_tokens.location_id)
            print("scope:", loc_tokens.scope)
            print("expires_at:", loc_tokens.expires_at)

        # Caso 'n' ou outra tecla: encerrar silenciosamente
    except KeyboardInterrupt:
        # Mesmo comportamento: encerrar silenciosamente.
        pass


def ask(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    try:
        if default:
            raw = input(f"{prompt} [{default}]: ").strip()
            return raw or default
        return input(f"{prompt}: ").strip()
    except KeyboardInterrupt:
        print("\nCancelado pelo usuário.")
        sys.exit(1)


def main():
    print("\n=== GoHighLevel OAuth Quickstart ===\n")
    print("Dica: garanta que o Redirect URI do seu app no Marketplace seja exatamente o mesmo informado aqui.\n")

    client_id = ask("GHL_CLIENT_ID")
    client_secret = ask("GHL_CLIENT_SECRET")
    redirect_uri = ask("Redirect URI", DEFAULT_REDIRECT_URI)
    try:
        port = int(ask("Callback server port", str(DEFAULT_SERVER_PORT)))
    except ValueError:
        print("Porta inválida.")
        sys.exit(1)

    print("\nIniciando fluxo OAuth...\n")
    asyncio.run(run_oauth_flow(client_id, client_secret, redirect_uri, port))


if __name__ == "__main__":
    main()
