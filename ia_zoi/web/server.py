"""Servidor Flask para recebimento de webhooks do GoHighLevel.

Este módulo inicializa um aplicativo Flask que expõe duas rotas:

* ``/`` – healthcheck que retorna informações básicas sobre o servidor.
* ``/webhook`` – endpoint POST para receber eventos do GoHighLevel.

O servidor também configura um agendador (APScheduler) para executar
tarefas periódicas, como a atualização de tokens.  Essa tarefa é
executada somente quando o servidor não está em modo debug, para
evitar execuções duplicadas durante o desenvolvimento.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

from .. import config
from .router import process_webhook, run_script, SCRIPT_REFRESH_TOKENS


logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Cria e configura a aplicação Flask."""
    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health_check() -> Any:
        """Endpoint de verificação de saúde do servidor."""
        return jsonify(
            {
                "status": "ok",
                "message": "Servidor de webhooks em execução.",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            }
        ), 200

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


def run_server() -> None:
    """Inicializa o servidor Flask e o agendador de tarefas."""
    app = create_app()
    scheduler: Optional[BackgroundScheduler] = None
    # Apenas iniciar scheduler em modo não debug para evitar instâncias duplicadas
    if not config.FLASK_DEBUG:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            func=_scheduled_token_update_job,
            trigger="interval",
            hours=3,
            id="job_refresh_tokens",
            replace_existing=True,
        )
        try:
            scheduler.start()
            logger.info(
                "Agendador APScheduler iniciado; tarefa de atualização de tokens configurada a cada 3 horas."
            )
        except Exception as exc:
            logger.error("Erro ao iniciar agendador: %s", exc)
    # Executar o app Flask
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG, use_reloader=config.FLASK_DEBUG)


if __name__ == "__main__":
    run_server()