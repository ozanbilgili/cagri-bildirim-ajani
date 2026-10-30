"""Ajanlar arasında taşınan veri yapıları."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RAPOR_ALANLARI = ("bildirim_turu", "bildirimin_konusu", "muhatap_kurum", "fon_kodu", "bildirim_sahibi", "bildirim_detayi")

ALAN_BASLIKLARI = {
    "bildirim_turu": "Bildirim Türü",
    "bildirimin_konusu": "Bildirimin Konusu",
    "muhatap_kurum": "Muhatap Kurum",
    "fon_kodu": "Fon Kodu",
    "bildirim_sahibi": "Bildirim Sahibi",
    "bildirim_detayi": "Bildirim Detayı",
}


class AlanSonucu(BaseModel):
    """Bir rapor alanı için ajan kararı: değer + güven + transkriptten gerekçe."""

    value: str = ""
    confidence: int = Field(default=0, ge=0, le=100)
    gerekce: str = ""
    kaynak: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _guveni_sinirla(cls, deger: Any) -> int:
        try:
            sayi = int(float(deger))
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, sayi))

    @field_validator("gerekce", "kaynak", mode="before")
    @classmethod
    def _metne_cevir(cls, deger: Any) -> str:
        if deger is None:
            return ""
        return deger if isinstance(deger, str) else str(deger)

    @field_validator("value", mode="before")
    @classmethod
    def _degeri_metne_cevir(cls, deger: Any) -> str:
        if deger is None:
            return ""
        if isinstance(deger, list):
            return ", ".join(str(x) for x in deger)
        return str(deger).strip()


class CagriMeta(BaseModel):
    """Ses dosyası adından (veya kullanıcıdan) gelen çağrı bilgileri."""

    tarih: str = ""
    saat: str = ""
    temsilci: str = ""
    telefon: str = ""
    dosya_adi: str = ""
    ayrisma_uyarilari: list[str] = Field(default_factory=list)


class CagriGirdisi(BaseModel):
    transkript: str
    meta: CagriMeta = Field(default_factory=CagriMeta)
    kaynak: Literal["metin", "ses"] = "metin"


IzTuru = Literal["plan", "ajan", "arac", "sonuc", "denetim", "revizyon", "guardrail", "uyari", "hata", "bilgi"]


class IzOlayi(BaseModel):
    """Arayüzde canlı gösterilen ve hafızaya kaydedilen iz kaydı."""

    tur: IzTuru
    ajan: str
    mesaj: str
    veri: dict[str, Any] = Field(default_factory=dict)
    zaman: float = Field(default_factory=time.time)


class Plan(BaseModel):
    """Planlayıcı ajanın çağrı için seçtiği rota."""

    rota: Literal["tam_analiz", "hat_kesildi"] = "tam_analiz"
    gerekce: str = ""
    fon_analizi_gerekli: bool = True
    kimlik_analizi_gerekli: bool = True
    dikkat_noktalari: list[str] = Field(default_factory=list)


class DenetimSorunu(BaseModel):
    alan: str
    aciklama: str
    oneri: str = ""
    kaynak: Literal["kural_motoru", "denetci_ajan"] = "denetci_ajan"


class AnalizSonucu(BaseModel):
    """Bir çağrının uçtan uca analiz çıktısı."""

    cagri_id: str = ""
    satir: dict[str, Any] = Field(default_factory=dict)
    alanlar: dict[str, AlanSonucu] = Field(default_factory=dict)
    plan: Plan = Field(default_factory=Plan)
    sorunlar: list[DenetimSorunu] = Field(default_factory=list)
    iz: list[IzOlayi] = Field(default_factory=list)
    insan_onayi_gerekli: bool = False
    insan_onayi_nedenleri: list[str] = Field(default_factory=list)
    tekrar_arayan: bool = False
    onceki_cagri_sayisi: int = 0
    sure_sn: float = 0.0
    llm_kullanimi: dict[str, Any] = Field(default_factory=dict)
    onbellekten: bool = False
