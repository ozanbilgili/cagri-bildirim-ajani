from bildirim_ajani.llm import json_ayikla
from bildirim_ajani.preprocess import asr_duzelt, dosya_adini_coz, kisisel_veri_maskele, on_isle, rolleri_normalize


def test_fon_ara_kod_okunus_ve_ad(bilgi):
    assert bilgi.fon_ara("ört")[0]["kod"] == "ORT"
    assert bilgi.fon_ara("o re te")[0]["kod"] == "ORT"
    assert bilgi.fon_ara("o pe bir")[0]["kod"] == "OP1"
    assert bilgi.fon_ara("altın fonu")[0]["kod"] == "OAL"
    assert bilgi.fon_ara("katılım para piyasası")[0]["kod"] == "OPK"


def test_genel_ad_temel_fonu_secer(bilgi):
    # Kural J-4: "para piyasası" niteleyicisiz temel fon OP1'e gider
    assert bilgi.fon_ara("para piyasası")[0]["kod"] == "OP1"


def test_kod_olmayan_kisaltmalar_kod_sayilmaz(bilgi):
    assert bilgi.kod_normalize("TL") is None
    assert bilgi.kod_normalize("OKS") is None
    assert bilgi.fon_ara("TEFAS") == []


def test_transkriptte_kod_tarama_baglam_ister(bilgi):
    metin = "MÜŞTERİ: ÖRT fonumu satamıyorum. her zaman böyle. HER şey yolunda dedi."
    kodlar = {k["kod"] for k in bilgi.transkriptte_kod_tara(metin)}
    assert "ORT" in kodlar
    assert "HER" not in kodlar  # Türkçe kelime çakışması, fon bağlamı yok


def test_temsilci_tespiti(bilgi):
    assert bilgi.temsilci_mi("Selin Hanım") == "Selin Er"
    assert bilgi.temsilci_mi("Selen") == "Selin Er"
    assert bilgi.temsilci_mi("Elif Yılmaz") is None
    assert bilgi.temsilci_mi("Ahmet Kaya") is None


def test_ozel_fon_soyad_eslesmesi(bilgi):
    assert bilgi.ozel_fon_sahibi("Tunalı")["kod"] == "TNA"
    assert bilgi.ozel_fon_sahibi("Barış") is None  # sadece ad eşleşmesi yetmez


def test_kural_kitabi_parcalari(bilgi):
    alanlar = {p.alan for p in bilgi.kural_parcalari}
    assert alanlar == {"G", "D", "K", "I", "J", "L", "E"}


def test_dosya_adi_ayristirma(bilgi):
    meta = dosya_adini_coz("26.09.03_101522_12_SELIN_ER_05550000123_08500000000_100001_1.wav", bilgi)
    assert meta.tarih == "2026-09-03"
    assert meta.saat == "10:15:22"
    assert meta.temsilci == "Selin Er"
    assert meta.telefon == "5550000123"
    assert not meta.ayrisma_uyarilari


def test_dosya_adi_yurt_disi_arayan_ve_hat_sirasi(bilgi):
    meta = dosya_adini_coz("26.09.03_101522_12_KAAN_YURT_08500000000_447700900123_1.wav", bilgi)
    assert meta.telefon == "447700900123"  # çağrı merkezi hattı arayan sayılmaz


def test_bozuk_dosya_adi_analizi_durdurmaz(bilgi):
    meta = dosya_adini_coz("kayit.wav", bilgi)
    assert meta.tarih == "" and meta.ayrisma_uyarilari


def test_kisisel_veri_maskeleme():
    metin, sayac = kisisel_veri_maskele("Numaram 0555 123 45 67, TC 12345678901, IBAN TR12 0006 4000 0011 2345 6789 01")
    assert "[TELEFON]" in metin and "[TCKN]" in metin and "[IBAN]" in metin
    assert "0555" not in metin and sayac["[IBAN]"] == 1


def test_asr_duzeltmeleri(bilgi):
    metin, uygulanan = asr_duzelt("Çay Merkezi aradım, ÖRT ve ÖAL fonlarım var, bilot fon da.", bilgi)
    assert "Çağrı Merkezi" in metin and "ORT" in metin and "OAL" in metin and "Pilotfon" in metin
    assert len(uygulanan) == 4


def test_rol_etiketleri_normalize():
    metin = rolleri_normalize("SPK0: Merhaba\nspk1: Selam\nTemsilci: Buyurun\nMüşteri: Teşekkürler")
    assert metin.splitlines() == ["TEMSİLCİ: Merhaba", "MÜŞTERİ: Selam", "TEMSİLCİ: Buyurun", "MÜŞTERİ: Teşekkürler"]


def test_on_isleme_olcum(bilgi):
    _, bilgi_ = on_isle("TEMSİLCİ: Alo?\nMÜŞTERİ: ...", bilgi)
    assert bilgi_["olcum"]["musteri_kelime"] == 0


def test_json_ayikla_toleransli():
    assert json_ayikla('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_ayikla('Sonuç şu: {"a": {"b": 2}} tamam') == {"a": {"b": 2}}
