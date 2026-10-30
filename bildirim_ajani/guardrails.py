"""Deterministik kural motoru (guardrail).

LLM kararlarını iki şekilde denetler:
- Güvenle düzeltilebilen hataları kendisi düzeltir (enum dışı değer, sözlük dışı fon kodu,
  temsilci adının bildirim sahibi yazılması, detayda kişisel veri).
- Yoruma açık tutarsızlıkları DenetimSorunu olarak Denetçi Ajan'a ve revizyon döngüsüne iletir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .knowledge_base import BilgiTabani, ascii_katla
from .preprocess import kisisel_veri_maskele
from .schemas import AlanSonucu, DenetimSorunu

_SIKAYET_SINYALI = re.compile(
    r"şikayet|memnun değil|memnuniyetsiz|rahatsız|mağdur|haksızlık|zarar|kaybett|eridi|"
    r"çalışmıyor|açılmıyor|hata veriyor|donuyor|satamıyorum|alamıyorum|yapamıyorum|ulaşamıyorum|"
    r"kimse dönmedi|dönüş yapılmadı|cevap alamadım|yanıltıcı|kandır|dolandır|sahte|"
    r"rezalet|kabul edilemez|berbat|bıktım|sinir",
    re.IGNORECASE,
)
_BANKA_ISARETI = re.compile(r"örnek ?bank|örnekcep|bankanız|banka şubesi|şubeye|şubeden", re.IGNORECASE)
_UYGULAMA_ISARETI = re.compile(r"örnek fon mobil|mobil uygulama|uygulama|mobil", re.IGNORECASE)
_HITAPLAR = re.compile(r"\b(Sayın|Bey|Hanım|Müşteri|Bayan|Bay)\b", re.IGNORECASE)


@dataclass
class DenetimRaporu:
    alanlar: dict[str, AlanSonucu]
    sorunlar: list[DenetimSorunu] = field(default_factory=list)
    otomatik_duzeltmeler: list[str] = field(default_factory=list)


def enum_yakala(deger: str, izinli: list[str]) -> tuple[str, bool]:
    """Değeri izinli listeye oturtur. (değer, değişti_mi) döndürür."""
    if deger in izinli:
        return deger, False
    katli = {ascii_katla(i): i for i in izinli}
    if ascii_katla(deger) in katli:
        return katli[ascii_katla(deger)], True
    en_iyi = process.extractOne(ascii_katla(deger), list(katli), scorer=fuzz.WRatio)
    if en_iyi and en_iyi[1] >= 80:
        return katli[en_iyi[0]], True
    return ("Diğer" if "Diğer" in izinli else izinli[-1]), True


def _fon_adi_geciyor(fon: dict, transkript_katli: str) -> bool:
    """Fonun adı/takma adı transkriptte geçiyor mu? ASR'nin birleştirdiği ('serbestfon') ve
    hafif bozduğu yazımlar da kabul edilir."""
    bosluksuz = re.sub(r"[^a-z0-9]", "", transkript_katli)
    temel_ad = re.sub(r"\(.*?\)", "", fon["ad"].replace("Örnek Portföy", ""))
    for ad in [temel_ad, *fon.get("takma_adlar", [])]:
        katli = ascii_katla(ad).strip()
        if len(katli) < 6:
            continue
        if re.sub(r"[^a-z0-9]", "", katli) in bosluksuz or fuzz.partial_ratio(katli, transkript_katli) >= 90:
            return True
    return False


def _musteri_satirlari(transkript: str) -> str:
    satirlar = [s.split(":", 1)[1] for s in transkript.splitlines() if s.startswith("MÜŞTERİ:")]
    return "\n".join(satirlar) if satirlar else transkript


class KuralMotoru:
    """Rapor satırı üzerinde deterministik denetim."""

    def __init__(self, bilgi: BilgiTabani) -> None:
        self.bilgi = bilgi

    def denetle(self, alanlar: dict[str, AlanSonucu], transkript: str, musteri_kelime: int | None = None) -> DenetimRaporu:
        alanlar = {k: v.model_copy() for k, v in alanlar.items()}
        rapor = DenetimRaporu(alanlar=alanlar)
        self._enumlar(rapor)
        self._fon_kodu(rapor, transkript)
        self._bildirim_sahibi(rapor)
        self._detay(rapor)
        self._capraz_kontroller(rapor, transkript, musteri_kelime)
        return rapor

    # ------------------------------------------------------------------ otomatik düzeltmeler
    def _enumlar(self, r: DenetimRaporu) -> None:
        for alan, izinli in self.bilgi.enumlar.items():
            sonuc = r.alanlar.get(alan)
            if sonuc is None:
                continue
            yeni, degisti = enum_yakala(sonuc.value, izinli)
            if degisti:
                r.otomatik_duzeltmeler.append(f"{alan}: '{sonuc.value}' izinli listede yok → '{yeni}'")
                sonuc.value = yeni
                sonuc.confidence = min(sonuc.confidence, 50)

    def _fon_kodu(self, r: DenetimRaporu, transkript: str) -> None:
        sonuc = r.alanlar.get("fon_kodu")
        if sonuc is None:
            return
        ham = sonuc.value.strip()
        gecerli: list[str] = []
        for parca in re.split(r"[,;/\s]+", ham):
            if not parca or parca == "-":
                continue
            kod = self.bilgi.kod_normalize(parca)
            if kod is None:
                r.otomatik_duzeltmeler.append(f"fon_kodu: '{parca}' fon sözlüğünde yok, çıkarıldı")
            elif kod not in gecerli:
                gecerli.append(kod)
        yeni = ", ".join(gecerli) if gecerli else "-"
        if yeni != ham:
            sonuc.value = yeni

        taranan = {k["kod"] for k in self.bilgi.transkriptte_kod_tara(transkript)}
        transkript_katli = ascii_katla(transkript)
        for kod in gecerli:
            fon = self.bilgi.kod_fon[kod]
            sahip = fon.get("ozel_fon_sahibi_soyadi")
            if kod not in taranan and not _fon_adi_geciyor(fon, transkript_katli) and not (sahip and ascii_katla(sahip) in transkript_katli):
                r.sorunlar.append(
                    DenetimSorunu(
                        alan="fon_kodu",
                        aciklama=f"{kod} ({fon['ad']}) transkriptte ne kod ne de ad olarak doğrudan geçmiyor.",
                        oneri="Kodun transkriptteki dayanağını fon_ara ile doğrula; dayanak yoksa çıkar.",
                        kaynak="kural_motoru",
                    )
                )
        eksik = sorted(taranan - set(gecerli))
        if eksik:
            r.sorunlar.append(
                DenetimSorunu(
                    alan="fon_kodu",
                    aciklama=f"Transkriptte fon bağlamında {', '.join(eksik)} kodu geçiyor ama fon_kodu alanında yok.",
                    oneri="Bu kodların görüşmede konuşulan fon olup olmadığını kontrol et.",
                    kaynak="kural_motoru",
                )
            )

    def _bildirim_sahibi(self, r: DenetimRaporu) -> None:
        sonuc = r.alanlar.get("bildirim_sahibi")
        if sonuc is None:
            return
        temiz = _HITAPLAR.sub("", sonuc.value).strip(" ,.-")
        temiz = re.sub(r"\s+", " ", temiz)
        if temiz != sonuc.value:
            r.otomatik_duzeltmeler.append(f"bildirim_sahibi: hitap sözcükleri temizlendi ('{sonuc.value}' → '{temiz}')")
            sonuc.value = temiz
        if sonuc.value and re.search(r"\[|\]|maskel", sonuc.value, re.IGNORECASE):
            r.otomatik_duzeltmeler.append("bildirim_sahibi: maskeli ifade ad olamaz, boşaltıldı")
            sonuc.value = ""
        temsilci = self.bilgi.temsilci_mi(sonuc.value) if sonuc.value else None
        if temsilci:
            r.otomatik_duzeltmeler.append(f"bildirim_sahibi: '{sonuc.value}' temsilci ({temsilci}), boşaltıldı (kural E-3)")
            sonuc.value = ""
            sonuc.confidence = 70

    def _detay(self, r: DenetimRaporu) -> None:
        sonuc = r.alanlar.get("bildirim_detayi")
        if sonuc is None:
            return
        maskeli, sayac = kisisel_veri_maskele(sonuc.value)
        if sayac:
            maskeli = re.sub(r"\[(TELEFON|TCKN|IBAN|E-POSTA)\]", "(kişisel veri paylaşıldı)", maskeli)
            r.otomatik_duzeltmeler.append(f"bildirim_detayi: kişisel veri maskelendi {sayac}")
            sonuc.value = maskeli
        for temsilci in self.bilgi.temsilciler:
            ilk_ad = temsilci.split()[0]
            if re.search(rf"[Mm]üşteri(?:\s+\w+)?\s+{ilk_ad}\b", sonuc.value):
                r.sorunlar.append(
                    DenetimSorunu(
                        alan="bildirim_detayi",
                        aciklama=f"Detay temsilci {temsilci} adını müşteriye atfediyor (kural L-8).",
                        oneri="Temsilci ile müşteriyi ayır.",
                        kaynak="kural_motoru",
                    )
                )

    # ------------------------------------------------------------------ çapraz kontroller
    def _capraz_kontroller(self, r: DenetimRaporu, transkript: str, musteri_kelime: int | None) -> None:
        a = r.alanlar
        tur = a.get("bildirim_turu", AlanSonucu()).value
        konu = a.get("bildirimin_konusu", AlanSonucu()).value
        muhatap = a.get("muhatap_kurum", AlanSonucu()).value
        detay = a.get("bildirim_detayi", AlanSonucu()).value
        fon_kodu = a.get("fon_kodu", AlanSonucu()).value

        def sorun(alan: str, aciklama: str, oneri: str) -> None:
            r.sorunlar.append(DenetimSorunu(alan=alan, aciklama=aciklama, oneri=oneri, kaynak="kural_motoru"))

        if konu == "Fon Getirilerinin Düşüklüğü" and tur not in ("Şikayet", "Öneri"):
            sorun("bildirim_turu", "Konu 'Fon Getirilerinin Düşüklüğü' iken tür Şikayet değil (kural D-7).", "Şikayet")
        if tur == "Şikayet" and not _SIKAYET_SINYALI.search(_musteri_satirlari(transkript)):
            sorun("bildirim_turu", "Tür Şikayet ama müşteri ifadelerinde şikayet sinyali bulunamadı (kural D-3).", "Müşteri gerçekten memnuniyetsizlik bildiriyor mu kontrol et.")
        if muhatap == "Örnek Bank" and not _BANKA_ISARETI.search(transkript):
            sorun("muhatap_kurum", "Muhatap Örnek Bank ama transkriptte Örnek Bank/ÖrnekCep/şube geçmiyor (kural I-2).", "Örnek Portföy")
        if muhatap != "Diğer Kurumlar":
            for kurum in self.bilgi.kurum.get("diger_kurumlar", []):
                if kurum.lower() in transkript.lower() and kurum.lower() not in detay.lower():
                    sorun("bildirim_detayi", f"Transkriptte {kurum} geçiyor ama detayda kurum adı yok (kural L-7).", f"Kanal kurumu {kurum} ise adını detaya yaz ve muhatabı yeniden değerlendir.")
                    break
        if konu == "Örnek Fon Mobil" and not _UYGULAMA_ISARETI.search(transkript):
            sorun("bildirimin_konusu", "Konu Örnek Fon Mobil ama transkriptte uygulama bağlamı yok (kural K-3).", "Uygulama geçmiyorsa başka konu seç.")
        if tur == "Hat Kesildi" and musteri_kelime is not None and musteri_kelime > 25:
            sorun("bildirim_turu", f"Tür Hat Kesildi ama müşteri {musteri_kelime} kelime konuşmuş (kural D-6).", "İçeriğe göre sınıfla.")
        if tur not in ("Hat Kesildi",) and detay and len(re.findall(r"[.!?](\s|$)", detay)) < 2:
            sorun("bildirim_detayi", "Detay çok kısa; en az 4 cümle bekleniyor (kural L-1).", "Detayı genişlet.")
        if tur == "Şikayet" and detay and not re.search(r"şikayet|memnuniyetsiz|sorun|mağdur|rahatsız|zarar|dolandır", detay.split(".")[0], re.IGNORECASE):
            sorun("bildirim_detayi", "Tür Şikayet ama detayın ilk cümlesinde şikayet görünmüyor (kural L-2).", "İlk cümlede şikayeti açıkça yaz.")
        for kod in sorted(set(re.findall(r"\b[A-Z][A-Z0-9]{2}\b", detay))):
            if kod in self.bilgi.fon_kodlari and kod not in fon_kodu:
                sorun("bildirim_detayi", f"Detayda {kod} kodu geçiyor ama fon_kodu alanında yok (kural L-6).", "Kod ile detay tutarlı olmalı.")
