# IA‑ZOI – Integração IA para GoHighLevel

Este projeto é uma reestruturação do código original para integrar GoHighLevel a uma camada de inteligência
artificial (IA) utilizando GPT‑4.1.  O objetivo da reestruturação é organizar melhor as responsabilidades
do código, centralizar configurações sensíveis e facilitar testes e manutenção.

## Visão geral

* **`ia_zoi/config.py`** – Carrega configurações a partir de variáveis de ambiente (ou de um arquivo
  `.env`) e fornece acesso centralizado a tokens e chaves de API.
* **`ia_zoi/core`** – Contém a lógica de domínio principal: histórico de conversas, integração com a IA,
  verificação de tags e processador de mensagens.
* **`ia_zoi/web`** – Fornece um servidor Flask para recebimento de webhooks e roteamento de eventos.
* **`ia_zoi/scripts`** – Scripts utilitários para atualização de tokens e sincronização de usuários/campos
  personalizados no GoHighLevel.

## Instalação

Recomenda‑se utilizar um ambiente virtual (``venv`` ou ``conda``).  Para instalar as dependências:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Edite o arquivo `.env` (pode começar copiando o `.env.example`) e forneça suas credenciais de
integração (chaves da API do GoHighLevel e do OpenAI).  Variáveis suportadas incluem:

* `GHL_CLIENT_ID`, `GHL_CLIENT_SECRET` e `GHL_AUTH_CODE` – credenciais para gerar tokens de agência.
* `GHL_USER_TYPE` – tipo de usuário para o OAuth (``Company`` ou ``Location``).
* `OPENAI_API_KEY` e `OPENAI_API_BASE` – credenciais do OpenAI.

## Uso

Abaixo estão os principais fluxos disponíveis.  Todos os scripts devem ser executados a partir da
raiz do projeto (onde se encontra o arquivo ``.env``).  O módulo ``ia_zoi.config`` carrega
automaticamente as variáveis definidas em ``.env`` via [python‑dotenv](https://github.com/theskumar/python-dotenv);
portanto, desde que você execute os comandos na raiz, não há necessidade de exportar as variáveis
manualmente.  Se desejar, pode carregá‑las no shell com ``set -a && source .env && set +a``.

1. **Executar o assistente de OAuth** – A forma mais fácil de obter o
   ``access_token`` e o ``refresh_token`` é utilizar o script
   ``oauth_setup``. Ele pedirá seu ``client_id`` e ``client_secret``,
   mostrará a URL de autorização para instalar o app e, após você
   informar o código de autorização, salvará os tokens em
   ``data/gohighlevel_token.json`` e atualizará o arquivo ``.env`` com
   as credenciais fornecidas. Execute:

   ```bash
   python -m ia_zoi.scripts.oauth_setup
   ```

   Dica: configure no Marketplace do GoHighLevel um `redirect_uri`
   local (por exemplo, `http://localhost:5000/callback`) e informe esse
   mesmo valor quando o script solicitar. O ``oauth_setup`` iniciará
   automaticamente um servidor local para capturar o código de
   autorização, evitando a necessidade de copiar e colar manualmente.

   Se preferir um fluxo não interativo, ainda é possível definir
   ``GHL_CLIENT_ID``, ``GHL_CLIENT_SECRET``, ``GHL_AUTH_CODE`` e
   ``GHL_USER_TYPE`` manualmente no ``.env`` e executar

   ```bash
   python -m ia_zoi.scripts.init_token
   ```

   para trocar o código por tokens.

2. **Atualizar tokens** – Após obter o token inicial, você pode renová‑lo periodicamente e
   sincronizar os tokens de cada localização usando:

   ```bash
   python -m ia_zoi.scripts.refresh_tokens
   ```

   Este script lê o ``refresh_token`` salvo em ``data/gohighlevel_token.json`` e grava tokens
   específicos por localização em arquivos correspondentes.

3. **Buscar localidades instaladas** – Para popular o arquivo ``data/installed_locations_data.json``
   com as localizações onde o app está instalado, defina ``GHL_APP_ID`` e ``GHL_COMPANY_ID`` no
   ``.env`` e execute:

   ```bash
   python -m ia_zoi.scripts.fetch_locations
   ```

4. **Sincronizar usuários** – Após ter a lista de localizações em ``installed_locations_data.json``,
   você pode consultar a API para obter a lista de usuários de cada localização e atualizar
   campos personalizados:

   ```bash
   python -m ia_zoi.scripts.get_users
   ```

   O resultado é salvo em ``data/users.json``.

5. **Atualizar lista de opções de campo** – Para atualizar o campo gerenciado com a lista de
   usuários (por exemplo, para permitir seleção em formulários), utilize:

   ```bash
   python -m ia_zoi.scripts.update_user_list
   ```

6. **Processar atribuição de contatos** – Se seu fluxo de webhooks envolve a atribuição dinâmica de
   contatos a usuários, o script a seguir executa a lógica de atribuição para um contato específico:

   ```bash
   python -m ia_zoi.scripts.process_contact_assignment --contact-id <id>
   ```

   Ele lê a lista de usuários, verifica a disponibilidade e registra a atribuição em
   ``data/registros_atribuicoes_contatos.json``.

7. **Servidor de webhooks** – Para colocar a aplicação no ar e processar eventos do GoHighLevel,
   inicie o servidor Flask:

   ```bash
   python -m ia_zoi.web.server
   ```

   O servidor expõe duas rotas: ``/`` (retorna ``OK``) e ``/webhook`` (recebe eventos POST).  Ele
   utiliza os módulos de ``ia_zoi/web/router.py`` e ``ia_zoi/core`` para tratar mensagens, criar
   respostas com IA, verificar tags e executar scripts auxiliares.

## Estrutura de dados

Os dados persistidos (histórico de conversas, tokens, lista de usuários, cache de tags etc.) são
salvos no diretório ``data``.  Em ambientes de produção recomenda‑se substituir os arquivos JSON
por um banco de dados relacional ou por uma solução como Redis para lidar com concorrência e
sincronização entre múltiplas instâncias.
