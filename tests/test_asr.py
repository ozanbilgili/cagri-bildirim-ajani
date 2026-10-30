from pathlib import Path

from bildirim_ajani.asr import Segment, rolleri_ata, segmentleri_birlestir

from .conftest import SahteLLM

SEGMENTLER = [
    Segment(0.0, 2.0, "Örnek Portföy, ben Elif, nasıl yardımcı olabilirim?"),
    Segment(2.6, 5.0, "Merhaba, fonumu satamıyorum."),
    Segment(5.1, 6.0, "Hata veriyor."),
    Segment(6.8, 8.0, "Hemen kontrol edelim."),
]


def test_rol_ajani_etiketler_ve_birlestirir():
    llm = SahteLLM()
    llm.yanitlar["roller"] = {"roller": ["TEMSİLCİ", "MÜŞTERİ", "MÜŞTERİ", "TEMSİLCİ"]}
    roller, yontem = rolleri_ata(SEGMENTLER, llm)
    assert yontem == "rol_ajani"
    assert segmentleri_birlestir(SEGMENTLER, roller).splitlines() == [
        "TEMSİLCİ: Örnek Portföy, ben Elif, nasıl yardımcı olabilirim?",
        "MÜŞTERİ: Merhaba, fonumu satamıyorum. Hata veriyor.",
        "TEMSİLCİ: Hemen kontrol edelim.",
    ]


def test_rol_ajani_hatasinda_sezgisel_yedek():
    llm = SahteLLM()
    llm.hata_verecek.add("roller")
    roller, yontem = rolleri_ata(SEGMENTLER, llm)
    assert yontem == "sezgisel" and roller[0] == "TEMSİLCİ" and roller[1] == "MÜŞTERİ"


def test_bozuk_ses_dosyasi_satir_uretir_ve_onaya_duser(orkestrator, tmp_path: Path):
    bozuk = tmp_path / "26.09.03_101522_12_ELIF_AKSOY_05550000123_08500000000_1.wav"
    bozuk.write_bytes(b"bu bir ses dosyasi degil")
    sonuc = orkestrator.sesten_analiz(bozuk)
    assert sonuc.insan_onayi_gerekli
    assert "manuel" in sonuc.satir["bildirim_detayi"]
    assert sonuc.satir["telefon"] == "5550000123"
