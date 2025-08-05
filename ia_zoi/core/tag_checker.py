"""Verificador de tags para ativação de IA.

Este módulo encapsula a lógica de verificação de tags de um contato no
GoHighLevel para determinar se a funcionalidade de IA deve ser
ativada.  Ele faz uso de um cache em disco para reduzir chamadas
repetidas à API e expira entradas após um tempo configurável.

A tag alvo (``target_tag``) é configurável, mas por padrão usa
``"ia/atendimento/ativa"``.  O cache é salvo no caminho indicado por
``config.TAG_CACHE_FILE``.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from .. import config
from ..services import ghl_api

logger = logging.getLogger(__name__)


class TagChecker:
    """Classe responsável por verificar se um contato possui a tag de IA.

    A instância mantém um cache em memória e em disco para
    armazenar o resultado de consultas recentes.  O cache evita
    chamadas repetidas à API do GoHighLevel para o mesmo contato
    dentro de uma janela de tempo.  Se ``force_refresh`` for
    passado, a API será consultada independentemente do estado do
    cache.
    """

    def __init__(
        self,
        cache_file: Path = config.TAG_CACHE_FILE,
        cache_expiry_minutes: int = 30,
        target_tag: str = "ia/atendimento/ativa",
    ) -> None:
        self.cache_file = Path(cache_file)
        self.cache_expiry_minutes = cache_expiry_minutes
        self.tag_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.target_tag = target_tag
        self._load_cache()
        self._cleanup_expired_cache()

    def _load_cache(self) -> None:
        """Carrega o cache do arquivo JSON.

        Se o arquivo não existir ou ocorrer um erro, inicializa o cache
        em branco.  O arquivo utiliza o formato ``{"tagCache": {...}}``
        para permitir a inclusão de metadados no futuro.
        """
        try:
            if self.cache_file.exists():
                with self.cache_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.tag_cache = data.get("tagCache", {}) or {}
                logger.info(
                    "Cache de tags carregado de %s: %d entradas.",
                    self.cache_file,
                    len(self.tag_cache),
                )
            else:
                logger.debug("Arquivo de cache de tags não existe: %s", self.cache_file)
                self.tag_cache = {}
        except Exception as exc:
            logger.error("Erro ao carregar cache de tags de %s: %s", self.cache_file, exc)
            self.tag_cache = {}

    def _save_cache(self) -> None:
        """Salva o cache em disco.

        Protege o acesso com um lock para garantir que o cache não seja
        modificado enquanto está sendo escrito.  Incluir data de
        atualização no arquivo facilita depuração.
        """
        try:
            with self._lock:
                data = {
                    "tagCache": self.tag_cache,
                    "last_updated": datetime.now().isoformat(),
                }
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_file.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.debug("Cache de tags salvo em %s", self.cache_file)
        except Exception as exc:
            logger.error("Erro ao salvar cache de tags em %s: %s", self.cache_file, exc)

    def _cleanup_expired_cache(self) -> None:
        """Remove entradas expiradas do cache.

        Uma entrada é considerada expirada se a diferença entre o horário
        atual e ``lastChecked`` for maior que ``cache_expiry_minutes``.
        Ao remover entradas expiradas, o cache é salvo para persistir
        alterações.
        """
        try:
            cutoff_time = datetime.now() - timedelta(minutes=self.cache_expiry_minutes)
            cutoff_iso = cutoff_time.isoformat()
            expired_contacts = [
                contact_id
                for contact_id, cache_data in self.tag_cache.items()
                if cache_data.get("lastChecked", "") < cutoff_iso
            ]
            if expired_contacts:
                for contact_id in expired_contacts:
                    del self.tag_cache[contact_id]
                logger.info(
                    "Removidas %d entradas expiradas do cache de tags.",
                    len(expired_contacts),
                )
                self._save_cache()
        except Exception as exc:
            logger.error("Erro ao limpar cache de tags expirado: %s", exc)

    def _fetch_contact_data(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """Obtém dados de contato utilizando o serviço de API.

        Se ocorrer qualquer erro durante a chamada, ``None`` será
        retornado e a camada superior poderá optar por usar o cache.
        """
        return ghl_api.get_contact(contact_id)

    def check_ai_tag(self, contact_id: str, force_refresh: bool = False) -> bool:
        """Verifica se a tag de IA está ativa para o contato.

        Primeiro verifica o cache se ``force_refresh`` for falso.  Se a
        entrada estiver no cache e ainda dentro do período de validade,
        retorna o valor armazenado.  Caso contrário, chama a API para
        obter os dados do contato, atualiza o cache e retorna o resultado.

        Args:
            contact_id: ID do contato no GHL.
            force_refresh: se ``True``, ignora o cache e consulta a API.

        Returns:
            ``True`` se a tag de IA estiver presente, ``False`` caso contrário.
        """
        try:
            # Verificar no cache se não forçar refresh
            if not force_refresh and contact_id in self.tag_cache:
                cache_data = self.tag_cache[contact_id]
                last_checked = datetime.fromisoformat(cache_data.get("lastChecked"))
                if datetime.now() - last_checked < timedelta(minutes=self.cache_expiry_minutes):
                    return bool(cache_data.get("aiActive", False))

            # Consultar API
            contact_data = self._fetch_contact_data(contact_id)
            if contact_data is None:
                # Em caso de erro, usar cache se existir
                if contact_id in self.tag_cache:
                    logger.warning(
                        "Usando cache devido a erro na API para contato %s.",
                        contact_id,
                    )
                    return bool(self.tag_cache[contact_id].get("aiActive", False))
                logger.warning(
                    "Sem dados disponíveis para contato %s, assumindo IA inativa.",
                    contact_id,
                )
                return False

            tags = contact_data.get("tags", [])
            ai_active = self.target_tag in tags

            # Atualizar cache
            with self._lock:
                self.tag_cache[contact_id] = {
                    "tags": tags,
                    "lastChecked": datetime.now().isoformat(),
                    "aiActive": ai_active,
                }
            # Salvar cache periodicamente (ex. a cada 10 entradas atualizadas)
            if len(self.tag_cache) % 10 == 0:
                self._save_cache()
            logger.info(
                "Contato %s: IA %s", contact_id, "ativa" if ai_active else "inativa"
            )
            return ai_active
        except Exception as exc:
            logger.error("Erro ao verificar tag do contato %s: %s", contact_id, exc)
            # Em caso de erro, fallback para cache se existir
            if contact_id in self.tag_cache:
                return bool(self.tag_cache[contact_id].get("aiActive", False))
            return False

    def get_contact_tags(self, contact_id: str) -> List[str]:
        """Retorna a lista de tags de um contato.

        Utiliza o cache se disponível e válido, caso contrário consulta a API.
        """
        try:
            if contact_id in self.tag_cache:
                cache_data = self.tag_cache[contact_id]
                last_checked = datetime.fromisoformat(cache_data.get("lastChecked"))
                if datetime.now() - last_checked < timedelta(minutes=self.cache_expiry_minutes):
                    return list(cache_data.get("tags", []))
            contact_data = self._fetch_contact_data(contact_id)
            if contact_data:
                return list(contact_data.get("tags", []))
            return []
        except Exception as exc:
            logger.error("Erro ao obter tags do contato %s: %s", contact_id, exc)
            return []

    def invalidate_cache(self, contact_id: Optional[str] = None) -> None:
        """Remove entradas do cache.

        Se ``contact_id`` for fornecido, remove apenas a entrada desse
        contato.  Caso contrário, limpa todo o cache e salva o arquivo.
        """
        try:
            with self._lock:
                if contact_id:
                    if contact_id in self.tag_cache:
                        del self.tag_cache[contact_id]
                        logger.info(
                            "Cache invalidado para contato %s.", contact_id
                        )
                else:
                    self.tag_cache.clear()
                    logger.info("Todo o cache de tags foi invalidado.")
                self._save_cache()
        except Exception as exc:
            logger.error("Erro ao invalidar cache: %s", exc)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache de tags.

        As estatísticas incluem o número total de entradas, quantas ainda
        são válidas (não expiradas), quantas têm IA ativa e a taxa de
        acerto do cache.
        """
        try:
            total_entries = len(self.tag_cache)
            cutoff_time = datetime.now() - timedelta(minutes=self.cache_expiry_minutes)
            cutoff_iso = cutoff_time.isoformat()
            valid_entries = sum(
                1 for data in self.tag_cache.values() if data.get("lastChecked", "") > cutoff_iso
            )
            active_ai_contacts = sum(
                1 for data in self.tag_cache.values() if data.get("aiActive", False)
            )
            return {
                "total_entries": total_entries,
                "valid_entries": valid_entries,
                "active_ai_contacts": active_ai_contacts,
                "cache_hit_rate": round(valid_entries / max(total_entries, 1) * 100, 2),
                "target_tag": self.target_tag,
            }
        except Exception as exc:
            logger.error("Erro ao calcular estatísticas do cache: %s", exc)
            return {}

    def force_save(self) -> None:
        """Força o salvamento do cache em disco.

        Útil em scripts de manutenção para persistir o estado antes de
        encerrar a aplicação.
        """
        self._save_cache()


# Instância global para facilitar o uso em outras partes da aplicação
tag_checker = TagChecker()


def is_ai_active_for_contact(contact_id: str, force_refresh: bool = False) -> bool:
    """Wrapper que delega a verificação ao ``TagChecker`` global."""
    return tag_checker.check_ai_tag(contact_id, force_refresh)


def get_contact_tags_list(contact_id: str) -> List[str]:
    """Wrapper para obter todas as tags de um contato."""
    return tag_checker.get_contact_tags(contact_id)


def refresh_contact_cache(contact_id: str) -> None:
    """Invalida a entrada de cache de um contato específico."""
    tag_checker.invalidate_cache(contact_id)