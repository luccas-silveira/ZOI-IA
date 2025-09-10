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
- `tag_tracker.py` – servidor assíncrono que consome webhooks do GoHighLevel; usa o pacote `zoi_ia` (storage/clients/services/rag) e mantém um resumo contextual das interações.
- `zoi_ia/ai_agent.py` – orquestra a geração de respostas (prompt template + memória + RAG + últimas mensagens).
- `zoi_ia/storage.py` – I/O local (store, mensagens por contato, tokens) centralizado em `data/`.
- `zoi_ia/clients/ghl_client.py` – cliente HTTP para GoHighLevel (listar mensagens de conversas e enviar respostas) com retries.
- `zoi_ia/services/context_service.py` – regra de atualização/compactação do contexto a partir do histórico.
- `zoi_ia/rag/` – RAG de conversa: `embedding.py` (gera embeddings), `index.py` (índice por contato), `retriever.py` (busca top‑K e formata contexto).
- `zoi_ia/transcriber.py` – transcrição de áudios recebidos via URL (OpenAI Whisper opcional).
 - `zoi_ia/vision.py` – descrição de imagens via modelo de visão (OpenAI) a partir de URLs.

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração

1. **Variáveis de ambiente**
   - `OPENAI_API_KEY`: chave para a API da OpenAI.
   - `OPENAI_MODEL`: modelo do agente/resumo (padrão do agente: `gpt-5-nano`).
   - `BRAND_NAME`, `VOICE_TONE`, `CHANNEL`, `SLA_POLICY`, `LANGUAGES`, `OUTPUT_STYLE`: personalizam o template do prompt.
   - `USE_FEWSHOTS=true|false` (default `true`) e `PROMPT_FEWSHOTS_PATH` (default `prompt_fewshots.json`).
   - Áudio/Transcrição:
     - `TRANSCRIBE_AUDIO=true|false` (default `true`)
     - `TRANSCRIPTION_MODEL` (default `whisper-1`)
     - `AUDIO_MAX_MB` (default `25`) – limite de tamanho de download
     - `AUDIO_MIME_WHITELIST` (CSV; default inclui `audio/mpeg`, `audio/ogg`, `audio/webm`, `audio/wav`, `audio/3gpp`, ...)
   - Imagem/Visão:
     - `DESCRIBE_IMAGES=true|false` (default `true`)
     - `VISION_MODEL` (default `gpt-4o-mini`)
     - `IMAGE_MAX_MB` (default `10`)
     - `IMAGE_MIME_WHITELIST` (CSV; default inclui `image/jpeg`, `image/png`, `image/webp`, ...)
     - `IMAGE_EXT_WHITELIST` (CSV; default `jpg,jpeg,png,webp,gif,bmp,tif,tiff,heic,heif`)
2. **Tokens do GoHighLevel**
   - Execute `python oauth.py` e informe `GHL_CLIENT_ID` e `GHL_CLIENT_SECRET` para gerar `data/agency_token.json` e `data/location_token.json`.

3. **RAG (opcional, ativado por padrão)**
   - `RAG_ENABLED=true|false` (default `true`)
   - `EMBEDDING_MODEL` (default `text-embedding-3-small` com OpenAI; se sem chave, usa fallback local determinístico)
   - `EMBEDDINGS_DIR` (default `data/embeddings`)
   - `RAG_K` (default 5), `RAG_MIN_SIM` (default 0.3), `RAG_MAX_SNIPPET_CHARS` (default 320)

4. **Contexto/Sumarização**
   - `CONTEXT_SUMMARY_THRESHOLD` (default `30`): quantidade mínima de mensagens acumuladas para gerar novo resumo.
   - `CONTEXT_CHUNK_SIZE` (default `15`): quantidade de mensagens usadas a cada rodada de resumo (as mais recentes dentro do lote).

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
 
Mensagens com anexos de áudio: o webhook de inbound pode incluir `attachments`
com URLs de mídia. Se `TRANSCRIBE_AUDIO=true`, o serviço baixa o arquivo (com
`Authorization: Bearer` quando o host é LeadConnector), transcreve com o modelo
configurado e injeta uma mensagem adicional com o conteúdo:
`[Transcrição de áudio]\n<texto>`. Essa transcrição passa a alimentar o agente e o
índice RAG.

Mensagens com anexos de imagem: se `DESCRIBE_IMAGES=true`, o serviço identifica
os URLs de imagem e gera uma descrição objetiva via `VISION_MODEL`. O corpo da
mensagem inbound é substituído pela(s) descrição(ões) (ou concatenado caso
também haja transcrição de áudio), alimentando o agente e o RAG.

## Desenvolvimento

- Dependências de desenvolvimento em `requirements-dev.txt` (pytest, pytest-asyncio).
- Rodar testes:

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Prompt como Template + Few‑shots

- O `prompt.md` é lido como texto base e o agente adiciona um cabeçalho com parâmetros dinâmicos (marca, canal, tom, etc.) a partir das variáveis de ambiente.
- Exemplos de comportamento (few‑shots) podem ser definidos em `prompt_fewshots.json` (lista de objetos `{role, content}`) e são injetados antes da conversa real. Desative com `USE_FEWSHOTS=false`.

Exemplo mínimo de `prompt_fewshots.json`:

```json
[
  {"role":"user","content":"Oi, vi um carro de vocês no Instagram e queria saber mais."},
  {"role":"assistant","content":"E aí! Tudo certo? Sou da Nick Multimarcas... Consegue falar agora?"}
]
```

## Fluxo OAuth e uso dos tokens

1. Registre um aplicativo no Marketplace do GoHighLevel e configure o Redirect URI para `http://localhost:8080/oauth/callback` (ou outro de sua preferência).
2. Execute `python oauth.py` para abrir o navegador e autorizar o aplicativo.
3. Após conceder acesso, o script salva os tokens no disco. O token de Location é usado por `tag_tracker.py` para buscar o histórico de conversas e validar webhooks.

## Rodando o servidor de webhooks

1. Gere e salve o token de Location como descrito acima.
2. Configure os webhooks do GoHighLevel para apontar para o endereço público que encaminha as requisições ao servidor local (por exemplo, usando `ngrok`).
3. Execute `python tag_tracker.py` e acompanhe os logs no terminal.
