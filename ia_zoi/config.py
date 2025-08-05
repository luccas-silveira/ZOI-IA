"""Módulo de configuração.

Este módulo lê variáveis de ambiente e fornece acesso centralizado às configurações do
projeto.  Se existir um arquivo ``.env`` na raiz do projeto ou no diretório atual,
ele será carregado automaticamente via ``python-dotenv``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    # python-dotenv é opcional; se não estiver instalado, a função load_dotenv será uma no-op.
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    def load_dotenv(dotenv_path: Optional[str] = None) -> None:
        """Fallback vazio se python-dotenv não estiver instalado."""
        return None

# Carregar variáveis do arquivo .env, se existir
def _load_env() -> None:
    """Localiza e carrega automaticamente um arquivo `.env`.

    Utiliza ``find_dotenv`` para procurar um arquivo `.env` começando no
    diretório atual e subindo na hierarquia. Se encontrado, carrega as
    variáveis de ambiente usando ``load_dotenv``. Caso contrário, nenhuma
    variável extra é carregada. Isso torna o pacote robusto a diferentes
    diretórios de execução.
    """
    try:
        # ``find_dotenv`` retorna o caminho do primeiro `.env` encontrado
        from dotenv import find_dotenv  # type: ignore

        found = find_dotenv() or None
        env_path = Path(found) if found else None
    except Exception:
        env_path = None
    if env_path and env_path.exists():
        load_dotenv(dotenv_path=str(env_path))


# Carregar as variáveis assim que o módulo é importado
_load_env()


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


# GoHighLevel credentials
GHL_CLIENT_ID: Optional[str] = _env("GHL_CLIENT_ID")
GHL_CLIENT_SECRET: Optional[str] = _env("GHL_CLIENT_SECRET")
GHL_AUTH_CODE: Optional[str] = _env("GHL_AUTH_CODE")
GHL_USER_TYPE: str = _env("GHL_USER_TYPE", "Company")

# OpenAI credentials
OPENAI_API_KEY: Optional[str] = _env("OPENAI_API_KEY")
OPENAI_API_BASE: str = _env("OPENAI_API_BASE", "https://api.openai.com/v1")

# Flask settings
FLASK_HOST: str = _env("FLASK_HOST", "0.0.0.0")
FLASK_PORT: int = int(_env("FLASK_PORT", "5050"))
FLASK_DEBUG: bool = _env("FLASK_DEBUG", "True").lower() in ("true", "1", "t")

# Paths for persisted data
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Files used by services
GHL_TOKEN_FILE = DATA_DIR / "gohighlevel_token.json"
CONVERSATION_HISTORY_FILE = DATA_DIR / "conversation_history.json"
TAG_CACHE_FILE = DATA_DIR / "tag_cache.json"
USERS_FILE = DATA_DIR / "users.json"
ASSIGNMENTS_FILE = DATA_DIR / "registros_atribuicoes_contatos.json"
MANAGED_FIELD_DETAILS_FILE = DATA_DIR / "campo_gerenciado_detalhes.json"
INSTALLED_LOCATIONS_FILE = DATA_DIR / "installed_locations_data.json"


def validate_config() -> None:
    """Valida se as configurações essenciais estão presentes.

    Lança uma exceção se alguma variável obrigatória estiver ausente.
    """
    missing = []
    for var_name in ("GHL_CLIENT_ID", "GHL_CLIENT_SECRET", "GHL_AUTH_CODE", "OPENAI_API_KEY"):
        if globals().get(var_name) in (None, ""):
            missing.append(var_name)
    if missing:
        raise RuntimeError(
            f"Variáveis obrigatórias ausentes: {', '.join(missing)}. Configure-as no .env ou no ambiente."
        )
