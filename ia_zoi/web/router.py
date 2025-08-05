"""Roteador estendido para eventos de webhook do GoHighLevel.

Este módulo expande a versão original, adicionando suporte para
atribuição de contatos a partir de campos personalizados em
oportunidades (``OpportunityUpdate``) e integrando um novo
script de agendamento para atualizar a lista de usuários e as opções
do campo de atribuição periodicamente.

Para compatibilidade, os eventos ``InboundMessage`` e ``UserCreate``
continuam funcionando como antes.  Em ``UserCreate``, o roteador
executa `get_users.py` e `update_user_list.py` para garantir que a
lista de opções reflita os novos usuários.

No evento ``ContactUpdate``, o roteador verifica se o campo
personalizado de atribuição (modelo contact) foi modificado e
executa o script de atribuição de contato.  Para eventos
``OpportunityUpdate``, realiza processo semelhante, mas resolve
primeiro o ID do contato associado à oportunidade e invoca
``process_opportunity_assignment.py``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ia_zoi import config
from ia_zoi.core.ia_integration import handle_ghl_webhook

logger = logging.getLogger(__name__)

# Nomes de scripts relativos ao subpacote ``ia_zoi.scripts``.  Caso
# você refatore os scripts para módulos importáveis, basta atualizar
# estas constantes ou ajustar as chamadas em ``run_script``.
SCRIPT_GET_USERS = "get_users.py"
SCRIPT_UPDATE_USER_LIST = "update_user_list.py"
SCRIPT_PROCESS_CONTACT_ASSIGNMENT = "process_contact_assignment.py"
SCRIPT_PROCESS_OPPORTUNITY_ASSIGNMENT = "process_opportunity_assignment.py"
SCRIPT_REFRESH_TOKENS = "refresh_tokens.py"


def _script_path(script_filename: str) -> Path:
    """Resolve o caminho absoluto para um script no pacote scripts."""
    return Path(__file__).resolve().parent.parent / "scripts" / script_filename


def run_script(script_filename: str, args: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Executa um script Python localizado em ``ia_zoi.scripts``.

    Retorna ``(True, '')`` em caso de sucesso ou ``(False, error)`` em caso
    de falha.  Saída padrão e erros do script são logados para
    depuração.
    """
    script_path = _script_path(script_filename)
    command = [sys.executable, str(script_path)]
    if args:
        command.extend(args)
    logger.info("Executando script %s com argumentos %s", script_filename, args or [])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        if result.stdout:
            logger.debug("Saída de %s:\n%s", script_filename, result.stdout.strip())
        if result.stderr:
            # Registrar stderr como warning para destacar eventuais alertas
            logger.warning("Stderr de %s:\n%s", script_filename, result.stderr.strip())
        return True, ""
    except FileNotFoundError:
        msg = f"Script '{script_filename}' não encontrado em {script_path}"
        logger.error(msg)
        return False, msg
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        logger.error("Falha ao executar %s: %s", script_filename, stderr)
        return False, stderr
    except Exception as exc:
        logger.error("Erro inesperado ao executar %s: %s", script_filename, exc)
        return False, str(exc)


def _load_json(path: Path, default: Any = None) -> Any:
    """Carrega um arquivo JSON, retornando um valor padrão em caso de erro."""
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Erro ao carregar JSON de %s: %s", path, exc)
        return default


