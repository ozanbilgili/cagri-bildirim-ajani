from bildirim_ajani.guardrails import KuralMotoru, enum_yakala
from bildirim_ajani.schemas import AlanSonucu

from .conftest import ORNEK_TRANSKRIPT


def _alanlar(**degerler):
    temel = {
        "bildirim_turu": "Şikayet",
        "bildirimin_konusu": "Alım/Satım Esasları/Operasyonel Süreç",
        "muhatap_kurum": "Diğer Kurumlar",
        "fon_kodu": "ORT",
        "bildirim_sahibi": "Mehmet Tunç",
        "bildirim_detayi": "Müşteri Kuzey Bank üzerinden aldığı ORT fonunu satamadığı için şikayette bulunmuştur. Temsilci yönlendirme yapmıştır. Dönüş sözü verilmiştir.",
    }
    temel.update(degerler)
    return {k: AlanSonucu(value=v, confidence=90) for k, v in temel.items()}


def test_enum_yakalama():
    izinli = ["Bilgi Talebi", "Şikayet", "Diğer"]
    assert enum_yakala("Şikayet", izinli) == ("Şikayet", False)
    assert enum_yakala("sikayet", izinli) == ("Şikayet", True)
    assert enum_yakala("tamamen alakasız", izinli) == ("Diğer", True)


def test_temiz_satir_sorunsuz(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(), ORNEK_TRANSKRIPT, 40)
    assert rapor.sorunlar == []


def test_sozluk_disi_kod_cikarilir(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(fon_kodu="ORT, XYZ, TL"), ORNEK_TRANSKRIPT, 40)
    assert rapor.alanlar["fon_kodu"].value == "ORT"
    assert any("XYZ" in d for d in rapor.otomatik_duzeltmeler)


def test_kanitsiz_kod_sorun_olur(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(fon_kodu="ORT, OAL"), ORNEK_TRANSKRIPT, 40)
    assert any(s.alan == "fon_kodu" and "OAL" in s.aciklama for s in rapor.sorunlar)


def test_temsilci_bildirim_sahibi_olamaz(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(bildirim_sahibi="Selin Hanım"), ORNEK_TRANSKRIPT, 40)
    assert rapor.alanlar["bildirim_sahibi"].value == ""


def test_hitap_temizlenir(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(bildirim_sahibi="Mehmet Bey"), ORNEK_TRANSKRIPT, 40)
    assert rapor.alanlar["bildirim_sahibi"].value == "Mehmet"


def test_getiri_dusuklugu_sikayet_olmali(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(bildirim_turu="Bilgi Talebi", bildirimin_konusu="Fon Getirilerinin Düşüklüğü"), ORNEK_TRANSKRIPT, 40)
    assert any(s.alan == "bildirim_turu" and "D-7" in s.aciklama for s in rapor.sorunlar)


def test_ornek_bank_kanit_ister(bilgi):
    rapor = KuralMotoru(bilgi).denetle(_alanlar(muhatap_kurum="Örnek Bank"), ORNEK_TRANSKRIPT, 40)
    assert any(s.alan == "muhatap_kurum" for s in rapor.sorunlar)


def test_detaydaki_kisisel_veri_maskelenir(bilgi):
    detay = "Müşteri şikayetini iletmiştir. 0555 123 45 67 numarasını vermiştir. Dönüş yapılacaktır."
    rapor = KuralMotoru(bilgi).denetle(_alanlar(bildirim_detayi=detay), ORNEK_TRANSKRIPT, 40)
    assert "0555" not in rapor.alanlar["bildirim_detayi"].value


def test_sikayet_sinyali_yoksa_uyari(bilgi):
    transkript = "TEMSİLCİ: Buyurun.\nMÜŞTERİ: OAL altın fonunun fiyatını öğrenebilir miyim?\nTEMSİLCİ: Tabii."
    rapor = KuralMotoru(bilgi).denetle(_alanlar(fon_kodu="OAL"), transkript, 10)
    assert any(s.alan == "bildirim_turu" and "D-3" in s.aciklama for s in rapor.sorunlar)


def test_asr_birlesik_fon_adi_kanit_sayilir(bilgi):
    transkript = "MÜŞTERİ: Örnek portföy model serbestfon demek yani, hesabıma geçmedi.\nTEMSİLCİ: Anladım."
    rapor = KuralMotoru(bilgi).denetle(_alanlar(fon_kodu="OMS"), transkript, 20)
    assert not any(s.alan == "fon_kodu" for s in rapor.sorunlar)
