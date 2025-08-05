"""Gerenciamento de histórico de conversas.

O histórico é persistido em um arquivo JSON definido em ``ia_zoi.config.CONVERSATION_HISTORY_FILE``.
Esta implementação utiliza locking para evitar corrupções quando acessada por múltiplas threads.

Recomenda‑se a substituição por um banco de dados em ambientes de produção.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .. import config

logger = logging.getLogger(__name__)


class ConversationHistory:
    """Classe responsável por armazenar e gerenciar conversas.

    Cada conversa é identificada por um ``conversation_id``.  As mensagens são
    armazenadas como dicionários com campos como ``messageId``, ``timestamp``,
    ``direction`` e ``content``.  A estrutura completa é persistida em disco.
    """

    def __init__(self, history_file: Optional[Path] = None, max_age_days: int = 30) -> None:
        self.history_file: Path = history_file or config.CONVERSATION_HISTORY_FILE
        self.max_age_days: int = max_age_days
        self.conversations: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._load_history()
        self._cleanup_old_conversations()

    def _load_history(self) -> None:
        """Carrega o histórico do arquivo JSON, se existir."""
        try:
            if self.history_file.exists():
                with self.history_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversations = data.get("conversations", {})
                logger.info("Histórico carregado: %d conversas", len(self.conversations))
            else:
                logger.info("Arquivo de histórico não existe, iniciando vazio")
        except Exception as e:
            logger.error("Erro ao carregar histórico: %s", e)
            self.conversations = {}

    def _save_history(self) -> None:
        """Salva o histórico no arquivo JSON."""
        try:
            with self._lock:
                data = {
                    "conversations": self.conversations,
                    "last_updated": datetime.now().isoformat(),
                }
                # Fazer backup do arquivo anterior
                if self.history_file.exists():
                    backup_file = self.history_file.with_suffix(".backup")
                    self.history_file.replace(backup_file)
                with self.history_file.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.debug("Histórico salvo com sucesso")
        except Exception as e:
            logger.error("Erro ao salvar histórico: %s", e)

    def add_message(
        self,
        conversation_id: str,
        contact_id: str,
        message_id: str,
        content: str,
        direction: str,
        message_type: str = "SMS",
    ) -> None:
        """Adiciona uma mensagem ao histórico.

        Args:
            conversation_id: ID único da conversa.
            contact_id: ID do contato associado à conversa.
            message_id: ID da mensagem.
            content: Conteúdo textual da mensagem.
            direction: ``'inbound'`` ou ``'outbound'``.
            message_type: Tipo da mensagem (SMS, Email, etc.).
        """
        try:
            with self._lock:
                if conversation_id not in self.conversations:
                    self.conversations[conversation_id] = {
                        "contactId": contact_id,
                        "messages": [],
                        "lastActivity": datetime.now().isoformat(),
                        "aiActive": False,
                        "created": datetime.now().isoformat(),
                    }
                message = {
                    "messageId": message_id,
                    "timestamp": datetime.now().isoformat(),
                    "direction": direction,
                    "content": content,
                    "messageType": message_type,
                }
                self.conversations[conversation_id]["messages"].append(message)
                self.conversations[conversation_id]["lastActivity"] = datetime.now().isoformat()
                # Manter somente as últimas 50 mensagens para limitar tamanho
                max_messages = 50
                if len(self.conversations[conversation_id]["messages"]) > max_messages:
                    self.conversations[conversation_id]["messages"] = self.conversations[conversation_id]["messages"][-max_messages:]
                logger.info("Mensagem adicionada à conversa %s (%s)", conversation_id, direction)
                # Salvar a cada 5 mensagens para reduzir I/O
                if len(self.conversations[conversation_id]["messages"]) % 5 == 0:
                    self._save_history()
        except Exception as e:
            logger.error("Erro ao adicionar mensagem: %s", e)

    def get_conversation_history(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Recupera as últimas ``limit`` mensagens de uma conversa."""
        try:
            if conversation_id not in self.conversations:
                return []
            messages = self.conversations[conversation_id]["messages"]
            return messages[-limit:] if limit > 0 else messages
        except Exception as e:
            logger.error("Erro ao recuperar histórico: %s", e)
            return []

    def set_ai_active(self, conversation_id: str, active: bool) -> None:
        """Define o status de IA ativa para uma conversa."""
        try:
            if conversation_id in self.conversations:
                self.conversations[conversation_id]["aiActive"] = active
                logger.info("IA %s para conversa %s", "ativada" if active else "desativada", conversation_id)
        except Exception as e:
            logger.error("Erro ao definir status da IA: %s", e)

    def is_ai_active(self, conversation_id: str) -> bool:
        """Retorna ``True`` se a IA estiver ativa para a conversa."""
        try:
            return self.conversations.get(conversation_id, {}).get("aiActive", False)
        except Exception as e:
            logger.error("Erro ao verificar status da IA: %s", e)
            return False

    def get_contact_conversations(self, contact_id: str) -> List[str]:
        """Retorna todos os conversation_id associados a um contato."""
        try:
            result: List[str] = []
            for conv_id, conv_data in self.conversations.items():
                if conv_data.get("contactId") == contact_id:
                    result.append(conv_id)
            return result
        except Exception as e:
            logger.error("Erro ao buscar conversas do contato: %s", e)
            return []

    def _cleanup_old_conversations(self) -> None:
        """Remove conversas mais antigas que ``max_age_days``."""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
            cutoff_iso = cutoff_date.isoformat()
            to_remove = [conv_id for conv_id, conv in self.conversations.items() if conv.get("lastActivity", "") < cutoff_iso]
            for conv_id in to_remove:
                del self.conversations[conv_id]
            if to_remove:
                logger.info("Removidas %d conversas antigas", len(to_remove))
                self._save_history()
        except Exception as e:
            logger.error("Erro na limpeza de conversas antigas: %s", e)

    def get_stats(self) -> Dict:
        """Calcula estatísticas básicas do histórico."""
        try:
            total_conversations = len(self.conversations)
            active_ai_conversations = sum(1 for conv in self.conversations.values() if conv.get("aiActive", False))
            total_messages = sum(len(conv.get("messages", [])) for conv in self.conversations.values())
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            active_conversations = sum(1 for conv in self.conversations.values() if conv.get("lastActivity", "") > yesterday)
            file_size_mb = 0.0
            try:
                if self.history_file.exists():
                    size_bytes = self.history_file.stat().st_size
                    file_size_mb = round(size_bytes / (1024 * 1024), 2)
            except Exception:
                pass
            return {
                "total_conversations": total_conversations,
                "active_ai_conversations": active_ai_conversations,
                "total_messages": total_messages,
                "active_conversations_24h": active_conversations,
                "file_size_mb": file_size_mb,
            }
        except Exception as e:
            logger.error("Erro ao calcular estatísticas: %s", e)
            return {}


# Instância global para uso em toda a aplicação
conversation_history = ConversationHistory()


def add_message_to_history(
    conversation_id: str,
    contact_id: str,
    message_id: str,
    content: str,
    direction: str,
    message_type: str = "SMS",
) -> None:
    """Wrapper conveniente para adicionar uma mensagem ao histórico global."""
    conversation_history.add_message(conversation_id, contact_id, message_id, content, direction, message_type)


def get_conversation_context(conversation_id: str, limit: int = 10) -> List[Dict]:
    """Wrapper para recuperar o histórico de uma conversa."""
    return conversation_history.get_conversation_history(conversation_id, limit)


def set_ai_status(conversation_id: str, active: bool) -> None:
    """Wrapper para definir o status da IA em uma conversa."""
    conversation_history.set_ai_active(conversation_id, active)


def check_ai_status(conversation_id: str) -> bool:
    """Wrapper para verificar o status da IA em uma conversa."""
    return conversation_history.is_ai_active(conversation_id)
