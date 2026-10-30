"""Ajanlardan önce çalışan deterministik ön işleme: dosya adı ayrıştırma, kişisel veri
maskeleme, konuşma tanıma (ASR) düzeltmeleri ve transkript ölçümleri."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .knowledge_base import BilgiTabani, ascii_katla
from .schemas import CagriMeta

_TELEFON = re.compile(r"(?<!\d)(?:\+?90[\s-]?)?0?\s?[2-58]\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")
_TCKN = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_IBAN = re.compile(r"\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE)
_EPOSTA = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

_ROL_KALIPLARI = [
    (re.compile(r"^\s*(?:SPK0|SPEAKER_00|TEMS[İI]LC[İI]|Temsilci|MT)\s*:", re.IGNORECASE | re.MULTILINE), "TEMSİLCİ:"),
    (re.compile(r"^\s*(?:SPK1|SPEAKER_01|M[ÜU][ŞS]TER[İI]|Müşteri|Arayan)\s*:", re.IGNORECASE | re.MULTILINE), "MÜŞTERİ:"),
]


def kisisel_veri_maskele(metin: str) -> tuple[str, dict[str, int]]:
    """Telefon, TCKN, IBAN ve e-postayı etiketle değiştirir; kaç adet maskelendiğini döndürür."""
    sayac: dict[str, int] = {}

    def degistir(kalip: re.Pattern[str], etiket: str, kaynak: str) -> str:
        yeni, adet = kalip.subn(etiket, kaynak)
        if adet:
            sayac[etiket] = sayac.get(etiket, 0) + adet
        return yeni

    metin = degistir(_IBAN, "[IBAN]", metin)
    metin = degistir(_EPOSTA, "[E-POSTA]", metin)
    metin = degistir(_TCKN, "[TCKN]", metin)
    metin = degistir(_TELEFON, "[TELEFON]", metin)
    return metin, sayac


def asr_duzelt(metin: str, bilgi: BilgiTabani) -> tuple[str, list[str]]:
    """Kurumun ASR düzeltme sözlüğünü ve Ö/O kod düzeltmesini uygular."""
    uygulananlar: list[str] = []
    for yanlis, dogru in bilgi.kurum.get("asr_duzeltmeleri", {}).items():
        kalip = re.compile(rf"(?<![\wçğıöşü]){re.escape(yanlis)}(?![\wçğıöşü])")
        if kalip.search(metin):
            metin = kalip.sub(dogru, metin)
            uygulananlar.append(f"{yanlis} → {dogru}")

    def kod_duzelt(eslesme: re.Match[str]) -> str:
        ham = eslesme.group(0)
        kod = bilgi.kod_normalize(ham)
        if kod and kod != ham:
            uygulananlar.append(f"{ham} → {kod}")
            return kod
        return ham

    # Sadece büyük harfle yazılmış, Türkçe harf içeren 3 karakterlik kodlar (ÖRT, ÖP1) düzeltilir
    metin = re.sub(r"(?<![\wçğıöşü])[ÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9]{2}(?![\wçğıöşü])", kod_duzelt, metin)
    return metin, uygulananlar


def rolleri_normalize(metin: str) -> str:
    """Farklı konuşmacı etiketlerini TEMSİLCİ:/MÜŞTERİ: biçimine getirir."""
    for kalip, etiket in _ROL_KALIPLARI:
        metin = kalip.sub(etiket, metin)
    satirlar = [re.sub(r"[ \t]+", " ", s).strip() for s in metin.splitlines()]
    return "\n".join(s for s in satirlar if s)


def transkript_olcumu(metin: str) -> dict[str, Any]:
    """Planlayıcının hızlı karar vermesi için transkript istatistikleri."""
    satirlar = [s for s in metin.splitlines() if s.strip()]
    musteri = [s for s in satirlar if s.startswith("MÜŞTERİ:")]
    temsilci = [s for s in satirlar if s.startswith("TEMSİLCİ:")]
    kelime = len(re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", metin))
    musteri_kelime = sum(len(re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", s.split(":", 1)[-1])) for s in musteri)
    return {
        "kelime": kelime,
        "replik": len(satirlar),
        "musteri_replik": len(musteri),
        "temsilci_replik": len(temsilci),
        "musteri_kelime": musteri_kelime,
        "roller_belli": bool(musteri or temsilci),
    }


def dosya_adini_coz(dosya_adi: str, bilgi: BilgiTabani) -> CagriMeta:
    """`YY.AA.GG_SSDDss_SIRA_AD_SOYAD_ARAYAN_HAT_...` kalıbındaki kayıt adını ayrıştırır.

    Kalıba uymayan adlarda alanlar boş kalır ve uyarı eklenir; analiz yine devam eder.
    """
    meta = CagriMeta(dosya_adi=dosya_adi)
    if not dosya_adi:
        return meta
    parcalar = Path(dosya_adi).stem.split("_")
    if len(parcalar) < 4:
        meta.ayrisma_uyarilari.append("Dosya adı beklenen kalıpta değil; tarih/temsilci/telefon boş bırakıldı.")
        return meta

    try:
        tarih = datetime.strptime(parcalar[0], "%y.%m.%d")
        meta.tarih = tarih.strftime("%Y-%m-%d")
    except ValueError:
        meta.ayrisma_uyarilari.append(f"Tarih okunamadı: {parcalar[0]}")
    if re.fullmatch(r"\d{6}", parcalar[1]):
        meta.saat = f"{parcalar[1][:2]}:{parcalar[1][2:4]}:{parcalar[1][4:]}"

    ad_parcalari: list[str] = []
    numaralar: list[str] = []
    for parca in parcalar[3:]:
        if re.fullmatch(r"\d{7,15}", parca):
            numaralar.append(parca)
        elif not numaralar and re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", parca):
            ad_parcalari.append(parca)
        elif numaralar:
            break

    if ad_parcalari:
        ham_ad = " ".join(ad_parcalari)
        eslesen = next((t for t in bilgi.temsilciler if ascii_katla(t) == ascii_katla(ham_ad)), None)
        meta.temsilci = eslesen or ham_ad.title()
        if not eslesen:
            meta.ayrisma_uyarilari.append(f"Temsilci listede yok: {ham_ad}")

    # Çağrı merkezinin kendi hattı arayan değildir (yurt dışı numaralar da kabul edilir)
    hat_oneki = bilgi.kurum.get("cagri_merkezi_hatti", "").lstrip("0")[:3] or "850"
    arayanlar = [n for n in numaralar if not n.lstrip("0").startswith(hat_oneki)]
    if arayanlar:
        meta.telefon = arayanlar[0].lstrip("0")
    else:
        meta.ayrisma_uyarilari.append("Arayan numarası dosya adında bulunamadı.")
    return meta


def on_isle(transkript: str, bilgi: BilgiTabani) -> tuple[str, dict[str, Any]]:
    """Transkripti ajanlara hazırlar; yapılan her değişikliği iz için raporlar."""
    metin = rolleri_normalize(transkript)
    metin, maskeler = kisisel_veri_maskele(metin)
    metin, duzeltmeler = asr_duzelt(metin, bilgi)
    return metin, {"maskelenen": maskeler, "asr_duzeltmeleri": duzeltmeler, "olcum": transkript_olcumu(metin)}
