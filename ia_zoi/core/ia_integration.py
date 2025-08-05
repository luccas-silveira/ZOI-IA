"""Integração de alto nível entre webhooks e camada de IA.

Este módulo orquestra as etapas necessárias para responder mensagens
entrantes utilizando a IA.  Ele delega tarefas específicas para outros
componentes: registra mensagens no histórico, verifica se a IA está
ativa através das tags do contato, obtém contexto da conversa e
processa o texto com o ``IAProcessor``.  Finalmente, envia a resposta
de volta ao GoHighLevel e atualiza o histórico de forma
síncrona.

Ao manter essa lógica de integração em um único lugar, a aplicação
torna‑se mais fácil de manter e estender.  Novos tipos de eventos
poderão ser suportados adicionando ramos extras no método
``handle_webhook``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .ia_processor import IAProcessor
from .conversation import conversation_history
from .tag_checker import tag_checker
from ..services import ghl_api

logger = logging.getLogger(__name__)


class IAIntegration:
    """Classe de integração que coordena o uso da IA em webhooks."""

    def __init__(self, processor: Optional[IAProcessor] = None) -> None:
        self.processor = processor or IAProcessor()

    def process_inbound_message(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Processa uma mensagem recebida e gera uma resposta da IA.

        Este método extrai os campos necessários do webhook, registra a
        mensagem no histórico, verifica se a IA está ativada para o
        contato e, se positivo, obtém contexto e chama o processador de
        IA.  Se algum passo falhar, ``None`` é retornado.

        Args:
            webhook_data: dicionário com os dados do webhook

        Returns:
            Texto de resposta da IA ou ``None``.
        """
        try:
            contact_id = webhook_data.get("contactId")
            conversation_id = webhook_data.get("conversationId")
            message_body = webhook_data.get("body", "")
            message_id = webhook_data.get("messageId")
            message_type = webhook_data.get("messageType", "SMS")
            if not all([contact_id, conversation_id, message_body]):
                logger.warning(
                    "Dados insuficientes no webhook: contactId=%s, conversationId=%s, body length=%d",
                    contact_id,
                    conversation_id,
                    len(message_body) if message_body else 0,
                )
                return None
            # Registrar mensagem recebida no histórico
            conversation_history.add_message(
                conversation_id=conversation_id,
                contact_id=contact_id,
                message_id=message_id,
                content=message_body,
                direction="inbound",
                message_type=message_type,
            )
            # Verificar se IA está ativa
            if not tag_checker.check_ai_tag(contact_id):
                logger.info("IA não está ativa para contato %s.", contact_id)
                return None
            # Marcar IA como ativa para a conversa
            conversation_history.set_ai_active(conversation_id, True)
            # Obter contexto recente (últimas 10 mensagens)
            context = conversation_history.get_conversation_history(conversation_id, limit=10)
            # Processar mensagem com IA e validar a resposta
            ai_raw = self.processor.process_message(message_body, context)
            if ai_raw and self.processor.validate_response(ai_raw):
                logger.info("IA gerou resposta para conversa %s.", conversation_id)
                return ai_raw
            # Caso a IA não gere resposta válida, usar fallback
            logger.warning("IA não gerou resposta válida para conversa %s, usando fallback.", conversation_id)
            return self.processor.get_fallback_response()
        except Exception as exc:
            logger.error("Erro ao processar mensagem com IA: %s", exc)
            return None

    def send_response_to_ghl(
        self,
        conversation_id: str,
        contact_id: str,
        response_text: str,
        reply_message_id: Optional[str] = None,
        message_type: str = "SMS",
    ) -> bool:
        """Envia a resposta gerada pela IA de volta ao GoHighLevel.

        Esta função utiliza o serviço ``ghl_api.send_message`` e em
        seguida registra a mensagem de saída no histórico.  Retorna
        ``True`` em caso de sucesso, ``False`` em falha.
        """
        try:
            success, response_data = ghl_api.send_message(
                conversation_id,
                response_text,
                reply_message_id=reply_message_id,
                message_type=message_type,
            )
            if success:
                # Determinar ID da mensagem retornada ou usar timestamp
                message_id = None
                if isinstance(response_data, dict):
                    message_id = response_data.get("messageId") or response_data.get("id")
                if not message_id:
                    import time as _time
                    message_id = f"ai_response_{int(_time.time())}"
                conversation_history.add_message(
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    message_id=message_id,
                    content=response_text,
                    direction="outbound",
                    message_type=message_type,
                )
                logger.info(
                    "Resposta enviada com sucesso para conversa %s (ID da mensagem: %s).",
                    conversation_id,
                    message_id,
                )
                return True
            logger.error(
                "Falha ao enviar resposta para conversa %s. Ver detalhes no log de serviço.",
                conversation_id,
            )
            return False
        except Exception as exc:
            logger.error("Erro ao enviar resposta para conversa %s: %s", conversation_id, exc)
            return False

    def handle_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Manipula diferentes tipos de eventos recebidos pelo webhook.

        Atualmente suporta apenas o tipo ``InboundMessage``.  Outros tipos
        de eventos serão retornados com status ``ignored``.

        Args:
            webhook_data: dicionário contendo o payload do webhook.

        Returns:
            Dicionário descrevendo o resultado do processamento.
        """
        try:
            event_type = webhook_data.get("type")
            if event_type == "InboundMessage":
                ai_response = self.process_inbound_message(webhook_data)
                if ai_response:
                    conversation_id = webhook_data.get("conversationId")
                    contact_id = webhook_data.get("contactId")
                    reply_message_id = webhook_data.get("messageId")
                    sent = self.send_response_to_ghl(
                        conversation_id=conversation_id,
                        contact_id=contact_id,
                        response_text=ai_response,
                        reply_message_id=reply_message_id,
                    )
                    return {
                        "status": "success" if sent else "error",
                        "message": "IA processou e respondeu" if sent else "Erro ao enviar resposta",
                        "ai_response": ai_response,
                        "sent": sent,
                    }
                return {
                    "status": "ignored",
                    "message": "IA não ativa ou não gerou resposta",
                    "ai_response": None,
                    "sent": False,
                }
            # Outros tipos de evento podem ser tratados aqui
            return {
                "status": "ignored",
                "message": f"Tipo de webhook não suportado: {event_type}",
                "ai_response": None,
                "sent": False,
            }
        except Exception as exc:
            logger.error("Erro no handler de webhook: %s", exc)
            return {
                "status": "error",
                "message": f"Erro interno: {str(exc)}",
                "ai_response": None,
                "sent": False,
            }


# Instância global de integração para reutilização
ia_integration = IAIntegration()


def handle_ghl_webhook(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """Função utilitária para processar um webhook usando a instância global."""
    return ia_integration.handle_webhook(webhook_data)