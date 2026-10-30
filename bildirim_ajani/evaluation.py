"""Değerlendirme: ajan sistemi ile tek LLM çağrısı (baseline) aynı altın etiketli set üzerinde karşılaştırılır.

Altın etiketler, gerçek bir çağrı merkezinin iş birimi onaylı raporundan maskelenerek alınmıştır
(bkz. README). Her alan için doğruluk, ayrıca fon kodu için kesinlik/duyarlılık raporlanır.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import Ayarlar, ayarlari_yukle
from .guardrails import enum_yakala
from .knowledge_base import BilgiTabani, ascii_katla, bilgi_tabani
from .llm import LLMHatasi, LLMIstemci
from .memory import Hafiza
from .orchestrator import Orkestrator
from .preprocess import on_isle

KATEGORIK = ("bildirim_turu", "bildirimin_konusu", "muhatap_kurum")
DEGERLENDIRILEN = KATEGORIK + ("fon_kodu", "bildirim_sahibi")


_HARF_OKUNUSU = {
    "A": "a", "B": "be", "C": "ce", "D": "de", "E": "e", "F": "fe", "G": "ge", "H": "he", "I": "ı", "J": "je",
    "K": "ke", "L": "le", "M": "me", "N": "ne", "O": "o", "P": "pe", "R": "re", "S": "se", "T": "te", "U": "u",
    "V": "ve", "Y": "ye", "Z": "ze", "0": "sıfır", "1": "bir", "2": "iki", "3": "üç", "4": "dört", "5": "beş",
    "6": "altı", "7": "yedi", "8": "sekiz", "9": "dokuz",
}


def asr_stresi(vaka: dict[str, Any]) -> dict[str, Any] | None:
    """Gerçek kayıtlarda görülen ASR davranışını taklit eder: fon kodları harf harf okunmuş gibi yazılır
    ("ORT" -> "o re te"). Fon kodu olmayan vakalar için None döner."""
    kodlar = sorted(_kodlar(vaka["beklenen"].get("fon_kodu", "")))
    if not kodlar:
        return None
    metin = vaka["transkript"]
    for kod in kodlar:
        okunus = " ".join(_HARF_OKUNUSU.get(h, h.lower()) for h in kod)
        metin = re.sub(rf"(?<![\wÇĞİÖŞÜçğıöşü])[ÖO]{re.escape(kod[1:])}(?![\wÇĞİÖŞÜçğıöşü])" if kod.startswith("O") else rf"\b{kod}\b", okunus, metin)
    return {**vaka, "transkript": metin}


def seti_yukle(yol: Path) -> list[dict[str, Any]]:
    return [json.loads(s) for s in yol.read_text(encoding="utf-8").splitlines() if s.strip()]


def _kodlar(deger: str) -> set[str]:
    return {k.strip().upper() for k in (deger or "").replace(";", ",").split(",") if k.strip() and k.strip() != "-"}


def _ad(deger: str) -> str:
    return " ".join(ascii_katla(deger or "").split())


def alan_dogru_mu(alan: str, beklenen: str, tahmin: str) -> bool:
    if alan == "fon_kodu":
        return _kodlar(beklenen) == _kodlar(tahmin)
    if alan == "bildirim_sahibi":
        b, t = _ad(beklenen), _ad(tahmin)
        if not b or not t:
            return b == t
        return b == t or b.split()[0] == t.split()[0] and (len(b.split()) == 1 or len(t.split()) == 1)
    return (beklenen or "").strip() == (tahmin or "").strip()


@dataclass
class TekCagriBaseline:
    """Karşılaştırma için: tüm kurallar + fon sözlüğü tek prompta, araç/denetim/hafıza yok."""

    llm: LLMIstemci
    bilgi: BilgiTabani

    def tahmin_et(self, transkript: str) -> dict[str, str]:
        metin, _ = on_isle(transkript, self.bilgi)
        e = self.bilgi.enumlar
        sozluk = "\n".join(f"{f['kod']} — {f['ad']}" for f in self.bilgi.fonlar)
        sistem = (
            "Bir portföy şirketi çağrı merkezi görüşmesinden aylık bildirim raporu satırı doldur. Kurallar ve fon sözlüğü aşağıda.\n\n"
            f"{self.bilgi.kural_metni}\n\n## Fon sözlüğü\n{sozluk}\n\n"
            f"bildirim_turu: {' | '.join(e['bildirim_turu'])}\nbildirimin_konusu: {' | '.join(e['bildirimin_konusu'])}\n"
            f"muhatap_kurum: {' | '.join(e['muhatap_kurum'])}\n"
            'Çıktı JSON: {"bildirim_turu": "", "bildirimin_konusu": "", "muhatap_kurum": "", "fon_kodu": "", "bildirim_sahibi": "", "bildirim_detayi": ""}'
        )
        cikti = self.llm.json_iste([{"role": "system", "content": sistem}, {"role": "user", "content": metin}], sicaklik=0)
        return {k: str(cikti.get(k, "") or "") for k in DEGERLENDIRILEN + ("bildirim_detayi",)}


def degerlendir(
    mod: str = "ajan",
    set_yolu: Path | None = None,
    limit: int | None = None,
    ayarlar: Ayarlar | None = None,
    ilerleme: Callable[[int, int, dict[str, Any]], None] | None = None,
    asr_stres: bool = False,
) -> dict[str, Any]:
    """Değerlendirmeyi çalıştırır, sonuçları data/degerlendirme/sonuclar altına yazar ve özet döndürür."""
    ayarlar = ayarlar or ayarlari_yukle()
    set_yolu = set_yolu or ayarlar.veri_dizini / "degerlendirme" / "cagrilar.jsonl"
    vakalar = seti_yukle(set_yolu)[: limit or None]
    if asr_stres:
        vakalar = [v for v in (asr_stresi(v) for v in vakalar) if v is not None]
    bilgi = bilgi_tabani()
    llm = LLMIstemci(ayarlar)

    gecici = Path(tempfile.mkdtemp(prefix="degerlendirme_"))
    orkestrator = Orkestrator(llm=llm, ayarlar=ayarlar, bilgi=bilgi, hafiza=Hafiza(gecici / "hafiza.db")) if mod == "ajan" else None
    baseline = TekCagriBaseline(llm, bilgi) if mod == "tek_cagri" else None

    kayitlar: list[dict[str, Any]] = []
    for i, vaka in enumerate(vakalar, start=1):
        kullanim_once = llm.kullanim.ozet()
        baslangic = time.perf_counter()
        hata = ""
        insan_onayi = False
        try:
            if orkestrator is not None:
                sonuc = orkestrator.metinden_analiz(vaka["transkript"], vaka.get("dosya_adi", ""), zorla=True)
                tahmin = {k: str(sonuc.satir.get(k, "")) for k in DEGERLENDIRILEN + ("bildirim_detayi",)}
                insan_onayi = sonuc.insan_onayi_gerekli
            else:
                tahmin = baseline.tahmin_et(vaka["transkript"])
        except Exception as h:  # tek vakadaki beklenmeyen hata tüm koşuyu durdurmasın
            tahmin, hata = {k: "" for k in DEGERLENDIRILEN}, f"{type(h).__name__}: {h}"
        dogruluk = {a: alan_dogru_mu(a, vaka["beklenen"].get(a, ""), tahmin.get(a, "")) for a in DEGERLENDIRILEN}
        kullanim = llm.kullanim.ozet()
        kayit = {
            "id": vaka["id"],
            "kaynak": vaka.get("kaynak", ""),
            "beklenen": vaka["beklenen"],
            "tahmin": tahmin,
            "dogru": dogruluk,
            "insan_onayi": insan_onayi,
            "sure_sn": round(time.perf_counter() - baslangic, 1),
            "llm_cagri": kullanim["cagri"] - kullanim_once["cagri"],
            "hata": hata,
        }
        kayitlar.append(kayit)
        if ilerleme:
            ilerleme(i, len(vakalar), kayit)

    ozet = ozetle(kayitlar, mod, ayarlar.llm_model)
    ozet["asr_stres"] = asr_stres
    ozet["enum_disi_deger_yuzde"] = enum_disi_oran(kayitlar, bilgi)
    cikti_dizini = set_yolu.parent / "sonuclar"
    cikti_dizini.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now().strftime("%Y%m%d_%H%M")
    ad = f"{mod}_asr_stres" if asr_stres else mod
    (cikti_dizini / f"{zaman}_{ad}_detay.jsonl").write_text(
        "\n".join(json.dumps(k, ensure_ascii=False) for k in kayitlar) + "\n", encoding="utf-8"
    )
    (cikti_dizini / f"{ad}_ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8")
    return ozet


def ozetle(kayitlar: list[dict[str, Any]], mod: str, model: str) -> dict[str, Any]:
    n = len(kayitlar) or 1
    dogruluk = {a: round(100 * sum(k["dogru"][a] for k in kayitlar) / n, 1) for a in DEGERLENDIRILEN}
    tp = fp = fn = 0
    for k in kayitlar:
        b, t = _kodlar(k["beklenen"].get("fon_kodu", "")), _kodlar(k["tahmin"].get("fon_kodu", ""))
        tp, fp, fn = tp + len(b & t), fp + len(t - b), fn + len(b - t)
    tam_satir = round(100 * sum(all(k["dogru"].values()) for k in kayitlar) / n, 1)
    onayli = [k for k in kayitlar if k["insan_onayi"]]
    onaysiz = [k for k in kayitlar if not k["insan_onayi"]]
    return {
        "mod": mod,
        "model": model,
        "vaka": len(kayitlar),
        "alan_dogrulugu_yuzde": dogruluk,
        "kategorik_ortalama_yuzde": round(sum(dogruluk[a] for a in KATEGORIK) / len(KATEGORIK), 1),
        "tam_dogru_satir_yuzde": tam_satir,
        "fon_kodu_kesinlik_yuzde": round(100 * tp / (tp + fp), 1) if tp + fp else 100.0,
        "fon_kodu_duyarlilik_yuzde": round(100 * tp / (tp + fn), 1) if tp + fn else 100.0,
        "insan_onayina_dusen": len(onayli),
        "onaysiz_satir_tam_dogru_yuzde": round(100 * sum(all(k["dogru"].values()) for k in onaysiz) / len(onaysiz), 1) if onaysiz else None,
        "ortalama_sure_sn": round(sum(k["sure_sn"] for k in kayitlar) / n, 1),
        "ortalama_llm_cagrisi": round(sum(k["llm_cagri"] for k in kayitlar) / n, 1),
        "hata": sum(1 for k in kayitlar if k["hata"]),
    }


def enum_disi_oran(kayitlar: list[dict[str, Any]], bilgi: BilgiTabani) -> dict[str, float]:
    """Baseline'ın izinli liste dışı ürettiği değer oranı (guardrail'in neden gerektiğini gösterir)."""
    sonuc = {}
    for alan in KATEGORIK:
        disari = sum(1 for k in kayitlar if enum_yakala(k["tahmin"].get(alan, ""), bilgi.enumlar[alan])[1])
        sonuc[alan] = round(100 * disari / (len(kayitlar) or 1), 1)
    return sonuc
