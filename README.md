# ZOI-IA

Este repositório reúne utilitários para integração com o GoHighLevel.
Ele contém scripts para execução do fluxo OAuth da API, rastreamento de tags em contatos e geração de resumos de conversas usando OpenAI ou modelos locais.

## Arquivos locais

Os scripts deste repositório criam alguns arquivos de uso local que contêm credenciais ou estado temporário e não devem ser versionados. Todos ficam centralizados na pasta `data/`.

- `data/agency_token.json` e `data/location_token.json` são gerados pelo fluxo de autenticação em `oauth.py`. Execute `python oauth.py` para obter novos tokens; os arquivos serão gravados em `data/`.
- `data/tag_ia_atendimento_ativa.json` é criado por `tag_tracker.py` e armazena os contatos já processados pela tag "ia - ativa".
- `data/messages/` contém o histórico de mensagens por contato.
- `patch.patch` pode ser usado para guardar ajustes temporários com `git apply` e não faz parte do código fonte.

Mantenha esses arquivos apenas localmente. Caso sejam removidos ou expirem, basta executar novamente os scripts correspondentes para regenerá-los. O `.gitignore` já ignora toda a pasta `data/`.

## Módulos

- `oauth.py` – executa o fluxo OAuth do GoHighLevel e salva os tokens em `data/agency_token.json` e `data/location_token.json` para futuras chamadas de API.
- `tag_tracker.py` – servidor assíncrono que consome webhooks do GoHighLevel; usa `storage` e `clients/ghl_client` e mantém um resumo contextual das interações.
- `summarizer.py` – função utilitária que gera um resumo textual das mensagens recebidas, utilizando `OPENAI_MODEL` ou um pipeline do Hugging Face.
- `storage.py` – I/O local (store, mensagens por contato, tokens) centralizado em `data/`.
- `clients/ghl_client.py` – cliente HTTP para GoHighLevel (listar mensagens de conversas e enviar respostas).
- `services/context_service.py` – regra de atualização/compactação do contexto a partir do histórico.

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração

1. **Variáveis de ambiente**
   - `OPENAI_API_KEY`: chave para a API da OpenAI.
   - `OPENAI_MODEL`: modelo a ser usado no resumo (ex.: `gpt-3.5-turbo`).
2. **Tokens do GoHighLevel**
   - Execute `python oauth.py` e informe `GHL_CLIENT_ID` e `GHL_CLIENT_SECRET` para gerar `data/agency_token.json` e `data/location_token.json`.

## Exemplos de execução

### Resumo de mensagens

```bash
python - <<'PY'
import asyncio
from summarizer import summarize
msgs=[{"direction":"inbound","body":"Olá"},{"direction":"outbound","body":"Oi, tudo bem?"}]
print(asyncio.run(summarize(msgs)))
PY
```

### Fluxo OAuth

```bash
python oauth.py
```
Siga as instruções na tela; ao finalizar, os tokens serão salvos em `data/agency_token.json` e `data/location_token.json`.

### Servidor de webhooks

```bash
python tag_tracker.py
```
O servidor (porta padrão `8081`) expõe:
- `GET /healthz`
- `GET /contacts/ativa`
- `POST /webhooks/ghl/contact-tag`
- `POST /webhooks/ghl/inbound-message`
 - `POST /webhooks/ghl/outbound-message`

## Desenvolvimento

- Dependências de desenvolvimento em `requirements-dev.txt` (pytest, pytest-asyncio).
- Rodar testes:

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Fluxo OAuth e uso dos tokens

1. Registre um aplicativo no Marketplace do GoHighLevel e configure o Redirect URI para `http://localhost:8080/oauth/callback` (ou outro de sua preferência).
2. Execute `python oauth.py` para abrir o navegador e autorizar o aplicativo.
3. Após conceder acesso, o script salva os tokens no disco. O token de Location é usado por `tag_tracker.py` para buscar o histórico de conversas e validar webhooks.

## Rodando o servidor de webhooks

1. Gere e salve o token de Location como descrito acima.
2. Configure os webhooks do GoHighLevel para apontar para o endereço público que encaminha as requisições ao servidor local (por exemplo, usando `ngrok`).
3. Execute `python tag_tracker.py` e acompanhe os logs no terminal.