def _save_json(data: Any, path: Path) -> bool:
    """Salva um objeto como JSON no caminho fornecido."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as exc:
        logger.error("Erro ao salvar JSON em %s: %s", path, exc)
        return False


def _find_user_id_by_name(name: str) -> Optional[str]:
    """Procura o ID de um usuário no arquivo ``users.json`` pelo nome.

    Retorna ``None`` se não encontrar.
    """
    users_data = _load_json(config.USERS_FILE, default={"users": []})
    if not users_data or not isinstance(users_data.get("users"), list):
        return None
    name_normalized = name.strip().lower()
    for user in users_data["users"]:
        if not isinstance(user, dict):
            continue
        user_name = user.get("name", "")
        if not user_name and (user.get("firstName") or user.get("lastName")):
            user_name = f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
        if user_name and user_name.strip().lower() == name_normalized:
            return user.get("id")
    return None


def process_webhook(data: Dict[str, Any]) -> Dict[str, Any]:
    """Processa o payload de um webhook e retorna um resultado estruturado.

    Dependendo do tipo de evento, delega o processamento para
    componentes de IA ou scripts auxiliares.  Eventos suportados:

    * ``InboundMessage``: encaminha para o módulo de IA.
    * ``UserCreate``: sincroniza lista de usuários e atualiza campo.
    * ``ContactUpdate``: verifica campo de atribuição (contact) e
      processa atribuição.
    * ``OpportunityUpdate``: verifica campo de atribuição (opportunity)
      e processa atribuição de contato.
    """
    event_type = data.get("type")
    location_id = data.get("locationId")

    # Processamento de mensagens inbound
    if event_type == "InboundMessage":
        logger.info("Recebido evento InboundMessage; encaminhando para IA.")
        ia_result = handle_ghl_webhook(data)
        return {
            "status": f"Evento '{event_type}' processado com IA",
            "ia_result": ia_result,
        }

    # Criação de usuário: sincroniza lista de usuários e campo personalizado
    if event_type == "UserCreate":
        logger.info("Recebido evento UserCreate; iniciando sincronização de usuários.")
        success_get, err_get = run_script(SCRIPT_GET_USERS)
        if not success_get:
            return {
                "status": f"Falha ao executar {SCRIPT_GET_USERS}",
                "error_detail": err_get,
            }
        success_update, err_update = run_script(SCRIPT_UPDATE_USER_LIST)
        if not success_update:
            return {
                "status": f"Falha ao executar {SCRIPT_UPDATE_USER_LIST}",
                "error_detail": err_update,
            }
        return {"status": f"Evento '{event_type}' processado com sucesso. Usuários sincronizados."}

    # Atualização de contato: verifica se campo de atribuição (contact) foi alterado
    if event_type == "ContactUpdate":
        contact_id = data.get("id")
        custom_fields = data.get("customFields", [])
        if not contact_id or not location_id:
            logger.warning(
                "ContactUpdate recebido com dados incompletos: contactId=%s, locationId=%s",
                contact_id,
                location_id,
            )
            return {"status": "Webhook ContactUpdate com dados incompletos."}
        # Carregar detalhes do campo personalizado gerenciado
        managed_field_info = _load_json(config.MANAGED_FIELD_DETAILS_FILE)
        assigner_field_id: Optional[str] = None
        if managed_field_info and isinstance(managed_field_info.get("managed_custom_field"), dict):
            details = managed_field_info["managed_custom_field"]
            if (
                details.get("model") == "contact"
                and details.get("fieldKey_base_sent") == "transferir_para_o_vendedor"
                and details.get("currentId")
            ):
                assigner_field_id = details.get("currentId")
        if not assigner_field_id:
            logger.warning("ID do campo de atribuição (contact) não encontrado em %s.", config.MANAGED_FIELD_DETAILS_FILE)
            return {"status": "ID do campo de atribuição (contact) não configurado."}
        # Obter valor do campo no payload
        assignee_name: Optional[str] = None
        for cf in custom_fields:
            if cf.get("id") == assigner_field_id:
                assignee_name = cf.get("value")
                break
        if not assignee_name or not assignee_name.strip() or assignee_name.strip().lower() == "selecionar":
            logger.info(
                "Campo de atribuição ausente ou sem valor para contato %s; nenhuma ação.",
                contact_id,
            )
            return {"status": "Sem atribuição a ser feita."}
        logger.info("Solicitação de atribuição para contato %s ao usuário '%s'.", contact_id, assignee_name)
        assignee_user_id = _find_user_id_by_name(assignee_name)
        if not assignee_user_id:
            logger.warning(
                "Usuário '%s' não encontrado em %s.", assignee_name, config.USERS_FILE
            )
            return {"status": f"Usuário '{assignee_name}' não encontrado."}
        # Verificar registro de atribuições para evitar repetição
        assignments_log = _load_json(config.ASSIGNMENTS_FILE, default={})
        last_assignee = assignments_log.get(contact_id)
        if last_assignee == assignee_user_id:
            logger.info(
                "Contato %s já atribuído ao usuário %s; nenhuma ação.",
                contact_id,
                assignee_user_id,
            )
            return {"status": "Atribuição já registrada; nenhuma ação."}
        # Executar script de atribuição de contato
        success_assign, err_assign = run_script(
            SCRIPT_PROCESS_CONTACT_ASSIGNMENT,
            args=[contact_id, location_id, assignee_user_id],
        )
        if success_assign:
            assignments_log[contact_id] = assignee_user_id
            _save_json(assignments_log, config.ASSIGNMENTS_FILE)
            logger.info(
                "Contato %s atribuído a %s e registro atualizado.",
                contact_id,
                assignee_user_id,
            )
            return {"status": "Atribuição realizada com sucesso."}
        return {
            "status": "Falha ao processar atribuição de contato.",
            "error_detail": err_assign,
        }

    # Atualização de oportunidade: verifica se campo de atribuição (opportunity) foi alterado
    if event_type == "OpportunityUpdate":
        opportunity_id = data.get("id") or data.get("opportunityId")
        custom_fields = data.get("customFields", [])
        if not opportunity_id or not location_id:
            logger.warning(
                "OpportunityUpdate recebido com dados incompletos: opportunityId=%s, locationId=%s",
                opportunity_id,
                location_id,
            )
            return {"status": "Webhook OpportunityUpdate com dados incompletos."}
        # Carregar detalhes do campo gerenciado e verificar modelo "opportunity"
        managed_field_info = _load_json(config.MANAGED_FIELD_DETAILS_FILE)
        assigner_field_id: Optional[str] = None
        if managed_field_info and isinstance(managed_field_info.get("managed_custom_field"), dict):
            details = managed_field_info["managed_custom_field"]
            if (
                details.get("model") == "opportunity"
                and details.get("fieldKey_base_sent") == "transferir_para_o_vendedor"
                and details.get("currentId")
            ):
                assigner_field_id = details.get("currentId")
        if not assigner_field_id:
            logger.warning(
                "ID do campo de atribuição (opportunity) não encontrado em %s.", config.MANAGED_FIELD_DETAILS_FILE
            )
            return {"status": "ID do campo de atribuição (opportunity) não configurado."}
        # Obter valor do campo no payload da oportunidade
        assignee_name: Optional[str] = None
        for cf in custom_fields:
            if cf.get("id") == assigner_field_id:
                assignee_name = cf.get("value")
                break
        if not assignee_name or not assignee_name.strip() or assignee_name.strip().lower() == "selecionar":
            logger.info(
                "Campo de atribuição ausente ou sem valor para oportunidade %s; nenhuma ação.",
                opportunity_id,
            )
            return {"status": "Sem atribuição a ser feita."}
        logger.info(
            "Solicitação de atribuição para oportunidade %s ao usuário '%s'.",
            opportunity_id,
            assignee_name,
        )
        assignee_user_id = _find_user_id_by_name(assignee_name)
        if not assignee_user_id:
            logger.warning(
                "Usuário '%s' não encontrado em %s.", assignee_name, config.USERS_FILE
            )
            return {"status": f"Usuário '{assignee_name}' não encontrado."}
        # Verificar registro de atribuições para evitar repetição
        assignments_log = _load_json(config.ASSIGNMENTS_FILE, default={})
        last_assignee = assignments_log.get(opportunity_id)
        if last_assignee == assignee_user_id:
            logger.info(
                "Oportunidade %s já atribuída ao usuário %s; nenhuma ação.",
                opportunity_id,
                assignee_user_id,
            )
            return {"status": "Atribuição já registrada; nenhuma ação."}
        # Executar script de atribuição da oportunidade (atribui contato associado)
        success_assign, err_assign = run_script(
            SCRIPT_PROCESS_OPPORTUNITY_ASSIGNMENT,
            args=[opportunity_id, location_id, assignee_user_id],
        )
        if success_assign:
            assignments_log[opportunity_id] = assignee_user_id
            _save_json(assignments_log, config.ASSIGNMENTS_FILE)
            logger.info(
                "Oportunidade %s atribuída a %s e registro atualizado.",
                opportunity_id,
                assignee_user_id,
            )
            return {"status": "Atribuição realizada com sucesso."}
        return {
            "status": "Falha ao processar atribuição de oportunidade.",
            "error_detail": err_assign,
        }

    # Evento desconhecido
    logger.info("Evento '%s' não suportado.", event_type)
    return {"status": f"Tipo de evento '{event_type}' desconhecido."}