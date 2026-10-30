"""Uygulama ayarları. Tüm değerler ortam değişkeninden (.env) okunur; kodda gizli bilgi tutulmaz."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJE_KOKU = Path(__file__).resolve().parent.parent
BILGI_DIZINI = Path(__file__).resolve().parent / "knowledge"

load_dotenv(PROJE_KOKU / ".env")


def _env(ad: str, varsayilan: str = "") -> str:
    return os.getenv(ad, varsayilan).strip()


def _env_int(ad: str, varsayilan: int) -> int:
    try:
        return int(_env(ad, str(varsayilan)))
    except ValueError:
        return varsayilan


def _env_float(ad: str, varsayilan: float) -> float:
    try:
        return float(_env(ad, str(varsayilan)))
    except ValueError:
        return varsayilan


@dataclass(frozen=True)
class Ayarlar:
    """Çalışma zamanı ayarları."""

    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "yerel"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemma4:26b"))
    llm_reasoning_effort: str = field(default_factory=lambda: _env("LLM_REASONING_EFFORT", "none"))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.1))
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 180))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))

    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "bge-m3"))
    embedding_base_url: str = field(default_factory=lambda: _env("EMBEDDING_BASE_URL", ""))

    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))

    veri_dizini: Path = field(default_factory=lambda: PROJE_KOKU / _env("VERI_DIZINI", "data"))
    hafiza_db: Path = field(default_factory=lambda: PROJE_KOKU / _env("HAFIZA_DB", "data/hafiza.db"))

    max_ajan_adimi: int = field(default_factory=lambda: _env_int("MAX_AJAN_ADIMI", 5))
    max_revizyon: int = field(default_factory=lambda: _env_int("MAX_REVIZYON", 1))
    dusuk_guven_esigi: int = field(default_factory=lambda: _env_int("DUSUK_GUVEN_ESIGI", 60))

    @property
    def embedding_url(self) -> str:
        return self.embedding_base_url or self.llm_base_url


def ayarlari_yukle() -> Ayarlar:
    """Ortamdan güncel ayarları döndürür."""
    return Ayarlar()
