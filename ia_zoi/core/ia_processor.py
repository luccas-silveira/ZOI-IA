"""Processamento de mensagens utilizando a API da OpenAI.

Esta classe encapsula a lógica de interação com o modelo GPT‑4.1.  Ela carrega uma
configuração padrão ou personalizada a partir de um arquivo JSON e utiliza o
cliente oficial da OpenAI.  Caso não consiga gerar uma resposta válida,
retorna uma resposta de fallback gentil.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover
    # Caso a biblioteca openai não esteja instalada, definimos um stub para evitar erros
    OpenAI = None  # type: ignore

from .. import config

logger = logging.getLogger(__name__)


class IAProcessor:
    def __init__(self, config_file: str = "ia_config.json") -> None:
        """Inicializa o processador de IA.

        Args:
            config_file: caminho para um arquivo JSON que define parâmetros do modelo.
        """
        self.config: Dict = self._load_config(config_file)
        # A chave e a base da API são carregadas de ia_zoi.config
        # Inicializar o cliente da OpenAI apenas se a biblioteca estiver disponível
        if OpenAI is None:
            raise ImportError(
                "A biblioteca 'openai' não está instalada. Instale-a com 'pip install openai' para usar IAProcessor."
            )
        self.client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_API_BASE)

    def _load_config(self, config_file: str) -> Dict:
        """Carrega configurações de IA a partir de ``config_file``.

        Se o arquivo não existir, cria um arquivo com valores padrão.
        """
        default_config = {
            "model": "gpt-4.1-mini",
            "max_tokens": 1000,
            "temperature": 0.7,
            "system_prompt": (
                "Você é um assistente de atendimento ao cliente profissional e prestativo.\n\n"
                "Suas características:\n"
                "- Sempre responda em português brasileiro\n"
                "- Seja cordial, empático e profissional\n"
                "- Forneça respostas claras e objetivas\n"
                "- Se não souber algo, seja honesto sobre isso\n"
                "- Mantenha o foco no atendimento ao cliente\n"
                "- Use um tom amigável mas profissional\n\n"
                "Diretrizes:\n"
                "- Responda apenas questões relacionadas ao atendimento\n"
                "- Não forneça informações pessoais ou confidenciais\n"
                "- Se a pergunta for muito complexa, sugira contato com um humano\n"
                "- Mantenha as respostas concisas mas completas"
            ),
            "max_history_messages": 10,
            "retry_attempts": 3,
            "retry_delay": 1,
        }
        try:
            cfg_path = config.DATA_DIR / config_file
            if cfg_path.exists():
                with cfg_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    default_config.update(loaded)
            else:
                # cria o arquivo com a configuração padrão
                with cfg_path.open("w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                logger.info("Arquivo de configuração IA criado em %s", cfg_path)
        except Exception as e:
            logger.error("Erro ao carregar configuração IA: %s", e)
        return default_config

    def _prepare_messages(self, message: str, conversation_history: Optional[List[Dict]] = None) -> List[Dict]:
        """Prepara a lista de mensagens para envio à API da OpenAI."""
        messages: List[Dict] = [
            {"role": "system", "content": self.config["system_prompt"]},
        ]
        if conversation_history:
            recent_history = conversation_history[-self.config["max_history_messages"] :]
            for hist_msg in recent_history:
                role = "user" if hist_msg.get("direction") == "inbound" else "assistant"
                messages.append({"role": role, "content": hist_msg.get("content", "")})
        messages.append({"role": "user", "content": message})
        return messages

    def _call_openai_with_retry(self, messages: List[Dict]) -> Optional[object]:
        """Envia a requisição para a OpenAI com tentativas de retry exponencial."""
        attempts = self.config.get("retry_attempts", 3)
        delay = self.config.get("retry_delay", 1)
        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.config["model"],
                    messages=messages,
                    max_tokens=self.config["max_tokens"],
                    temperature=self.config["temperature"],
                )
                return response
            except Exception as e:
                logger.warning("Tentativa %d falhou: %s", attempt + 1, e)
                if attempt < attempts - 1:
                    time.sleep(delay * (2 ** attempt))
                else:
                    logger.error("Todas as tentativas de chamada à OpenAI falharam")
        return None

    def validate_response(self, response: str) -> bool:
        """Valida se uma resposta é aceitável para o usuário final."""
        if not response or not response.strip():
            return False
        # Respostas muito longas podem indicar comportamento inesperado
        if len(response) > 2000:
            logger.warning("Resposta da IA muito longa (%d caracteres)", len(response))
        inappropriate_keywords = ["hack", "illegal", "confidencial", "senha", "password"]
        lower = response.lower()
        for kw in inappropriate_keywords:
            if kw in lower:
                logger.warning("Resposta contém palavra inapropriada: %s", kw)
                return False
        return True

    def get_fallback_response(self) -> str:
        """Retorna uma resposta padrão amigável em caso de falha."""
        responses = [
            "Obrigado pela sua mensagem! Em breve um de nossos atendentes entrará em contato com você.",
            "Recebemos sua mensagem e retornaremos o mais breve possível. Obrigado!",
            "Sua mensagem é importante para nós. Um atendente especializado entrará em contato em breve.",
        ]
        index = int(time.time()) % len(responses)
        return responses[index]

    def process_message(self, message: str, conversation_history: Optional[List[Dict]] = None) -> Optional[str]:
        """Processa uma mensagem do usuário e retorna a resposta da IA."""
        try:
            messages = self._prepare_messages(message, conversation_history)
            response = self._call_openai_with_retry(messages)
            if response:
                logger.info("IA processou mensagem com sucesso")
                content: str = response.choices[0].message.content.strip()
                return content
            logger.error("Falha ao obter resposta da OpenAI")
            return None
        except Exception as e:
            logger.error("Erro ao processar mensagem com IA: %s", e)
            return None


def process_message_with_ai(message: str, conversation_history: Optional[List[Dict]] = None) -> str:
    """Função utilitária para processar uma mensagem com IA.

    Retorna uma resposta válida ou um fallback.
    """
    processor = IAProcessor()
    ai_response = processor.process_message(message, conversation_history)
    if ai_response and processor.validate_response(ai_response):
        return ai_response
    logger.warning("Usando resposta de fallback por falha ou resposta inválida")
    return processor.get_fallback_response()
