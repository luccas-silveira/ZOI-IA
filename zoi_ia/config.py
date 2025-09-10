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
# Recuperação
RAG_K: int = int(os.getenv("RAG_K", "5"))
RAG_MIN_SIM: float = float(os.getenv("RAG_MIN_SIM", "0.3"))
RAG_MAX_SNIPPET_CHARS: int = int(os.getenv("RAG_MAX_SNIPPET_CHARS", "320"))

# Áudio / Transcrição
TRANSCRIBE_AUDIO: bool = _str_to_bool(os.getenv("TRANSCRIBE_AUDIO", "true"))
TRANSCRIPTION_MODEL: str = os.getenv("TRANSCRIPTION_MODEL", "whisper-1")
TRANSCRIBE_HISTORY_ON_LOAD: bool = _str_to_bool(os.getenv("TRANSCRIBE_HISTORY_ON_LOAD", "false"))
AUDIO_MAX_MB: int = int(os.getenv("AUDIO_MAX_MB", "25"))
_AUDIO_WHITELIST_DEFAULT = (
    "audio/mpeg,audio/mp3,audio/mp4,audio/aac,audio/wav,audio/x-wav,"
    "audio/webm,audio/ogg,audio/3gpp,audio/3gpp2"
)
AUDIO_MIME_WHITELIST = set((os.getenv("AUDIO_MIME_WHITELIST", _AUDIO_WHITELIST_DEFAULT) or "").split(","))
_AUDIO_EXTS_DEFAULT = "mp3,mp4,m4a,aac,wav,ogg,oga,webm,3gp,3gpp,3g2,flac,opus,amr,caf"
AUDIO_EXT_WHITELIST = set((os.getenv("AUDIO_EXT_WHITELIST", _AUDIO_EXTS_DEFAULT) or "").split(","))

# Imagem / Visão
DESCRIBE_IMAGES: bool = _str_to_bool(os.getenv("DESCRIBE_IMAGES", "true"))
VISION_MODEL: str = os.getenv("VISION_MODEL", "gpt-4o-mini")
IMAGE_MAX_MB: int = int(os.getenv("IMAGE_MAX_MB", "10"))
_IMAGE_MIME_WHITELIST_DEFAULT = (
    "image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff,image/heic,image/heif"
)
IMAGE_MIME_WHITELIST = set((os.getenv("IMAGE_MIME_WHITELIST", _IMAGE_MIME_WHITELIST_DEFAULT) or "").split(","))
_IMAGE_EXTS_DEFAULT = "jpg,jpeg,png,webp,gif,bmp,tif,tiff,heic,heif"
IMAGE_EXT_WHITELIST = set((os.getenv("IMAGE_EXT_WHITELIST", _IMAGE_EXTS_DEFAULT) or "").split(","))

# Contexto / Resumo
CONTEXT_SUMMARY_THRESHOLD: int = int(os.getenv("CONTEXT_SUMMARY_THRESHOLD", "30"))
CONTEXT_CHUNK_SIZE: int = int(os.getenv("CONTEXT_CHUNK_SIZE", "15"))

# Prompt templating (parametrização)
BRAND_NAME: str = os.getenv("BRAND_NAME", "Nick Multimarcas")
VOICE_TONE: str = os.getenv("VOICE_TONE", "jovem, leve, humano e objetivo")
CHANNEL: str = os.getenv("CHANNEL", "WhatsApp")
SLA_POLICY: str = os.getenv("SLA_POLICY", "responder em até 5 minutos no horário comercial")
LANGUAGES: str = os.getenv("LANGUAGES", "pt-BR")
OUTPUT_STYLE: str = os.getenv(
    "OUTPUT_STYLE",
    "mensagem curta (1–2 frases), 1 pergunta por vez, sem listas a menos que o cliente peça",
)
USE_FEWSHOTS: bool = _str_to_bool(os.getenv("USE_FEWSHOTS", "true"))
PROMPT_FEWSHOTS_PATH: Path = Path(os.getenv("PROMPT_FEWSHOTS_PATH", "prompt_fewshots.json"))

# Logging
LOG_WEBHOOKS: bool = _str_to_bool(os.getenv("LOG_WEBHOOKS", "false"))
