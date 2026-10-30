"""Kurum bilgisi, fon sözlüğü ve kural kitabını yükler; fon arama mantığını içerir."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from .config import BILGI_DIZINI

_ASCII_TABLO = str.maketrans("çğıöşüâîû", "cgiosuaiu")

# Türkçe harf okunuşları: "o re te" -> ORT, "o pe bir" -> OP1
_HARF_OKUNUSU = {
    "a": "A", "be": "B", "ce": "C", "de": "D", "e": "E", "fe": "F", "ge": "G", "he": "H",
    "ı": "I", "i": "I", "je": "J", "ke": "K", "ka": "K", "le": "L", "me": "M", "ne": "N",
    "o": "O", "ö": "O", "pe": "P", "re": "R", "se": "S", "te": "T", "u": "U", "ü": "U",
    "ve": "V", "ye": "Y", "ze": "Z",
}
_RAKAM_OKUNUSU = {
    "sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
    "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9",
}
_FON_BAGLAMI = re.compile(
    r"fon|tefas|portföy|yatırım|alım|satım|sat|al(?:dım|mak|ış)|valör|fiyat|getiri|performans|kesim|komisyon|ücret|kod",
    re.IGNORECASE,
)


def tr_kucuk(metin: str) -> str:
    """Türkçe kurallarıyla küçük harfe çevirir (I->ı, İ->i)."""
    return metin.replace("İ", "i").replace("I", "ı").lower()


def ascii_katla(metin: str) -> str:
    """Bulanık eşleştirme için Türkçe karakterleri ASCII'ye indirger."""
    return tr_kucuk(metin).translate(_ASCII_TABLO)


def _ad_sadelestir(ad: str) -> str:
    """Hitap sözcüklerini atıp karşılaştırılabilir ad üretir."""
    kelimeler = [k for k in ascii_katla(ad).split() if k not in {"hanim", "bey", "sayin", "musteri"}]
    return " ".join(kelimeler)


@dataclass(frozen=True)
class KuralParcasi:
    id: str
    alan: str
    baslik: str
    metin: str


