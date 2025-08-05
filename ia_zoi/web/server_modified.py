"""Servidor Flask aprimorado para recepção de webhooks e tarefas agendadas.

Esta versão do servidor inclui, além da atualização periódica de tokens,
um job que sincroniza a lista de usuários e atualiza as opções do
campo personalizado de atribuição.  O intervalo padrão para essa
sincronização é de 2 horas, mas pode ser ajustado via variáveis de
ambiente (``USER_LIST_UPDATE_INTERVAL_HOURS``).

Rotas:
  * ``/`` – healthcheck simples.
  * ``/webhook`` – endpoint POST para receber eventos do GoHighLevel.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

from ia_zoi import config
from ia_zoi.web.router_modified import (
    process_webhook,
    run_script,
    SCRIPT_REFRESH_TOKENS,
    SCRIPT_GET_USERS,
    SCRIPT_UPDATE_USER_LIST,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Cria e configura a aplicação Flask."""
    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health_check() -> Any:
        """Endpoint de verificação de saúde do servidor."""
        return (
            jsonify(
                {
                    "status": "ok",
                    "message": "Servidor de webhooks em execução.",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                }
            ),
            200,
        )

    @app.route("/webhook", methods=["POST"])
    def webhook_receiver() -> Any:
        """Endpoint para receber webhooks do GoHighLevel."""
        try:
            data: Dict[str, Any] = {}
            # Tentar decodificar JSON; caso falhe, tentar form data
            data = request.get_json(silent=True) or {}
            if not data:
                # Se não for JSON, tente form data
                form_data = request.form.to_dict()
                if form_data:
                    data = form_data
            if not data:
                return jsonify({"status": "error", "message": "Nenhum payload válido fornecido"}), 400
            result = process_webhook(data)
            return jsonify(result), 200
        except Exception as exc:
            logger.error("Erro ao processar requisição /webhook: %s", exc)
            return jsonify({"status": "error", "message": str(exc)}), 500

    return app


def _scheduled_token_update_job() -> None:
    """Job agendado para atualizar tokens periodicamente."""
    logger.info("Job agendado: atualização de tokens iniciada.")
    run_script(SCRIPT_REFRESH_TOKENS)


def _scheduled_user_sync_job() -> None:
    """Job agendado para sincronizar usuários e atualizar campo personalizado."""
    logger.info("Job agendado: sincronização de usuários e atualização de campo iniciada.")
    # Ignorar erros individuais; logs já capturam detalhes
    run_script(SCRIPT_GET_USERS)
    run_script(SCRIPT_UPDATE_USER_LIST)


def run_server() -> None:
    """Inicializa o servidor Flask e o agendador de tarefas."""
    app = create_app()
    scheduler: Optional[BackgroundScheduler] = None
    # Iniciar scheduler somente em modo não debug para evitar instâncias duplicadas
    if not config.FLASK_DEBUG:
        scheduler = BackgroundScheduler(daemon=True)
        # Atualização de tokens a cada 3 horas (mantém lógica original)
        scheduler.add_job(
            func=_scheduled_token_update_job,
            trigger="interval",
            hours=3,
            id="job_refresh_tokens",
            replace_existing=True,
        )
        # Atualização de usuários e campo personalizado
        interval_hours_str = os.getenv("USER_LIST_UPDATE_INTERVAL_HOURS", "2")
        try:
            interval_hours = float(interval_hours_str)
        except ValueError:
            interval_hours = 2.0
        scheduler.add_job(
            func=_scheduled_user_sync_job,
            trigger="interval",
            hours=interval_hours,
            id="job_user_sync",
            replace_existing=True,
        )
        try:
            scheduler.start()
            logger.info(
                "Agendador APScheduler iniciado; tarefas configuradas (tokens a cada 3h, usuários a cada %s h).",
                interval_hours_str,
            )
        except Exception as exc:
            logger.error("Erro ao iniciar agendador: %s", exc)
    # Executar o app Flask
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=config.FLASK_DEBUG,
    )


if __name__ == "__main__":
    run_server()