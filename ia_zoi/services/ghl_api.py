"""Camada de serviço para a API do GoHighLevel.

Este módulo fornece funções utilitárias para interagir com a API do
GoHighLevel (GHL).  Todas as chamadas HTTP para buscar contatos,
enviar mensagens e ler tokens devem ser centralizadas aqui.  Dessa
forma, eventuais mudanças na API ou necessidade de tratamentos
específicos ficam confinadas a este ponto de integração.

As credenciais (tokens de acesso) são lidas do arquivo JSON
``gohighlevel_token.json`` localizado em ``config.GHL_TOKEN_FILE``.  O
módulo não tenta atualizar ou renovar tokens automaticamente; essa
responsabilidade cabe a scripts dedicados em ``ia_zoi.scripts``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from .. import config

# Configure o logger para herdar a configuração global.
logger = logging.getLogger(__name__)

# Base URL e versão da API do GoHighLevel.  Caso a API seja atualizada
# globalmente, altere estes valores aqui.
API_BASE_URL: str = "https://services.leadconnectorhq.com"
API_VERSION: str = "2021-07-28"


def _load_token_file(token_file: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Carrega o arquivo JSON que contém os tokens de acesso.

    Por padrão o arquivo em ``config.GHL_TOKEN_FILE`` é usado.  O
    conteúdo do arquivo deve ser um objeto JSON contendo um campo
    ``access_token``.  Se o arquivo não existir ou não for possível
    decodificá‑lo, ``None`` será retornado.

    Args:
        token_file: caminho opcional para um arquivo específico.

    Returns:
        O conteúdo do arquivo JSON como dicionário, ou ``None``.
    """
    file_path = Path(token_file) if token_file else config.GHL_TOKEN_FILE
    try:
        if not file_path.exists():
            logger.warning("Arquivo de token do GoHighLevel não encontrado: %s", file_path)
            return None
        with file_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Falha ao carregar o arquivo de tokens %s: %s", file_path, exc)
        return None


def get_access_token() -> Optional[str]:
    """Retorna o access token atual do GoHighLevel.

    O token é lido do arquivo ``gohighlevel_token.json``.  Se o token
    estiver ausente ou o arquivo não puder ser lido, ``None`` será
    retornado.  Não há tentativa de refresh automático.

    Returns:
        String do access token, ou ``None``.
    """
    token_data = _load_token_file()
    if token_data and isinstance(token_data, dict):
        return token_data.get("access_token")
    return None


def get_contact(contact_id: str) -> Optional[Dict[str, Any]]:
    """Obtém os dados de um contato a partir do seu ID.

    Esta função consulta a API do GHL para buscar as informações de um
    contato específico.  Ela lida com erros comuns como token inválido,
    contato inexistente e timeouts, registrando mensagens no logger.

    Args:
        contact_id: identificador do contato.

    Returns:
        Dicionário com os dados do contato (incluindo ``tags``), ou
        ``None`` em caso de erro.
    """
    token = get_access_token()
    if not token:
        logger.error("Não há token disponível para buscar contato %s.", contact_id)
        return None
    url = f"{API_BASE_URL}/contacts/{contact_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("contact", {})
        if response.status_code == 401:
            logger.error("Token inválido ou expirado ao buscar contato %s.", contact_id)
        elif response.status_code == 404:
            logger.warning("Contato %s não encontrado.", contact_id)
        else:
            logger.error(
                "Erro da API GHL ao buscar contato %s: %s - %s",
                contact_id,
                response.status_code,
                response.text,
            )
    except requests.exceptions.Timeout:
        logger.error("Timeout ao buscar contato %s.", contact_id)
    except requests.exceptions.RequestException as exc:
        logger.error("Erro de rede ao buscar contato %s: %s", contact_id, exc)
    except Exception as exc:
        logger.error("Erro inesperado ao buscar contato %s: %s", contact_id, exc)
    return None


def send_message(
    conversation_id: str,
    message_text: str,
    reply_message_id: Optional[str] = None,
    message_type: str = "SMS",
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Envia uma mensagem para a conversa especificada.

    Args:
        conversation_id: ID da conversa no GHL.
        message_text: conteúdo textual da mensagem.
        reply_message_id: opcional, ID da mensagem a ser respondida.
        message_type: tipo da mensagem, ex. ``SMS`` ou ``MMS``.

    Returns:
        Uma tupla ``(sucesso, resposta)``.  ``sucesso`` é ``True`` se a
        mensagem foi enviada (código de retorno 200 ou 201).  ``resposta``
        contém o JSON retornado pela API em caso de sucesso.
    """
    token = get_access_token()
    if not token:
        logger.error("Não há token disponível para enviar mensagem para a conversa %s.", conversation_id)
        return False, None
    url = f"{API_BASE_URL}/conversations/{conversation_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Version": API_VERSION,
        "Accept": "application/json",
    }
    payload: Dict[str, Any] = {
        "type": message_type,
        "message": message_text,
    }
    if reply_message_id:
        payload["replyMessageId"] = reply_message_id
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code in (200, 201):
            return True, response.json()
        logger.error(
            "Falha ao enviar mensagem para conversa %s: %s - %s",
            conversation_id,
            response.status_code,
            response.text,
        )
        return False, None
    except requests.exceptions.RequestException as exc:
        logger.error("Erro de rede ao enviar mensagem para conversa %s: %s", conversation_id, exc)
    except Exception as exc:
        logger.error("Erro inesperado ao enviar mensagem para conversa %s: %s", conversation_id, exc)
    return False, None


# No futuro, funções para buscar usuários, campos personalizados e atualizar
# tokens podem ser adicionadas aqui.  Atualmente estas tarefas estão
# implementadas nos scripts em ``ia_zoi.scripts`` e são chamadas via
# subprocess.  Mantemos esse módulo enxuto para separar responsabilidades.