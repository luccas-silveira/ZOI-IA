import os
from pathlib import Path


def _str_to_bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# =========================
# Configurações principais
# =========================
TAG_NAME: str = os.getenv("TAG_NAME", "ia - teste")
PORT: int = int(os.getenv("PORT", "8081"))

# Caminhos
STORE_PATH: Path = Path(os.getenv("STORE_PATH", "data/tag_ia_atendimento_ativa.json"))
MESSAGES_DIR: Path = Path(os.getenv("MESSAGES_DIR", "data/messages"))
LOCATION_TOKEN_PATH: Path = Path(os.getenv("LOCATION_TOKEN_PATH", "data/location_token.json"))
EMBEDDINGS_DIR: Path = Path(os.getenv("EMBEDDINGS_DIR", "data/embeddings"))

# Assinatura de webhooks
VERIFY_SIGNATURE: bool = _str_to_bool(os.getenv("VERIFY_SIGNATURE", "true"))

_PUBLIC_KEY_ENV = os.getenv("WEBHOOK_PUBLIC_KEY_PEM")
if _PUBLIC_KEY_ENV:
    PUBLIC_KEY_PEM: bytes = _PUBLIC_KEY_ENV.encode("utf-8")
else:
    PUBLIC_KEY_PEM: bytes = b"""-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAokvo/r9tVgcfZ5DysOSC
Frm602qYV0MaAiNnX9O8KxMbiyRKWeL9JpCpVpt4XHIcBOK4u3cLSqJGOLaPuXw6
dO0t6Q/ZVdAV5Phz+ZtzPL16iCGeK9po6D6JHBpbi989mmzMryUnQJezlYJ3DVfB
csedpinheNnyYeFXolrJvcsjDtfAeRx5ByHQmTnSdFUzuAnC9/GepgLT9SM4nCpv
uxmZMxrJt5Rw+VUaQ9B8JSvbMPpez4peKaJPZHBbU3OdeCVx5klVXXZQGNHOs8gF
3kvoV5rTnXV0IknLBXlcKKAQLZcY/Q9rG6Ifi9c+5vqlvHPCUJFT5XUGG5RKgOKU
J062fRtN+rLYZUV+BjafxQauvC8wSWeYja63VSUruvmNj8xkx2zE/Juc+yjLjTXp
IocmaiFeAO6fUtNjDeFVkhf5LNb59vECyrHD2SQIrhgXpO4Q3dVNA5rw576PwTzN
h/AMfHKIjE4xQA1SZuYJmNnmVZLIZBlQAF9Ntd03rfadZ+yDiOXCCs9FkHibELhC
HULgCsnuDJHcrGNd5/Ddm5hxGQ0ASitgHeMZ0kcIOwKDOzOU53lDza6/Y09T7sYJ
PQe7z0cvj7aE4B+Ax1ZoZGPzpJlZtGXCsu9aTEGEnKzmsFqwcSsnw3JB31IGKAyk
T1hhTiaCeIY/OwwwNUY2yvcCAwEAAQ==
-----END PUBLIC KEY-----"""

# GoHighLevel / LeadConnector
GHL_API_URL: str = os.getenv("GHL_API_URL", "https://services.leadconnectorhq.com")
GHL_MESSAGES_LIST_VERSION: str = os.getenv("GHL_MESSAGES_LIST_VERSION", "2021-04-15")
GHL_MESSAGES_WRITE_VERSION: str = os.getenv("GHL_MESSAGES_WRITE_VERSION", "2021-07-28")

# HTTP client behavior
HTTP_TIMEOUT: float = float(os.getenv("HTTP_TIMEOUT", "10"))
HTTP_MAX_RETRIES: int = int(os.getenv("HTTP_MAX_RETRIES", "3"))
HTTP_BACKOFF_BASE: float = float(os.getenv("HTTP_BACKOFF_BASE", "0.5"))

# RAG / Embeddings
RAG_ENABLED: bool = _str_to_bool(os.getenv("RAG_ENABLED", "true"))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

