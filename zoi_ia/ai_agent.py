"""Orquestra a montagem das mensagens para o chat model.

Este módulo combina:
- Template do prompt base (arquivo `prompt.md`) com um cabeçalho parametrizado
  por variáveis de ambiente (marca, tom, canal, idiomas, SLA e estilo).
- Exemplos de comportamento (few‑shots) opcionais, lidos de um JSON.
- Memória resumida da conversa (quando existente) e contexto extra (RAG).
- As últimas mensagens da conversa, limitadas a uma janela curta.

Nada aqui persiste estado; a função pública `generate_reply` recebe um `store`
imutável (dict) e retorna apenas a resposta textual do modelo.
"""

import logging
import os
from pathlib import Path
import json

try:  # pragma: no cover - openai é opcional
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None


# prompt.md fica na raiz do projeto; este arquivo está em zoi_ia/
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"


from .config import (
    BRAND_NAME,
    VOICE_TONE,
    CHANNEL,
    SLA_POLICY,
    LANGUAGES,
    OUTPUT_STYLE,
    USE_FEWSHOTS,
    PROMPT_FEWSHOTS_PATH,
)


def _system_prompt() -> str:
    """Monta o conteúdo do papel "system".

    Lê o arquivo `prompt.md` (na raiz do projeto) e o prefixa com um cabeçalho
    de parâmetros de atendimento. Caso o arquivo não exista, retorna um
    fallback simples para evitar falhas em ambientes mínimos.
    """
    try:
        base = _PROMPT_PATH.read_text(encoding="utf-8").strip()
        header = (
            "Parâmetros do atendimento (não compartilhar com o cliente):\n"
            f"- Marca: {BRAND_NAME}\n"
            f"- Canal: {CHANNEL}\n"
            f"- Tom/voz: {VOICE_TONE}\n"
            f"- Idiomas: {LANGUAGES}\n"
            f"- SLA: {SLA_POLICY}\n"
            f"- Estilo de saída: {OUTPUT_STYLE}\n"
            "\n"
        )
        return header + base
    except OSError:
        # Fallback ultra‑simples em caso de falta do arquivo.
        return "Você é um assistente que responde de forma educada."


def _fewshots() -> list[dict]:
    """Carrega exemplos de comportamento (few‑shots) do arquivo configurado.

    Espera um JSON em lista com objetos {"role", "content"}. Em caso de erro,
    arquivo ausente ou `USE_FEWSHOTS=false`, retorna uma lista vazia.
    """
    if not USE_FEWSHOTS:
        return []
    try:
        raw = PROMPT_FEWSHOTS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            msgs: list[dict] = []
            for item in data:
                if isinstance(item, dict) and item.get("role") and item.get("content"):
                    msgs.append({"role": str(item["role"]), "content": str(item["content"])})
            return msgs
    except Exception:
        # Silencioso: few‑shots são opcionais e não devem quebrar o fluxo.
        pass
    return []


async def generate_reply(store: dict, extra_context: str | None = None) -> str:
    """Gera uma resposta usando janela curta de conversa + memórias.

    Regras principais:
    - Usa no máximo as 15 mensagens recentes do histórico do `store`.
    - Faz o mapeamento: inbound -> role="user"; outbound -> role="assistant".
    - Injeta, antes da conversa, o papel "system" (template + cabeçalho),
      seguida de few‑shots (se habilitados), memória resumida (se houver) e
      `extra_context` (se fornecido via RAG).

    Args:
        store: Estrutura volátil da conversa (mensagens, context, flow, ...).
        extra_context: Contexto externo (ex.: trechos recuperados via RAG) a
            ser injetado como nota de sistema para orientar a resposta.

    Returns:
        Texto com a resposta do modelo, ou string vazia em caso de falha.
    """
    context = store.get("context") or ""
    raw_messages = store.get("messages") or []

    convo: list[dict] = []
    for m in raw_messages:
        # Mantém apenas mensagens do usuário/assistente e descarta metadados.
        if m.get("direction") in {"inbound", "outbound"}:
            convo.append(m)
        # Limita a janela a 15 itens começando pelos mais recentes do array.
        if len(convo) >= 15:
            break

    if not convo:
        return ""

    has_inbound = any(m.get("direction") == "inbound" for m in convo)
    if not has_inbound:
        return ""

    if AsyncOpenAI is None:
        return ""

    chat_messages = [
        {"role": "system", "content": _system_prompt()},
    ]
    # Insere exemplos (few‑shots) antes da conversa real, se existirem.
    chat_messages.extend(_fewshots())
    if context:
        chat_messages.append({
            "role": "assistant",
            "content": f"Memória (não compartilhar com o cliente):\n{context}",
        })
    if extra_context:
        chat_messages.append({
            "role": "assistant",
            "content": f"Contexto recuperado (não compartilhar com o cliente):\n{extra_context}",
        })

    flow = store.get("flow") or {}
    if isinstance(flow, dict) and (flow.get("current_step") or flow.get("checklist")):
        import json as _json
        chat_messages.append({
            "role": "assistant",
            "content": (
                "Memória de processo (não compartilhar com o cliente):\n"
                + _json.dumps(flow, ensure_ascii=False)
            ),
        })

    # O modelo espera ordem cronológica: do mais antigo para o mais recente.
    for m in reversed(convo):
        role = "user" if m.get("direction") == "inbound" else "assistant"
        body = m.get("body") or ""
        chat_messages.append({"role": role, "content": str(body)})

    try:
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5-nano"),
            messages=chat_messages,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # pragma: no cover
        logging.exception("Falha gerando resposta: %s", exc)
        return ""
