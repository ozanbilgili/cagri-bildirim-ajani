"""Testler gerçek model sunucusu olmadan çalışır: senaryolu sahte LLM kullanılır."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from bildirim_ajani.config import Ayarlar
from bildirim_ajani.knowledge_base import bilgi_tabani
from bildirim_ajani.llm import AracCagrisi, Kullanim, LLMHatasi, LLMYaniti
from bildirim_ajani.memory import Hafiza
from bildirim_ajani.orchestrator import Orkestrator
from bildirim_ajani.rag import KuralDeposu

ORNEK_TRANSKRIPT = """TEMSİLCİ: Örnek Portföy, ben Selin, nasıl yardımcı olabilirim?
MÜŞTERİ: Merhaba, ben Mehmet Tunç. Kuzey Bank üzerinden ÖRT fonu almıştım, satmaya çalışıyorum ama hata veriyor, satamıyorum.
TEMSİLCİ: Fon Kuzey Bank kanalından alındıysa satış talimatı da oradan verilmeli.
MÜŞTERİ: Bankayı aradım, size yönlendirdiler. Çok mağdur oldum.
TEMSİLCİ: Kaydınızı oluşturuyorum, Kuzey Bank ile görüşüp dönüş yapacağız.
MÜŞTERİ: Tamam, teşekkürler."""

VARSAYILAN_YANITLAR: dict[str, Any] = {
    "plan": {"rota": "tam_analiz", "gerekce": "Müşteri fon satış sorunu bildiriyor.", "fon_analizi_gerekli": True, "kimlik_analizi_gerekli": True, "dikkat_noktalari": ["Kuzey Bank kanalı"]},
    "siniflandirma": {
        "bildirim_turu": {"value": "Şikayet", "confidence": 90, "gerekce": "satamıyorum, mağdur oldum"},
        "bildirimin_konusu": {"value": "Alım/Satım Esasları/Operasyonel Süreç", "confidence": 85, "gerekce": "fon satışı"},
        "muhatap_kurum": {"value": "Diğer Kurumlar", "confidence": 80, "gerekce": "Kuzey Bank kanalı"},
    },
    "fon": {"fon_kodu": {"value": "ORT", "confidence": 95, "gerekce": "ÖRT fonu"}},
    "kimlik": {"bildirim_sahibi": {"value": "Mehmet Tunç", "confidence": 95, "gerekce": "ben Mehmet Tunç"}},
    "ozet": {
        "bildirim_detayi": {
            "value": "Müşteri Mehmet Tunç, Kuzey Bank üzerinden aldığı ORT kodlu fonu satamadığı için şikayette bulunmuştur. "
            "Temsilci satış talimatının Kuzey Bank üzerinden verilmesi gerektiğini belirtmiştir. Müşteri bankanın kendisini "
            "yönlendirdiğini ifade etmiştir. Kayıt oluşturulmuş ve dönüş yapılacağı bildirilmiştir.",
            "confidence": 85,
            "gerekce": "özet",
        }
    },
    "denetci": {"onay": True, "sorunlar": []},
    "roller": None,
}


def ajan_tespit(sistem: str) -> str:
    if "iş planı" in sistem:
        return "plan"
    if "Üç rapor alanını" in sistem:
        return "siniflandirma"
    if "KODLARINI bul" in sistem:
        return "fon"
    if "Bildirim sahibini" in sistem:
        return "kimlik"
    if "Bildirim Detayı' paragrafını" in sistem:
        return "ozet"
    if "DENETLE" in sistem:
        return "denetci"
    if "numaralı segmentlerini" in sistem:
        return "roller"
    return "rapor"


@dataclass
class SahteLLM:
    """Sistem mesajından hangi ajanın çağırdığını anlayıp senaryolu yanıt döndürür."""

    yanitlar: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(VARSAYILAN_YANITLAR)))
    hata_verecek: set[str] = field(default_factory=set)
    fon_araci_kullan: bool = True
    cagrilar: list[str] = field(default_factory=list)
    kullanim: Kullanim = field(default_factory=Kullanim)
    ozel: dict[str, Callable[[list[dict[str, Any]]], Any]] = field(default_factory=dict)
    ayarlar: Ayarlar = field(default_factory=Ayarlar)

    @property
    def model(self) -> str:
        return "sahte-model"

    def sohbet(self, mesajlar, araclar=None, json_modu=False, sicaklik=None) -> LLMYaniti:
        ajan = ajan_tespit(mesajlar[0]["content"])
        self.cagrilar.append(ajan)
        if ajan in self.hata_verecek:
            raise LLMHatasi(f"{ajan} için sahte hata")
        if ajan == "fon" and araclar and self.fon_araci_kullan and not any(m["role"] == "tool" for m in mesajlar):
            yanit = LLMYaniti("", [AracCagrisi("c1", "transkriptte_kod_tara", {}, "{}")])
        elif ajan in self.ozel:
            yanit = LLMYaniti(json.dumps(self.ozel[ajan](mesajlar), ensure_ascii=False), [])
        else:
            yanit = LLMYaniti(json.dumps(self.yanitlar.get(ajan) or {}, ensure_ascii=False), [])
        self.kullanim.ekle(yanit)
        return yanit

    def json_iste(self, mesajlar, sicaklik=None) -> dict[str, Any]:
        return json.loads(self.sohbet(mesajlar, json_modu=True).icerik)

    def embed(self, metinler):
        raise ConnectionError("embedding sunucusu yok")


@pytest.fixture
def bilgi():
    return bilgi_tabani()


@pytest.fixture
def hafiza(tmp_path: Path) -> Hafiza:
    return Hafiza(tmp_path / "hafiza.db")


@pytest.fixture
def sahte_llm() -> SahteLLM:
    return SahteLLM()


@pytest.fixture
def orkestrator(sahte_llm, bilgi, hafiza, tmp_path) -> Orkestrator:
    ayarlar = Ayarlar(veri_dizini=tmp_path, hafiza_db=tmp_path / "hafiza.db")
    kurallar = KuralDeposu(bilgi, None)
    return Orkestrator(llm=sahte_llm, ayarlar=ayarlar, bilgi=bilgi, hafiza=hafiza, kural_deposu=kurallar)
