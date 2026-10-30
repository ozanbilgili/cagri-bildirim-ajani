from bildirim_ajani.schemas import IzOlayi

from .conftest import ORNEK_TRANSKRIPT

DOSYA = "26.09.03_101522_12_SELIN_ER_05550000123_08500000000_100001_1.wav"


def test_uctan_uca_analiz(orkestrator, sahte_llm):
    olaylar: list[IzOlayi] = []
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA, olaylar.append)
    s = sonuc.satir
    assert (s["bildirim_turu"], s["muhatap_kurum"], s["fon_kodu"], s["bildirim_sahibi"]) == ("Şikayet", "Diğer Kurumlar", "ORT", "Mehmet Tunç")
    assert s["gorusulen_mt"] == "Selin Er" and s["telefon"] == "5550000123"
    assert not sonuc.insan_onayi_gerekli, sonuc.insan_onayi_nedenleri
    # Planlayıcı, üç paralel ajan, özet ve denetçi çalıştı; fon ajanı aracı kullandı
    assert {"plan", "siniflandirma", "fon", "kimlik", "ozet", "denetci"} <= set(sahte_llm.cagrilar)
    assert any(e.tur == "arac" and "transkriptte_kod_tara" in e.mesaj for e in olaylar)


def test_hat_kesildi_modeli_cagirmaz(orkestrator, sahte_llm):
    sonuc = orkestrator.metinden_analiz("TEMSİLCİ: Örnek Portföy, buyurun?\nMÜŞTERİ: ...\nTEMSİLCİ: Alo?", DOSYA)
    assert sonuc.satir["bildirim_turu"] == "Hat Kesildi"
    assert sonuc.satir["islem_ozeti"] == "Yanıt verilmemiştir."
    assert sahte_llm.cagrilar == []


def test_denetci_sorunu_revizyonu_tetikler(orkestrator, sahte_llm):
    durum = {"tur": 0}

    def denetci(_):
        durum["tur"] += 1
        if durum["tur"] == 1:
            return {"onay": False, "sorunlar": [{"alan": "muhatap_kurum", "aciklama": "Kanal Kuzey Bank", "oneri": "Diğer Kurumlar"}]}
        return {"onay": True, "sorunlar": []}

    sahte_llm.ozel["denetci"] = denetci
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sahte_llm.cagrilar.count("siniflandirma") == 2  # revizyonla yeniden çalıştı
    assert any(e.tur == "revizyon" for e in sonuc.iz)
    assert not sonuc.insan_onayi_gerekli


def test_cozulmeyen_sorun_insan_onayina_duser(orkestrator, sahte_llm):
    sahte_llm.yanitlar["denetci"] = {"onay": False, "sorunlar": [{"alan": "bildirim_turu", "aciklama": "Şüpheli", "oneri": "Bilgi Talebi"}]}
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sonuc.insan_onayi_gerekli
    assert any("Şüpheli" in n for n in sonuc.insan_onayi_nedenleri)


def test_ajan_hatasi_guvenli_varsayilan_ve_onay(orkestrator, sahte_llm):
    sahte_llm.hata_verecek.add("fon")
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sonuc.alanlar["fon_kodu"].confidence == 0
    assert sonuc.insan_onayi_gerekli
    assert any(e.tur == "hata" for e in sonuc.iz)


def test_enum_disi_cikti_duzeltilir(orkestrator, sahte_llm):
    sahte_llm.yanitlar["siniflandirma"]["bildirim_turu"]["value"] = "sikayet"
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sonuc.satir["bildirim_turu"] == "Şikayet"


def test_hafiza_tekrar_islemeyi_onler(orkestrator, sahte_llm):
    orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    cagri_sayisi = len(sahte_llm.cagrilar)
    ikinci = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert ikinci.onbellekten and len(sahte_llm.cagrilar) == cagri_sayisi


def test_tekrar_arayan_tespiti(orkestrator):
    orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    ikinci = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT + "\nMÜŞTERİ: Bir de şunu sorayım.", DOSYA.replace("101522", "151000"))
    assert ikinci.tekrar_arayan and ikinci.onceki_cagri_sayisi == 1
    assert any("Tekrarlayan şikayet" in n for n in ikinci.insan_onayi_nedenleri)


def test_duzeltme_hafizasi_ajana_ornek_olarak_gider(orkestrator, sahte_llm):
    ilk = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    orkestrator.hafiza.duzeltme_kaydet(ilk.cagri_id, "muhatap_kurum", "Örnek Portföy", "Diğer Kurumlar", "Kuzey Bank kanalı")
    gorulen = {}

    def siniflandirma(mesajlar):
        gorulen["mesaj"] = mesajlar[1]["content"]
        return sahte_llm.yanitlar["siniflandirma"]

    sahte_llm.ozel["siniflandirma"] = siniflandirma
    orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA, zorla=True)
    assert "iş biriminin yaptığı düzeltmeler" in gorulen["mesaj"] and "Kuzey Bank kanalı" in gorulen["mesaj"]


def test_rag_embedding_yoksa_bm25(orkestrator):
    assert orkestrator.kurallar.mod == "bm25"
    sonuc = orkestrator.kurallar.ara("başka banka üzerinden fon satamıyorum", alanlar="I", k=2)
    assert sonuc and all(p.alan == "I" for p, _ in sonuc)


def test_bozuk_alan_ciktisi_analizi_durdurmaz(orkestrator, sahte_llm):
    sahte_llm.yanitlar["kimlik"] = {"bildirim_sahibi": {"value": "Mehmet Tunç", "confidence": "yüksek", "gerekce": None}}
    sahte_llm.yanitlar["denetci"] = {"onay": False, "sorunlar": [{"alan": ["fon_kodu"], "aciklama": "liste"}, "metin"]}
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sonuc.satir["bildirim_sahibi"] == "Mehmet Tunç"
    assert sonuc.alanlar["bildirim_sahibi"].confidence == 0  # sayı olmayan güven 0'a iner


def test_planlayici_hatasi_insan_onayina_duser(orkestrator, sahte_llm):
    sahte_llm.hata_verecek.add("plan")
    sonuc = orkestrator.metinden_analiz(ORNEK_TRANSKRIPT, DOSYA)
    assert sonuc.satir["bildirim_turu"] == "Şikayet"  # güvenli varsayılan rota ile analiz sürdü
    assert any("hata" in n for n in sonuc.insan_onayi_nedenleri)
