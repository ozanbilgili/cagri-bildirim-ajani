"""Ajanların çağırabildiği araçlar (function calling).

Her araç JSON şemasıyla modele tanıtılır ve metin (JSON) döndürür. Araç hata verirse
istisna ajana {"hata": ...} olarak geri döner; ajan döngüsü kırılmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .knowledge_base import BilgiTabani
from .memory import Hafiza
from .rag import KuralDeposu
from .schemas import CagriMeta


@dataclass
class AracBaglami:
    """Araçların o anki çağrıya erişimi."""

    bilgi: BilgiTabani
    kurallar: KuralDeposu
    hafiza: Hafiza | None
    transkript: str = ""
    meta: CagriMeta = field(default_factory=CagriMeta)
    cagri_id: str = ""


@dataclass(frozen=True)
class Arac:
    ad: str
    aciklama: str
    parametreler: dict[str, Any]
    fonksiyon: Callable[[AracBaglami, dict[str, Any]], Any]

    def sema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.ad, "description": self.aciklama, "parameters": self.parametreler},
        }


def _fon_ara(b: AracBaglami, a: dict[str, Any]) -> Any:
    sonuc = b.bilgi.fon_ara(str(a.get("sorgu", "")), limit=5)
    return sonuc or {"sonuc": "Sözlükte eşleşen fon yok. Kod uydurma; emin değilsen '-' yaz."}


def _kod_tara(b: AracBaglami, a: dict[str, Any]) -> Any:
    bulunan = b.bilgi.transkriptte_kod_tara(b.transkript)
    for k in bulunan:
        k["ad"] = b.bilgi.kod_fon[k["kod"]]["ad"]
    return bulunan or {"sonuc": "Transkriptte fon bağlamında geçen kod bulunamadı (fon adı geçiyor olabilir; fon_ara ile ada göre ara)."}


def _kural_ara(b: AracBaglami, a: dict[str, Any]) -> Any:
    alan = str(a.get("alan", "")).upper() or "GDKIJLE"
    return json.loads(b.kurallar.ara_json(str(a.get("sorgu", "")), alanlar=alan + "G", k=3))


def _temsilci_mi(b: AracBaglami, a: dict[str, Any]) -> Any:
    resmi = b.bilgi.temsilci_mi(str(a.get("ad", "")))
    return {"temsilci": bool(resmi), "resmi_ad": resmi or "", "not": "Temsilci adı bildirim sahibi olamaz." if resmi else ""}


def _ozel_fon(b: AracBaglami, a: dict[str, Any]) -> Any:
    fon = b.bilgi.ozel_fon_sahibi(str(a.get("soyad", "")))
    return {"eslesme": True, "kod": fon["kod"], "ad": fon["ad"]} if fon else {"eslesme": False}


def _gecmis_duzeltmeler(b: AracBaglami, a: dict[str, Any]) -> Any:
    if b.hafiza is None:
        return {"sonuc": "Hafıza kapalı."}
    alan = a.get("alan")
    sonuc = b.hafiza.benzer_duzeltmeler(b.transkript, (alan,) if alan else None, k=3)
    return sonuc or {"sonuc": "Benzer geçmiş düzeltme yok."}


_ALANLAR = ["D", "K", "I", "J", "L", "E"]

ARACLAR: dict[str, Arac] = {
    a.ad: a
    for a in [
        Arac(
            "fon_ara",
            "Örnek Portföy fon sözlüğünde kod, harf harf okunuş ('o re te') veya fon adıyla arama yapar. Kod yazmadan önce mutlaka doğrula.",
            {"type": "object", "properties": {"sorgu": {"type": "string", "description": "Kod, okunuş veya fon adı"}}, "required": ["sorgu"]},
            _fon_ara,
        ),
        Arac(
            "transkriptte_kod_tara",
            "Transkriptte fon bağlamında geçen geçerli fon kodlarını deterministik olarak bulur (Ö/O ve heceleme düzeltmeli).",
            {"type": "object", "properties": {}},
            _kod_tara,
        ),
        Arac(
            "kural_ara",
            "İş birimi kural kitabında arama yapar. Emin olmadığın bir sınıflandırma için ilgili kuralı getir.",
            {
                "type": "object",
                "properties": {
                    "sorgu": {"type": "string", "description": "Aranan durum, ör. 'başka banka üzerinden fon satamıyor'"},
                    "alan": {"type": "string", "enum": _ALANLAR, "description": "D=tür, K=konu, I=muhatap, J=fon, L=detay, E=sahip"},
                },
                "required": ["sorgu"],
            },
            _kural_ara,
        ),
        Arac(
            "temsilci_mi",
            "Verilen adın çağrı merkezi temsilcisine ait olup olmadığını kontrol eder.",
            {"type": "object", "properties": {"ad": {"type": "string"}}, "required": ["ad"]},
            _temsilci_mi,
        ),
        Arac(
            "ozel_fon_sahibi_kontrol",
            "Arayanın soyadı bir özel fonun sahibiyle eşleşiyor mu kontrol eder (kural J-6).",
            {"type": "object", "properties": {"soyad": {"type": "string"}}, "required": ["soyad"]},
            _ozel_fon,
        ),
        Arac(
            "gecmis_duzeltmeler",
            "İş biriminin benzer çağrılarda daha önce yaptığı düzeltmeleri getirir. Aynı hatayı tekrarlamamak için kullan.",
            {"type": "object", "properties": {"alan": {"type": "string", "description": "İsteğe bağlı rapor alanı adı, ör. 'muhatap_kurum'"}}},
            _gecmis_duzeltmeler,
        ),
    ]
}


class AracKutusu:
    """Bir ajana açılan araç alt kümesi."""

    def __init__(self, baglam: AracBaglami, adlar: list[str]) -> None:
        bilinmeyen = [a for a in adlar if a not in ARACLAR]
        if bilinmeyen:
            raise ValueError(f"Bilinmeyen araç: {bilinmeyen}")
        self.baglam = baglam
        self.araclar = {a: ARACLAR[a] for a in adlar}

    def semalar(self) -> list[dict[str, Any]]:
        return [a.sema() for a in self.araclar.values()]

    def calistir(self, ad: str, argumanlar: dict[str, Any]) -> str:
        """Aracı çalıştırır; her durumda modele gösterilebilir bir JSON metni döndürür."""
        arac = self.araclar.get(ad)
        if arac is None:
            return json.dumps({"hata": f"'{ad}' adlı araç bu ajana açık değil. Kullanılabilir: {list(self.araclar)}"}, ensure_ascii=False)
        if "_ayrisma_hatasi" in argumanlar:
            return json.dumps({"hata": "Argümanlar geçerli JSON değil, tekrar dene."}, ensure_ascii=False)
        eksik = [p for p in arac.parametreler.get("required", []) if not str(argumanlar.get(p, "")).strip()]
        if eksik:
            return json.dumps({"hata": f"Eksik parametre: {eksik}"}, ensure_ascii=False)
        try:
            return json.dumps(arac.fonksiyon(self.baglam, argumanlar), ensure_ascii=False)
        except Exception as hata:  # araç hatası ajana bildirilir, analiz sürer
            return json.dumps({"hata": f"Araç çalışırken hata: {hata}"}, ensure_ascii=False)
