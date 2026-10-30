"""Komut satırı arayüzü: python -m bildirim_ajani <komut>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SES_UZANTILARI = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def _iz_yazdir(olay) -> None:
    print(f"  [{olay.tur:<9}] {olay.ajan}: {olay.mesaj[:160]}", flush=True)


def _analiz(orkestrator, yol: Path, zorla: bool, sessiz: bool = False):
    dinleyici = None if sessiz else _iz_yazdir
    if yol.suffix.lower() in SES_UZANTILARI:
        return orkestrator.sesten_analiz(yol, dinleyici, zorla)
    return orkestrator.metinden_analiz(yol.read_text(encoding="utf-8"), yol.with_suffix(".wav").name, dinleyici, zorla)


def komut_analiz(args) -> int:
    from .orchestrator import Orkestrator

    yol = Path(args.dosya)
    if not yol.is_file():
        print(f"Dosya bulunamadı: {yol}", file=sys.stderr)
        return 1
    try:
        sonuc = _analiz(Orkestrator(), yol, args.zorla, sessiz=args.json)
    except UnicodeDecodeError:
        print(f"{yol.name} UTF-8 metin dosyası değil. Transkript .txt (UTF-8) ya da ses dosyası verin.", file=sys.stderr)
        return 1
    if args.json:
        print(sonuc.model_dump_json(indent=2))
    else:
        print(json.dumps(sonuc.satir, ensure_ascii=False, indent=2))
        if sonuc.insan_onayi_gerekli:
            print("\nİnsan onayı gerekli:\n- " + "\n- ".join(sonuc.insan_onayi_nedenleri))
    return 0


def komut_toplu(args) -> int:
    from .orchestrator import Orkestrator

    dizin = Path(args.dizin)
    dosyalar = sorted(p for p in dizin.rglob("*") if p.suffix.lower() in SES_UZANTILARI | {".txt"})
    if not dosyalar:
        print(f"{dizin} içinde .txt veya ses dosyası yok.", file=sys.stderr)
        return 1
    orkestrator = Orkestrator()
    for i, yol in enumerate(dosyalar, start=1):
        print(f"[{i}/{len(dosyalar)}] {yol.name}", flush=True)
        try:
            sonuc = _analiz(orkestrator, yol, args.zorla, sessiz=True)
        except Exception as hata:  # bir kayıttaki hata toplu işi durdurmaz
            print(f"  → ATLANDI: {type(hata).__name__}: {hata}", file=sys.stderr)
            continue
        isaret = " (insan onayı)" if sonuc.insan_onayi_gerekli else ""
        print(f"  → {sonuc.satir['bildirim_turu']} | {sonuc.satir['bildirimin_konusu']} | {sonuc.satir['fon_kodu']} | {sonuc.sure_sn} sn{isaret}")
    return komut_rapor(args)


def komut_rapor(args) -> int:
    from .config import ayarlari_yukle
    from .llm import LLMIstemci
    from .memory import Hafiza
    from .report import excel_yaz, istatistik, numaralandir, yonetici_ozeti_yaz

    ayarlar = ayarlari_yukle()
    satirlar = numaralandir(Hafiza(ayarlar.hafiza_db).tum_satirlar())
    if not satirlar:
        print("Hafızada işlenmiş çağrı yok.", file=sys.stderr)
        return 1
    stats = istatistik(satirlar)
    ozet = yonetici_ozeti_yaz(LLMIstemci(ayarlar), stats, satirlar) if args.ozet else None
    cikti = Path(args.cikti) if args.cikti else ayarlar.veri_dizini / "ciktilar" / "aylik_bildirim_raporu.xlsx"
    excel_yaz(satirlar, cikti, stats, ozet)
    print(f"Rapor yazıldı: {cikti} ({len(satirlar)} satır)")
    if ozet:
        print("\n" + ozet["ozet"])
        for u in ozet.get("uyarilar", []):
            print(f"UYARI: {u}")
    return 0


def komut_degerlendir(args) -> int:
    from .evaluation import degerlendir

    modlar = ["tek_cagri", "ajan"] if args.mod == "ikisi" else [args.mod]
    for mod in modlar:
        print(f"== {mod} ==", flush=True)

        def ilerleme(i, n, kayit):
            yanlis = [a for a, d in kayit["dogru"].items() if not d]
            print(f"  [{i}/{n}] {kayit['id']} {kayit['sure_sn']} sn  yanlış: {', '.join(yanlis) or '-'}", flush=True)

        ozet = degerlendir(mod=mod, limit=args.limit, ilerleme=ilerleme, asr_stres=args.asr_stres)
        print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 0


def komut_saglik(args) -> int:
    from .asr import asr_kullanilabilir
    from .llm import LLMIstemci

    durum = LLMIstemci().saglik_kontrolu()
    durum["asr"] = asr_kullanilabilir()
    print(json.dumps(durum, ensure_ascii=False, indent=2))
    return 0 if durum["llm"] else 1


def komut_hafiza_temizle(args) -> int:
    from .config import ayarlari_yukle
    from .memory import Hafiza

    Hafiza(ayarlari_yukle().hafiza_db).temizle()
    print("Hafıza temizlendi.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ana = argparse.ArgumentParser(prog="bildirim_ajani", description="Çağrı kaydından müşteri bildirim raporu üreten çoklu ajan sistemi")
    alt = ana.add_subparsers(dest="komut", required=True)

    p = alt.add_parser("analiz", help="Tek bir transkript (.txt) veya ses kaydını analiz eder")
    p.add_argument("dosya")
    p.add_argument("--zorla", action="store_true", help="Hafızada olsa bile yeniden analiz et")
    p.add_argument("--json", action="store_true", help="Tüm sonucu (iz dahil) JSON yazdır")
    p.set_defaults(fonksiyon=komut_analiz)

    p = alt.add_parser("toplu", help="Bir klasördeki tüm kayıtları işler ve Excel raporu üretir")
    p.add_argument("dizin")
    p.add_argument("--zorla", action="store_true")
    p.add_argument("--cikti", help="Excel çıktı yolu")
    p.add_argument("--ozet", action="store_true", help="Rapor Ajanı ile yönetici özeti ekle")
    p.set_defaults(fonksiyon=komut_toplu)

    p = alt.add_parser("rapor", help="Hafızadaki çağrılardan Excel raporu üretir")
    p.add_argument("--cikti")
    p.add_argument("--ozet", action="store_true")
    p.set_defaults(fonksiyon=komut_rapor)

    p = alt.add_parser("degerlendir", help="Altın etiketli sette doğruluk ölçer")
    p.add_argument("--mod", choices=["ajan", "tek_cagri", "ikisi"], default="ikisi")
    p.add_argument("--limit", type=int)
    p.add_argument("--asr-stres", action="store_true", help="Fon kodlu vakalarda kodları harf harf okunmuş hale getirerek dayanıklılığı ölç")
    p.set_defaults(fonksiyon=komut_degerlendir)

    alt.add_parser("saglik", help="Model, embedding ve ASR erişimini kontrol eder").set_defaults(fonksiyon=komut_saglik)
    alt.add_parser("hafiza-temizle", help="Hafızadaki tüm çağrı ve düzeltmeleri siler").set_defaults(fonksiyon=komut_hafiza_temizle)

    args = ana.parse_args(argv)
    return args.fonksiyon(args)


if __name__ == "__main__":
    sys.exit(main())
