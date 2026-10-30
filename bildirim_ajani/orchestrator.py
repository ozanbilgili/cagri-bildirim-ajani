"""Orkestratör: çağrıyı planlar, uzman ajanları yürütür, denetim/revizyon döngüsünü yönetir.

Akış:
    ön işleme → hafıza kontrolü → Planlayıcı
      → [Sınıflandırma ‖ Fon Kodu ‖ Kimlik] (paralel) → Özet
      → Kural Motoru + Denetçi → (sorun varsa) ilgili ajanlara revizyon → son kontrol
      → rapor satırı + insan onayı kararı → hafızaya kayıt
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .agents import DenetciAjan, FonAjani, KimlikAjani, OzetAjani, PlanlayiciAjan, SiniflandirmaAjani
from .agents.base import AracliAjan
from .asr import AsrHatasi, sesi_transkripte_cevir
from .config import Ayarlar, ayarlari_yukle
from .guardrails import KuralMotoru
from .knowledge_base import BilgiTabani, bilgi_tabani
from .llm import LLMHatasi, LLMIstemci
from .memory import Hafiza, cagri_kimligi
from .preprocess import dosya_adini_coz, on_isle, transkript_olcumu
from .rag import KuralDeposu
from .schemas import (
    ALAN_BASLIKLARI,
    AlanSonucu,
    AnalizSonucu,
    CagriGirdisi,
    CagriMeta,
    DenetimSorunu,
    IzOlayi,
    Plan,
)
from .tools import AracBaglami, AracKutusu

OlayDinleyici = Callable[[IzOlayi], None]

# Hangi alanın hangi ajanın sorumluluğunda olduğu (revizyon yönlendirmesi için)
ALAN_SAHIBI = {
    "bildirim_turu": "siniflandirma",
    "bildirimin_konusu": "siniflandirma",
    "muhatap_kurum": "siniflandirma",
    "fon_kodu": "fon",
    "bildirim_sahibi": "kimlik",
    "bildirim_detayi": "ozet",
}

HAT_KESILDI_DETAYI = "Arama bağlantısı kuruldu ancak anlamlı görüşme gerçekleşmedi (hat kesildi/ses gelmedi)."


class Orkestrator:
    """Çoklu ajan analiz hattı."""

    def __init__(
        self,
        llm: LLMIstemci | None = None,
        ayarlar: Ayarlar | None = None,
        bilgi: BilgiTabani | None = None,
        hafiza: Hafiza | None = None,
        kural_deposu: KuralDeposu | None = None,
        rag_k: int = 3,
    ) -> None:
        self.ayarlar = ayarlar or ayarlari_yukle()
        self.llm = llm or LLMIstemci(self.ayarlar)
        self.bilgi = bilgi or bilgi_tabani()
        self.hafiza = hafiza if hafiza is not None else Hafiza(self.ayarlar.hafiza_db)
        self.kurallar = kural_deposu or KuralDeposu(self.bilgi, self.llm, self.ayarlar.veri_dizini / ".index")
        self.kural_motoru = KuralMotoru(self.bilgi)
        self.rag_k = rag_k
        adim = self.ayarlar.max_ajan_adimi
        self.planlayici = PlanlayiciAjan(self.llm, self.bilgi)
        self.ajanlar: dict[str, AracliAjan] = {
            "siniflandirma": SiniflandirmaAjani(self.llm, self.bilgi, adim),
            "fon": FonAjani(self.llm, self.bilgi, adim + 1),
            "kimlik": KimlikAjani(self.llm, self.bilgi, adim),
            "ozet": OzetAjani(self.llm, self.bilgi),
        }
        self.denetci = DenetciAjan(self.llm, self.bilgi, adim)

    # ------------------------------------------------------------------ giriş noktaları
    def metinden_analiz(
        self, transkript: str, dosya_adi: str = "", dinleyici: OlayDinleyici | None = None, zorla: bool = False
    ) -> AnalizSonucu:
        meta = dosya_adini_coz(dosya_adi, self.bilgi) if dosya_adi else CagriMeta()
        return self.analiz_et(CagriGirdisi(transkript=transkript, meta=meta), dinleyici, zorla)

    def sesten_analiz(self, yol: Path, dinleyici: OlayDinleyici | None = None, zorla: bool = False) -> AnalizSonucu:
        """Ses kaydını önce transkripte çevirir, sonra analiz eder. ASR başarısızsa satır yine üretilir."""
        meta = dosya_adini_coz(yol.name, self.bilgi)
        asr_izi: list[IzOlayi] = []

        def topla(e: IzOlayi) -> None:
            asr_izi.append(e)
            if dinleyici:
                dinleyici(e)

        try:
            transkript = sesi_transkripte_cevir(yol, self.llm, topla, self.ayarlar)
        except AsrHatasi as hata:
            topla(IzOlayi(tur="hata", ajan="Konuşma Tanıma", mesaj=str(hata)))
            return self._cozumlenemedi(meta, str(hata), asr_izi)
        sonuc = self.analiz_et(CagriGirdisi(transkript=transkript, meta=meta, kaynak="ses"), dinleyici, zorla)
        sonuc.iz = asr_izi + sonuc.iz
        return sonuc

    def _cozumlenemedi(self, meta: CagriMeta, hata: str, iz: list[IzOlayi]) -> AnalizSonucu:
        """Ses çözümlenemediğinde rapordan satır düşmemesi için 'manuel inceleme' satırı üretir."""
        alanlar = self._hat_kesildi_alanlari("Ses kaydı çözümlenemedi.")
        alanlar["bildirim_turu"] = AlanSonucu(value="Diğer", confidence=0, gerekce=hata, kaynak="Konuşma Tanıma")
        alanlar["bildirim_detayi"] = AlanSonucu(
            value="Ses kaydı otomatik olarak çözümlenemedi; kaydın manuel dinlenerek değerlendirilmesi gerekmektedir.",
            confidence=0,
            gerekce=hata,
            kaynak="Konuşma Tanıma",
        )
        girdi = CagriGirdisi(transkript="", meta=meta, kaynak="ses")
        cagri_id = cagri_kimligi(f"asr-hata|{meta.dosya_adi}")
        plan = Plan(rota="hat_kesildi", gerekce="Ses çözümlenemedi", fon_analizi_gerekli=False, kimlik_analizi_gerekli=False)
        sonuc = AnalizSonucu(cagri_id=cagri_id, alanlar=alanlar, plan=plan, iz=iz)
        sonuc.satir = self._satir_olustur(alanlar, girdi, cagri_id, plan)
        sonuc.insan_onayi_gerekli = True
        sonuc.insan_onayi_nedenleri = [f"Ses çözümlenemedi: {hata}"]
        if self.hafiza is not None:
            self.hafiza.cagri_kaydet(sonuc, "")
        return sonuc

    def analiz_et(self, girdi: CagriGirdisi, dinleyici: OlayDinleyici | None = None, zorla: bool = False) -> AnalizSonucu:
        """Bir çağrıyı uçtan uca analiz eder. Hiçbir koşulda istisna fırlatmaz; hata iz'e yazılır."""
        baslangic = time.perf_counter()
        kullanim_once = self.llm.kullanim.ozet()
        iz: list[IzOlayi] = []

        def olay(e: IzOlayi) -> None:
            iz.append(e)
            if dinleyici:
                try:
                    dinleyici(e)
                except Exception:  # arayüz hatası analizi bozmamalı
                    pass

        metin, onisleme = on_isle(girdi.transkript, self.bilgi)
        cagri_id = cagri_kimligi(metin + "|" + girdi.meta.dosya_adi)
        if not zorla and self.hafiza is not None:
            onceki = self.hafiza.cagri_getir(cagri_id)
            if onceki is not None:
                onceki.onbellekten = True
                olay(IzOlayi(tur="bilgi", ajan="Hafıza", mesaj="Bu kayıt daha önce işlenmiş; hafızadaki sonuç döndürüldü."))
                onceki.iz = iz + onceki.iz
                return onceki

        olay(
            IzOlayi(
                tur="bilgi",
                ajan="Ön İşleme",
                mesaj=f"{onisleme['olcum']['replik']} replik, {onisleme['olcum']['kelime']} kelime; "
                f"maskelenen: {onisleme['maskelenen'] or 'yok'}; ASR düzeltmesi: {len(onisleme['asr_duzeltmeleri'])}",
                veri=onisleme,
            )
        )
        for uyari in girdi.meta.ayrisma_uyarilari:
            olay(IzOlayi(tur="uyari", ajan="Ön İşleme", mesaj=uyari))

        baglam = AracBaglami(self.bilgi, self.kurallar, self.hafiza, metin, girdi.meta, cagri_id)
        sonuc = AnalizSonucu(cagri_id=cagri_id)

        gecmis = self.hafiza.arayan_gecmisi(girdi.meta.telefon, haric_id=cagri_id) if self.hafiza else []
        if gecmis:
            sonuc.tekrar_arayan, sonuc.onceki_cagri_sayisi = True, len(gecmis)
            olay(IzOlayi(tur="bilgi", ajan="Hafıza", mesaj=f"Bu numara daha önce {len(gecmis)} kez aramış.", veri={"gecmis": gecmis}))

        sonuc.plan = self._planla(metin, onisleme["olcum"], gecmis, olay)
        if sonuc.plan.rota == "hat_kesildi":
            alanlar = self._hat_kesildi_alanlari(sonuc.plan.gerekce)
            sorunlar: list[DenetimSorunu] = []
        else:
            alanlar, sorunlar = self._tam_analiz(metin, girdi, baglam, sonuc.plan, gecmis, olay)

        sonuc.alanlar = alanlar
        sonuc.sorunlar = sorunlar
        sonuc.satir = self._satir_olustur(alanlar, girdi, cagri_id, sonuc.plan)
        sonuc.iz = iz  # insan onayı kararı izdeki hata olaylarına bakar
        self._insan_onayi(sonuc, olay)
        sonuc.sure_sn = round(time.perf_counter() - baslangic, 1)
        kullanim_sonra = self.llm.kullanim.ozet()
        sonuc.llm_kullanimi = {k: round(kullanim_sonra[k] - kullanim_once[k], 1) for k in kullanim_sonra}
        olay(IzOlayi(tur="sonuc", ajan="Orkestratör", mesaj=f"Analiz tamamlandı ({sonuc.sure_sn} sn, {sonuc.llm_kullanimi['cagri']} model çağrısı)."))
        sonuc.iz = iz
        if self.hafiza is not None:
            self.hafiza.cagri_kaydet(sonuc, metin)
        return sonuc

    # ------------------------------------------------------------------ planlama
    def _planla(self, metin: str, olcum: dict[str, Any], gecmis: list[dict[str, Any]], olay: OlayDinleyici) -> Plan:
        # Deterministik ön kontrol: anlamlı içerik yoksa model çağırmaya gerek yok
        if olcum["kelime"] < 8 or (olcum["roller_belli"] and olcum["musteri_kelime"] < 4):
            plan = Plan(rota="hat_kesildi", gerekce="Transkriptte anlamlı müşteri konuşması yok.", fon_analizi_gerekli=False, kimlik_analizi_gerekli=False)
            olay(IzOlayi(tur="plan", ajan="Planlayıcı", mesaj=f"Rota: hat_kesildi — {plan.gerekce}", veri=plan.model_dump()))
            return plan
        mesaj = f"## Transkript\n{metin[:6000]}\n\n## Ölçümler\n{json.dumps(olcum, ensure_ascii=False)}"
        if gecmis:
            mesaj += f"\n\n## Bu numaradan önceki çağrılar\n{json.dumps(gecmis, ensure_ascii=False)}"
        try:
            ham = self.planlayici.calistir(mesaj, None, olay)
            plan = Plan.model_validate({k: v for k, v in ham.items() if k in Plan.model_fields})
        except Exception as hata:
            olay(IzOlayi(tur="hata", ajan="Planlayıcı", mesaj=f"Plan üretilemedi, tam analiz varsayıldı: {hata}"))
            plan = Plan(gerekce="Planlayıcı hatası; güvenli varsayılan.")
        if gecmis:
            plan.dikkat_noktalari.append(f"Arayan bu numaradan daha önce {len(gecmis)} kez aramış.")
        olay(IzOlayi(tur="plan", ajan="Planlayıcı", mesaj=f"Rota: {plan.rota} — {plan.gerekce}", veri=plan.model_dump()))
        return plan

    def _hat_kesildi_alanlari(self, gerekce: str) -> dict[str, AlanSonucu]:
        kaynak = "Planlayıcı (hat kesildi rotası)"
        return {
            "bildirim_turu": AlanSonucu(value="Hat Kesildi", confidence=90, gerekce=gerekce, kaynak=kaynak),
            "bildirimin_konusu": AlanSonucu(value="Diğer", confidence=90, gerekce=gerekce, kaynak=kaynak),
            "muhatap_kurum": AlanSonucu(value=self.bilgi.kurum["kisa_ad"], confidence=80, gerekce="Varsayılan muhatap (kural I-1).", kaynak=kaynak),
            "fon_kodu": AlanSonucu(value="-", confidence=90, gerekce="Fon konuşulmadı.", kaynak=kaynak),
            "bildirim_sahibi": AlanSonucu(value="", confidence=90, gerekce="Arayan kendini tanıtmadı.", kaynak=kaynak),
            "bildirim_detayi": AlanSonucu(value=HAT_KESILDI_DETAYI, confidence=90, gerekce=gerekce, kaynak=kaynak),
        }

    # ------------------------------------------------------------------ uzman ajanlar
    def _ortak_baglam(self, metin: str, girdi: CagriGirdisi, plan: Plan) -> str:
        bolum = f"## Transkript\n{metin}\n\n## Çağrı bilgisi\n"
        bolum += f"Tarih: {girdi.meta.tarih or 'bilinmiyor'} | Çağrıyı karşılayan temsilci: {girdi.meta.temsilci or 'bilinmiyor'} (müşteri değildir)\n"
        if plan.dikkat_noktalari:
            bolum += "\n## Planlayıcının dikkat notları\n" + "\n".join(f"- {n}" for n in plan.dikkat_noktalari) + "\n"
        return bolum

    def _rag_bolumu(self, metin: str, kendi: str, diger: str) -> str:
        """Ajanın kendi alanlarının kuralları (meta veri filtresi) + diğer alanlardan transkripte en ilgili k kural."""
        secilen = {p.id: p for p in self.bilgi.alan_kurallari(kendi)}
        for p, _ in self.kurallar.ara(metin, alanlar=diger, k=self.rag_k):
            secilen.setdefault(p.id, p)
        return "## İlgili iş birimi kuralları\n" + "\n\n".join(p.metin for p in secilen.values())

    def _duzeltme_bolumu(self, metin: str, alanlar: tuple[str, ...]) -> str:
        if self.hafiza is None:
            return ""
        ornekler = self.hafiza.benzer_duzeltmeler(metin, alanlar, k=3)
        if not ornekler:
            return ""
        satirlar = [f"- {o['alan']}: '{o['eski']}' yerine '{o['yeni']}' ({o['aciklama'] or 'açıklama yok'})" for o in ornekler]
        return "\n\n## Benzer çağrılarda iş biriminin yaptığı düzeltmeler\n" + "\n".join(satirlar)

    def _ajan_mesaji(self, ajan: str, metin: str, girdi: CagriGirdisi, plan: Plan, ek: str = "") -> str:
        ortak = self._ortak_baglam(metin, girdi, plan)
        if ajan == "siniflandirma":
            return ortak + "\n" + self._rag_bolumu(metin, "DKI", "GJL") + self._duzeltme_bolumu(metin, ("bildirim_turu", "bildirimin_konusu", "muhatap_kurum")) + ek
        if ajan == "fon":
            return ortak + "\n" + self._rag_bolumu(metin, "J", "GIK") + self._duzeltme_bolumu(metin, ("fon_kodu",)) + ek
        if ajan == "kimlik":
            return ortak + "\n" + self._rag_bolumu(metin, "E", "GL") + ek
        return ortak + "\n" + self._rag_bolumu(metin, "L", "GDKIJ") + ek

    def _ajan_calistir(self, ajan: str, mesaj: str, baglam: AracBaglami, olay: OlayDinleyici) -> dict[str, AlanSonucu]:
        nesne = self.ajanlar[ajan]
        beklenen = [a for a, s in ALAN_SAHIBI.items() if s == ajan]
        olay(IzOlayi(tur="ajan", ajan=nesne.ad, mesaj=f"Çalışıyor → {', '.join(ALAN_BASLIKLARI[a] for a in beklenen)}"))
        kutu = AracKutusu(baglam, nesne.arac_adlari) if nesne.arac_adlari else None
        try:
            ham = nesne.calistir(mesaj, kutu, olay)
        except (LLMHatasi, ValueError) as hata:
            olay(IzOlayi(tur="hata", ajan=nesne.ad, mesaj=f"Ajan başarısız oldu: {hata}"))
            ham = {}
        sonuc: dict[str, AlanSonucu] = {}
        for alan in beklenen:
            deger = ham.get(alan) if isinstance(ham, dict) else None
            if isinstance(deger, dict):
                try:
                    sonuc[alan] = AlanSonucu.model_validate({**deger, "kaynak": nesne.ad})
                    continue
                except ValidationError as hata:
                    olay(IzOlayi(tur="hata", ajan=nesne.ad, mesaj=f"{ALAN_BASLIKLARI[alan]} çıktısı şemaya uymuyor: {hata.errors()[0]['msg']}"))
                    deger = None
            if isinstance(deger, (str, int, float)):
                sonuc[alan] = AlanSonucu(value=str(deger), confidence=50, gerekce="Ajan gerekçe vermedi.", kaynak=nesne.ad)
            else:
                varsayilan = {"fon_kodu": "-", "bildirim_sahibi": "", "bildirimin_konusu": "Diğer", "bildirim_turu": "Diğer", "muhatap_kurum": self.bilgi.kurum["kisa_ad"]}.get(alan, "")
                sonuc[alan] = AlanSonucu(value=varsayilan, confidence=0, gerekce="Ajan bu alan için geçerli çıktı üretemedi.", kaynak=nesne.ad)
                olay(IzOlayi(tur="uyari", ajan=nesne.ad, mesaj=f"{ALAN_BASLIKLARI[alan]} için çıktı yok; güvenli varsayılan kullanıldı."))
        ozet = "; ".join(f"{ALAN_BASLIKLARI[a]}={v.value[:60] or '∅'} (%{v.confidence})" for a, v in sonuc.items())
        olay(IzOlayi(tur="sonuc", ajan=nesne.ad, mesaj=ozet, veri={a: v.model_dump() for a, v in sonuc.items()}))
        return sonuc

    def _ozet_ek_bilgisi(self, alanlar: dict[str, AlanSonucu]) -> str:
        kodlar = [k.strip() for k in alanlar.get("fon_kodu", AlanSonucu()).value.split(",") if k.strip() in self.bilgi.fon_kodlari]
        fonlar = "; ".join(f"{k} = {self.bilgi.kod_fon[k]['ad']}" for k in kodlar) or "fon kodu yok"
        kararlar = {a: alanlar[a].value for a in ("bildirim_turu", "bildirimin_konusu", "muhatap_kurum", "fon_kodu", "bildirim_sahibi") if a in alanlar}
        return f"\n\n## Diğer ajanların kararları\n{json.dumps(kararlar, ensure_ascii=False)}\nFonların resmi adları: {fonlar}"

    def _tam_analiz(
        self,
        metin: str,
        girdi: CagriGirdisi,
        baglam: AracBaglami,
        plan: Plan,
        gecmis: list[dict[str, Any]],
        olay: OlayDinleyici,
    ) -> tuple[dict[str, AlanSonucu], list[DenetimSorunu]]:
        alanlar: dict[str, AlanSonucu] = {}
        calisacaklar = ["siniflandirma"]
        if plan.fon_analizi_gerekli:
            calisacaklar.append("fon")
        else:
            alanlar["fon_kodu"] = AlanSonucu(value="-", confidence=80, gerekce="Planlayıcı: görüşmede fon geçmiyor.", kaynak="Planlayıcı")
        if plan.kimlik_analizi_gerekli:
            calisacaklar.append("kimlik")
        else:
            alanlar["bildirim_sahibi"] = AlanSonucu(value="", confidence=80, gerekce="Planlayıcı: arayan adını söylemedi.", kaynak="Planlayıcı")

        if self.hafiza is not None:
            benzer = self.hafiza.benzer_duzeltmeler(metin, k=3)
            if benzer:
                olay(
                    IzOlayi(
                        tur="bilgi",
                        ajan="Hafıza",
                        mesaj=f"{len(benzer)} benzer iş birimi düzeltmesi ajanlara örnek olarak verilecek: "
                        + "; ".join(f"{ALAN_BASLIKLARI.get(d['alan'], d['alan'])} '{d['eski']}' → '{d['yeni']}'" for d in benzer),
                        veri={"duzeltmeler": benzer},
                    )
                )

        # Bağımsız ajanlar paralel çalışır
        with ThreadPoolExecutor(max_workers=len(calisacaklar)) as havuz:
            isler = {a: havuz.submit(self._ajan_calistir, a, self._ajan_mesaji(a, metin, girdi, plan), baglam, olay) for a in calisacaklar}
            for a in calisacaklar:
                alanlar.update(isler[a].result())

        alanlar.update(self._ajan_calistir("ozet", self._ajan_mesaji("ozet", metin, girdi, plan, self._ozet_ek_bilgisi(alanlar)), baglam, olay))

        sorunlar: list[DenetimSorunu] = []
        for tur in range(self.ayarlar.max_revizyon + 1):
            rapor = self.kural_motoru.denetle(alanlar, metin, self._musteri_kelime(metin))
            alanlar = rapor.alanlar
            for d in rapor.otomatik_duzeltmeler:
                olay(IzOlayi(tur="guardrail", ajan="Kural Motoru", mesaj=d))
            for s in rapor.sorunlar:
                olay(IzOlayi(tur="guardrail", ajan="Kural Motoru", mesaj=f"{ALAN_BASLIKLARI.get(s.alan, s.alan)}: {s.aciklama}"))
            sorunlar = rapor.sorunlar + self._denetle(metin, alanlar, rapor.sorunlar, baglam, olay)
            if not sorunlar:
                olay(IzOlayi(tur="denetim", ajan="Denetçi Ajan", mesaj="Satır onaylandı, revizyon gerekmiyor."))
                break
            if tur == self.ayarlar.max_revizyon:
                olay(IzOlayi(tur="uyari", ajan="Orkestratör", mesaj=f"Revizyon hakkı bitti; {len(sorunlar)} sorun insan onayına bırakıldı."))
                break
            alanlar = self._revize_et(metin, girdi, plan, baglam, alanlar, sorunlar, olay)
        # Döngü her zaman bir denetimle biter: dönen alanlar kural motorundan geçmiştir
        return alanlar, sorunlar

    def _denetle(
        self, metin: str, alanlar: dict[str, AlanSonucu], kural_sorunlari: list[DenetimSorunu], baglam: AracBaglami, olay: OlayDinleyici
    ) -> list[DenetimSorunu]:
        satir = {a: v.value for a, v in alanlar.items()}
        mesaj = f"## Transkript\n{metin}\n\n## Denetlenecek rapor satırı\n{json.dumps(satir, ensure_ascii=False, indent=1)}"
        if kural_sorunlari:
            mesaj += "\n\n## Kural motorunun uyarıları (bunları ayrıca yazma; sadece senin bulduğun EK sorunları yaz)\n"
            mesaj += "\n".join(f"- {s.alan}: {s.aciklama}" for s in kural_sorunlari)
        olay(IzOlayi(tur="ajan", ajan=self.denetci.ad, mesaj="Satırı transkripte karşı denetliyor"))
        kutu = AracKutusu(baglam, self.denetci.arac_adlari)
        try:
            ham = self.denetci.calistir(mesaj, kutu, olay)
        except (LLMHatasi, ValueError) as hata:
            olay(IzOlayi(tur="hata", ajan=self.denetci.ad, mesaj=f"Denetim yapılamadı: {hata}"))
            return [DenetimSorunu(alan="bildirim_detayi", aciklama="Denetçi ajan çalışamadı; satır insan kontrolüne bırakıldı.")]
        bulunan = []
        sorun_listesi = ham.get("sorunlar") if isinstance(ham, dict) else None
        for s in sorun_listesi if isinstance(sorun_listesi, list) else []:
            if isinstance(s, dict) and isinstance(s.get("alan"), str) and s["alan"] in ALAN_SAHIBI and s.get("aciklama"):
                bulunan.append(DenetimSorunu(alan=s["alan"], aciklama=str(s["aciklama"]), oneri=str(s.get("oneri", "")), kaynak="denetci_ajan"))
        if bulunan:
            for s in bulunan:
                olay(IzOlayi(tur="denetim", ajan=self.denetci.ad, mesaj=f"{ALAN_BASLIKLARI[s.alan]}: {s.aciklama} → öneri: {s.oneri or '-'}"))
        elif not kural_sorunlari:
            olay(IzOlayi(tur="denetim", ajan=self.denetci.ad, mesaj="Ek sorun bulunmadı."))
        return bulunan

    def _revize_et(
        self,
        metin: str,
        girdi: CagriGirdisi,
        plan: Plan,
        baglam: AracBaglami,
        alanlar: dict[str, AlanSonucu],
        sorunlar: list[DenetimSorunu],
        olay: OlayDinleyici,
    ) -> dict[str, AlanSonucu]:
        gruplar: dict[str, list[DenetimSorunu]] = {}
        for s in sorunlar:
            gruplar.setdefault(ALAN_SAHIBI[s.alan], []).append(s)
        alanlar = dict(alanlar)
        onceki_tur = alanlar.get("bildirim_turu", AlanSonucu()).value

        for ajan in ("siniflandirma", "fon", "kimlik"):
            if ajan not in gruplar:
                continue
            olay(IzOlayi(tur="revizyon", ajan="Orkestratör", mesaj=f"{self.ajanlar[ajan].ad} geri bildirimle yeniden çalıştırılıyor ({len(gruplar[ajan])} sorun)."))
            mesaj = self._ajan_mesaji(ajan, metin, girdi, plan, self._geri_bildirim(alanlar, gruplar[ajan]))
            alanlar.update(self._ajan_calistir(ajan, mesaj, baglam, olay))

        tur_degisti = alanlar.get("bildirim_turu", AlanSonucu()).value != onceki_tur
        if "ozet" in gruplar or tur_degisti or "fon" in gruplar:
            neden = gruplar.get("ozet", [])
            if tur_degisti:
                neden = neden + [DenetimSorunu(alan="bildirim_detayi", aciklama=f"Bildirim türü '{onceki_tur}' → '{alanlar['bildirim_turu'].value}' olarak değişti; ilk cümle yeni türü yansıtmalı.")]
            olay(IzOlayi(tur="revizyon", ajan="Orkestratör", mesaj="Özet Ajanı güncel kararlarla yeniden yazıyor."))
            ek = self._ozet_ek_bilgisi(alanlar) + (self._geri_bildirim(alanlar, neden) if neden else "")
            alanlar.update(self._ajan_calistir("ozet", self._ajan_mesaji("ozet", metin, girdi, plan, ek), baglam, olay))
        return alanlar

    @staticmethod
    def _geri_bildirim(alanlar: dict[str, AlanSonucu], sorunlar: list[DenetimSorunu]) -> str:
        satirlar = [
            f"- {ALAN_BASLIKLARI.get(s.alan, s.alan)} (şu anki değer: '{alanlar.get(s.alan, AlanSonucu()).value[:120]}'): {s.aciklama}"
            + (f" Öneri: {s.oneri}" if s.oneri else "")
            for s in sorunlar
        ]
        return (
            "\n\n## DENETİM GERİ BİLDİRİMİ (revizyon)\nÖnceki kararın denetimde şu sorunlara takıldı. Transkripte tekrar bak; "
            "sorun haklıysa düzelt, haksızsa kararını koru ve gerekçede nedenini yaz. Kararını değiştirmeden önce "
            "araçlarınla yeniden doğrula; yeni değerin de transkriptte dayanağı olmalı, emin değilsen önceki değeri koru.\n" + "\n".join(satirlar)
        )

    @staticmethod
    def _musteri_kelime(metin: str) -> int | None:
        olcum = transkript_olcumu(metin)
        return olcum["musteri_kelime"] if olcum["roller_belli"] else None

    # ------------------------------------------------------------------ çıktı
    def _satir_olustur(self, alanlar: dict[str, AlanSonucu], girdi: CagriGirdisi, cagri_id: str, plan: Plan) -> dict[str, Any]:
        sabit = self.bilgi.kurum["rapor_sabitleri"]
        guvenler = [v.confidence for v in alanlar.values()]
        yanitsiz = plan.rota == "hat_kesildi"
        return {
            "bildirim_no": "",
            "tarih": girdi.meta.tarih,
            "gorusulen_mt": girdi.meta.temsilci,
            "bildirim_turu": alanlar["bildirim_turu"].value,
            "bildirim_sahibi": alanlar["bildirim_sahibi"].value,
            "telefon": girdi.meta.telefon,
            "bildirim_yontemi": sabit["bildirim_yontemi"],
            "muhatap_kurum": alanlar["muhatap_kurum"].value,
            "fon_kodu": alanlar["fon_kodu"].value,
            "bildirimin_konusu": alanlar["bildirimin_konusu"].value,
            "bildirim_detayi": alanlar["bildirim_detayi"].value,
            "islem_ozeti": sabit["islem_ozeti_yanitsiz"] if yanitsiz else sabit["islem_ozeti"],
            "cevaplama_tarihi": girdi.meta.tarih,
            "cevap": "",
            "cevaplama_suresi": sabit["cevaplama_suresi"],
            "ai_duzeltmesi": sabit["ai_duzeltmesi"],
            "kaynak": sabit["kaynak"],
            "analiz_guveni": round(sum(guvenler) / len(guvenler)) if guvenler else 0,
            "dosya_adi": girdi.meta.dosya_adi,
            "cagri_id": cagri_id,
        }

    def _insan_onayi(self, sonuc: AnalizSonucu, olay: OlayDinleyici) -> None:
        nedenler = []
        esik = self.ayarlar.dusuk_guven_esigi
        for alan, v in sonuc.alanlar.items():
            if v.confidence < esik:
                nedenler.append(f"{ALAN_BASLIKLARI[alan]} düşük güvenli (%{v.confidence})")
        for s in sonuc.sorunlar:
            nedenler.append(f"Çözülmemiş denetim notu — {ALAN_BASLIKLARI.get(s.alan, s.alan)}: {s.aciklama}")
        if any(e.tur == "hata" for e in sonuc.iz):
            nedenler.append("Analiz sırasında ajan/araç hatası oluştu")
        if sonuc.tekrar_arayan and sonuc.alanlar.get("bildirim_turu", AlanSonucu()).value == "Şikayet":
            nedenler.append(f"Tekrarlayan şikayet: bu numara daha önce {sonuc.onceki_cagri_sayisi} kez aramış")
        sonuc.insan_onayi_gerekli = bool(nedenler)
        sonuc.insan_onayi_nedenleri = nedenler
        if nedenler:
            olay(IzOlayi(tur="uyari", ajan="Orkestratör", mesaj=f"İnsan onayı gerekli: {len(nedenler)} neden", veri={"nedenler": nedenler}))


def dosyadan_transkript(yol: Path) -> str:
    """Metin dosyasından transkript okur."""
    return yol.read_text(encoding="utf-8")
