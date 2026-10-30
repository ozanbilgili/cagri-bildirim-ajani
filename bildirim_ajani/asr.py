"""Ses kaydını konuşmacı rolleri işaretlenmiş transkripte çevirir.

1. faster-whisper ile Türkçe konuşma tanıma (opsiyonel bağımlılık: requirements-asr.txt)
2. Rol Ajanı: her segmentin TEMSİLCİ mi MÜŞTERİ mi olduğunu bağlamdan çıkarır
   (ayrı bir konuşmacı ayrıştırma modeli ve erişim anahtarı gerektirmez).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .config import Ayarlar, ayarlari_yukle
from .llm import LLMHatasi, LLMIstemci
from .schemas import IzOlayi


class AsrHatasi(RuntimeError):
    """Ses çözümlenemediğinde fırlatılır."""


@dataclass
class Segment:
    bas: float
    son: float
    metin: str


def asr_kullanilabilir() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=2)
def _model(boyut: str, cihaz: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(boyut, device=cihaz, compute_type="int8")


def transkribe(yol: Path, ayarlar: Ayarlar | None = None) -> list[Segment]:
    """Ses dosyasını Türkçe metin segmentlerine çevirir."""
    ayarlar = ayarlar or ayarlari_yukle()
    if not asr_kullanilabilir():
        raise AsrHatasi("Konuşma tanıma paketi kurulu değil: pip install -r requirements-asr.txt")
    if not yol.exists() or yol.stat().st_size == 0:
        raise AsrHatasi(f"Ses dosyası bulunamadı veya boş: {yol.name}")
    try:
        model = _model(ayarlar.whisper_model, ayarlar.whisper_device)
        segmentler, _ = model.transcribe(str(yol), language="tr", vad_filter=True, beam_size=5)
        return [Segment(s.start, s.end, s.text.strip()) for s in segmentler if s.text.strip()]
    except Exception as hata:
        raise AsrHatasi(f"Ses çözümlenemedi: {hata}") from hata


def _sezgisel_roller(segmentler: list[Segment]) -> list[str]:
    """Model kullanılamazsa: ilk konuşan temsilci kabul edilir, belirgin duraksamada konuşmacı değişir."""
    roller, rol = [], "TEMSİLCİ"
    for i, s in enumerate(segmentler):
        if i and s.bas - segmentler[i - 1].son > 0.35:
            rol = "MÜŞTERİ" if rol == "TEMSİLCİ" else "TEMSİLCİ"
        roller.append(rol)
    return roller


def rolleri_ata(segmentler: list[Segment], llm: LLMIstemci) -> tuple[list[str], str]:
    """Rol Ajanı: segmentleri TEMSİLCİ/MÜŞTERİ olarak etiketler. (roller, yöntem) döndürür."""
    numarali = "\n".join(f"{i}: {s.metin}" for i, s in enumerate(segmentler))
    mesajlar = [
        {
            "role": "system",
            "content": "Bir portföy şirketi çağrı merkezine gelen telefon görüşmesinin numaralı segmentlerini alıyorsun. "
            "Her segmenti konuşan kişiye göre etiketle: çağrıyı karşılayan şirket çalışanı 'TEMSİLCİ', arayan kişi 'MÜŞTERİ'. "
            "Selamlayıp şirket adını söyleyen ve bilgi veren genellikle temsilcidir; sorun anlatan ve soru soran müşteridir. "
            'Çıktı: {"roller": ["TEMSİLCİ", "MÜŞTERİ", ...]} — segment sayısı kadar eleman.',
        },
        {"role": "user", "content": numarali},
    ]
    try:
        cevap = llm.json_iste(mesajlar, sicaklik=0)
        roller = [("MÜŞTERİ" if "M" in str(r).upper()[:2] else "TEMSİLCİ") for r in cevap.get("roller", [])]
        if len(roller) == len(segmentler):
            return roller, "rol_ajani"
    except (LLMHatasi, ValueError):
        pass
    return _sezgisel_roller(segmentler), "sezgisel"


def segmentleri_birlestir(segmentler: list[Segment], roller: list[str]) -> str:
    """Aynı konuşmacının ardışık segmentlerini tek replikte birleştirir."""
    satirlar: list[str] = []
    onceki = ""
    for s, rol in zip(segmentler, roller):
        if rol == onceki and satirlar:
            satirlar[-1] += " " + s.metin
        else:
            satirlar.append(f"{rol}: {s.metin}")
        onceki = rol
    return "\n".join(satirlar)


def sesi_transkripte_cevir(
    yol: Path, llm: LLMIstemci, dinleyici: Callable[[IzOlayi], None] | None = None, ayarlar: Ayarlar | None = None
) -> str:
    """Ses → segmentler → roller → transkript. Her adımı iz olarak bildirir."""
    bildir = dinleyici or (lambda e: None)
    baslangic = time.perf_counter()
    bildir(IzOlayi(tur="ajan", ajan="Konuşma Tanıma", mesaj=f"{yol.name} çözümleniyor (Whisper)"))
    segmentler = transkribe(yol, ayarlar)
    if not segmentler:
        raise AsrHatasi("Kayıtta konuşma algılanmadı.")
    bildir(IzOlayi(tur="sonuc", ajan="Konuşma Tanıma", mesaj=f"{len(segmentler)} segment, {time.perf_counter() - baslangic:.1f} sn"))
    roller, yontem = rolleri_ata(segmentler, llm)
    bildir(IzOlayi(tur="sonuc", ajan="Rol Ajanı", mesaj=f"Konuşmacı rolleri atandı ({yontem})"))
    return segmentleri_birlestir(segmentler, roller)