class BilgiTabani:
    """Kurum profili, fon sözlüğü ve kural kitabı için tek erişim noktası."""

    def __init__(self, dizin: Path = BILGI_DIZINI) -> None:
        self.kurum: dict[str, Any] = json.loads((dizin / "kurum.json").read_text(encoding="utf-8"))
        self.fonlar: list[dict[str, Any]] = json.loads((dizin / "fonlar.json").read_text(encoding="utf-8"))
        self.kural_metni = (dizin / "kurallar.md").read_text(encoding="utf-8")
        self.kural_parcalari = self._kurallari_parcala(self.kural_metni)
        self.fon_kodlari = {f["kod"] for f in self.fonlar}
        self.kod_fon = {f["kod"]: f for f in self.fonlar}
        self.enumlar: dict[str, list[str]] = self.kurum["enumlar"]
        self.temsilciler: list[str] = self.kurum["temsilciler"]
        self.kod_olmayanlar = {k.upper() for k in self.kurum["kod_olmayan_kisaltmalar"]}
        self.kelime_cakisan_kodlar = set(self.kurum.get("turkce_kelime_cakisan_kodlar", []))

    # ------------------------------------------------------------------ kurallar
    @staticmethod
    def _kurallari_parcala(metin: str) -> list[KuralParcasi]:
        parcalar: list[KuralParcasi] = []
        baslik, satirlar = "", []

        def kaydet() -> None:
            if not baslik:
                return
            kural_id = baslik.split()[0]
            alan = kural_id.split("-")[0]
            parcalar.append(KuralParcasi(kural_id, alan, baslik, f"{baslik}\n" + "\n".join(satirlar).strip()))

        for satir in metin.splitlines():
            if satir.startswith("### "):
                kaydet()
                baslik, satirlar = satir[4:].strip(), []
            elif satir.startswith("## ") or satir.startswith("# "):
                kaydet()
                baslik, satirlar = "", []
            elif baslik:
                satirlar.append(satir)
        kaydet()
        return parcalar

    def alan_kurallari(self, alanlar: str) -> list[KuralParcasi]:
        """Verilen alan harflerine (ör. 'GDKI') ait tüm kuralları döndürür."""
        return [p for p in self.kural_parcalari if p.alan in alanlar]

    # ------------------------------------------------------------------ temsilci
    def temsilci_mi(self, ad: str) -> str | None:
        """Ad bir temsilciye (veya yakın varyantına) aitse temsilcinin resmi adını döndürür."""
        aday = _ad_sadelestir(ad)
        if not aday:
            return None
        varyant_tablosu = self.kurum.get("temsilci_varyantlari", {})
        for temsilci in self.temsilciler:
            adaylar = {_ad_sadelestir(v) for v in [temsilci, *varyant_tablosu.get(temsilci, [])]}
            if aday in adaylar or fuzz.ratio(aday, _ad_sadelestir(temsilci)) >= 88:
                return temsilci
        return None

    # ------------------------------------------------------------------ fon kodu
    def kod_normalize(self, ham: str) -> str | None:
        """'ört', 'Ö R T', 'o-r-t' gibi yazımları geçerli fon koduna çevirir; değilse None."""
        sade = re.sub(r"[\s.\-_/]", "", ham)
        if not sade:
            return None
        aday = ascii_katla(sade).upper()
        if aday in self.kod_olmayanlar:
            return None
        if aday in self.fon_kodlari:
            return aday
        return None

    def heceli_kodlari_bul(self, metin: str) -> list[str]:
        """'o re te' gibi harf harf okunmuş kodları bulur."""
        kelimeler = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", tr_kucuk(metin))
        bulunan: list[str] = []
        for i in range(len(kelimeler)):
            harfler = ""
            for kelime in kelimeler[i : i + 4]:
                if kelime in _HARF_OKUNUSU:
                    harfler += _HARF_OKUNUSU[kelime]
                elif kelime in _RAKAM_OKUNUSU:
                    harfler += _RAKAM_OKUNUSU[kelime]
                elif len(kelime) == 1 and kelime.isalnum():
                    harfler += ascii_katla(kelime).upper()
                else:
                    break
                if len(harfler) == 3 and harfler in self.fon_kodlari and harfler not in bulunan:
                    bulunan.append(harfler)
                    break
        return bulunan

    def transkriptte_kod_tara(self, metin: str, pencere: int = 60) -> list[dict[str, Any]]:
        """Transkriptte fon bağlamında geçen kodları deterministik olarak bulur."""
        sonuc: dict[str, dict[str, Any]] = {}
        for eslesme in re.finditer(r"(?<![\wçğıöşü])([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü0-9]{2})(?![\wçğıöşü])", metin):
            ham = eslesme.group(1)
            if ham.islower() and ham.isalpha():
                continue  # küçük harfli gerçek kelimeler (ör. 'her', 'bas') kod değildir
            kod = self.kod_normalize(ham)
            if not kod:
                continue
            bas, son = max(0, eslesme.start() - pencere), eslesme.end() + pencere
            baglam = metin[bas:son]
            # "HER" gibi Türkçe kelimeyle çakışan kodlar yalnızca hemen yanında "fon" geçiyorsa kod sayılır
            yakin = metin[max(0, eslesme.start() - 12) : eslesme.end() + 12]
            if kod in self.kelime_cakisan_kodlar and not re.search(r"fon", yakin, re.IGNORECASE):
                continue
            if not _FON_BAGLAMI.search(baglam):
                continue
            sonuc.setdefault(kod, {"kod": kod, "yazim": ham, "baglam": baglam.replace("\n", " ").strip()})
        for kod in self.heceli_kodlari_bul(metin):
            sonuc.setdefault(kod, {"kod": kod, "yazim": "heceli", "baglam": ""})
        return list(sonuc.values())

    def fon_ara(self, sorgu: str, limit: int = 5) -> list[dict[str, Any]]:
        """Kod, harf harf okunuş ya da fon adıyla sözlükte arama yapar (bulanık)."""
        sorgu = (sorgu or "").strip()
        if not sorgu:
            return []
        sonuclar: dict[str, dict[str, Any]] = {}

        def ekle(kod: str, skor: float, tur: str) -> None:
            onceki = sonuclar.get(kod)
            if onceki is None or onceki["skor"] < skor:
                fon = self.kod_fon[kod]
                sonuclar[kod] = {"kod": kod, "ad": fon["ad"], "kategori": fon["kategori"], "skor": skor, "eslesme": tur}

        kod = self.kod_normalize(sorgu)
        if kod:
            ekle(kod, 100, "kod")
        for parca in re.split(r"[,;]", sorgu):
            kod = self.kod_normalize(parca)
            if kod:
                ekle(kod, 100, "kod")
        for kod in self.heceli_kodlari_bul(sorgu):
            ekle(kod, 95, "heceli_kod")

        katli = ascii_katla(sorgu)
        for fon in self.fonlar:
            adlar = [fon["ad"].replace("Örnek Portföy", ""), *fon.get("takma_adlar", [])]
            en_iyi = 0.0
            for ad in adlar:
                ak = ascii_katla(ad)
                if ak and ak in katli:
                    en_iyi = max(en_iyi, min(99.0, 90 + len(ak) / 5))
                else:
                    en_iyi = max(en_iyi, fuzz.token_set_ratio(katli, ak) * 0.9, fuzz.partial_ratio(ak, katli) * 0.85)
            if en_iyi >= 60:
                ekle(fon["kod"], en_iyi, "ad")
        # Eşit skorda niteleyicisiz (kısa adlı) temel fon öne gelir: "para piyasası" -> OP1
        sirali = sorted(sonuclar.values(), key=lambda s: (-round(s["skor"], 1), len(s["ad"])))[:limit]
        for s in sirali:
            s["skor"] = round(s["skor"])
        return sirali

    def ozel_fon_sahibi(self, soyad: str) -> dict[str, Any] | None:
        """Soyadı bir özel fonun sahibiyle eşleşiyorsa o fonu döndürür."""
        hedef = ascii_katla(soyad)
        eslesen = [f for f in self.fonlar if f.get("ozel_fon_sahibi_soyadi") and ascii_katla(f["ozel_fon_sahibi_soyadi"]) == hedef]
        return eslesen[0] if len(eslesen) == 1 else None


@lru_cache(maxsize=1)
def bilgi_tabani() -> BilgiTabani:
    """Uygulama genelinde paylaşılan bilgi tabanı örneği."""
    return BilgiTabani()
