"""Streamlit arayüzü: streamlit run app.py"""

from __future__ import annotations

import html
import json
import queue
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

from bildirim_ajani.asr import asr_kullanilabilir
from bildirim_ajani.config import ayarlari_yukle
from bildirim_ajani.knowledge_base import bilgi_tabani
from bildirim_ajani.orchestrator import Orkestrator
from bildirim_ajani.report import excel_yaz, istatistik, numaralandir, yonetici_ozeti_yaz
from bildirim_ajani.schemas import ALAN_BASLIKLARI, AnalizSonucu, IzOlayi

st.set_page_config(page_title="Çağrı Bildirim Ajanı", page_icon=":telephone_receiver:", layout="wide")

SERI_RENGI = "#2a78d6"
SES_UZANTILARI = ("wav", "mp3", "m4a", "ogg", "flac")
IZ_ETIKETI = {
    "plan": ("PLAN", "#6250d6"),
    "ajan": ("AJAN", "#2a78d6"),
    "arac": ("ARAÇ", "#1baf7a"),
    "sonuc": ("SONUÇ", "#52514e"),
    "denetim": ("DENETİM", "#eb6834"),
    "revizyon": ("REVİZYON", "#e87ba4"),
    "guardrail": ("KURAL", "#c98500"),
    "uyari": ("UYARI", "#c98500"),
    "hata": ("HATA", "#d03b3b"),
    "bilgi": ("BİLGİ", "#52514e"),
}

st.markdown(
    """
<style>
.iz-satir {font-size: 0.86rem; line-height: 1.35; margin: 2px 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;}
.iz-etiket {display:inline-block; min-width: 74px; padding: 0 6px; margin-right: 6px; border-radius: 4px;
            color: #fff; font-size: 0.72rem; font-weight: 600; text-align:center;}
.iz-ajan {font-weight: 600;}
.alan-kart {border: 1px solid #e3e2dc; border-radius: 8px; padding: 10px 12px; background: #fff;}
.alan-kart .baslik {font-size: 0.75rem; color: #52514e; text-transform: uppercase; letter-spacing: .03em;}
.alan-kart .deger {font-size: 1.05rem; font-weight: 600; margin-top: 2px;}
.alan-kart .alt {font-size: 0.75rem; color: #6b6a65; margin-top: 4px;}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------- kaynaklar
@st.cache_resource(show_spinner="Ajanlar ve bilgi tabanı hazırlanıyor…")
def orkestrator_al() -> Orkestrator:
    return Orkestrator()


def ornek_dosyalar() -> list[Path]:
    dizin = ayarlari_yukle().veri_dizini / "ornek_cagrilar"
    if not dizin.exists():
        return []
    return sorted(p for p in dizin.rglob("*") if p.suffix.lower().lstrip(".") in SES_UZANTILARI + ("txt",))


def iz_html(e: IzOlayi) -> str:
    etiket, renk = IZ_ETIKETI.get(e.tur, ("•", "#52514e"))
    return f'<div class="iz-satir"><span class="iz-etiket" style="background:{renk}">{etiket}</span><span class="iz-ajan">{html.escape(e.ajan)}</span> — {html.escape(e.mesaj)}</div>'


def canli_calistir(gorev: Callable[[Callable[[IzOlayi], None]], AnalizSonucu], baslik: str) -> AnalizSonucu | None:
    """Analizi arka plan iş parçacığında çalıştırır, iz olaylarını canlı gösterir."""
    kuyruk: queue.Queue[IzOlayi | None] = queue.Queue()
    sonuc: dict[str, Any] = {}

    def is_parcacigi() -> None:
        try:
            sonuc["deger"] = gorev(kuyruk.put)
        except Exception as hata:  # arayüzde gösterilir
            sonuc["hata"] = hata
        finally:
            kuyruk.put(None)

    threading.Thread(target=is_parcacigi, daemon=True).start()
    with st.status(baslik, expanded=True) as durum:
        while (olay := kuyruk.get()) is not None:
            st.markdown(iz_html(olay), unsafe_allow_html=True)
        if "hata" in sonuc:
            durum.update(label=f"Analiz başarısız: {sonuc['hata']}", state="error")
            return None
        deger: AnalizSonucu = sonuc["deger"]
        etiket = "Hafızadaki sonuç getirildi" if deger.onbellekten else f"Analiz tamamlandı — {deger.sure_sn} sn, {deger.llm_kullanimi.get('cagri', 0)} model çağrısı"
        durum.update(label=etiket, state="complete", expanded=False)
    return deger


def bar_grafik(sayilar: dict[str, int], baslik: str) -> alt.Chart:
    """Tek seri yatay çubuk grafik: tek renk, uçta değer etiketi, ipucu, sade eksenler."""
    df = pd.DataFrame({"Kategori": list(sayilar), "Adet": list(sayilar.values())}).sort_values("Adet", ascending=False)
    sira = df["Kategori"].tolist()
    y = alt.Y("Kategori:N", sort=sira, scale=alt.Scale(paddingInner=0.4), axis=alt.Axis(title=None, labelLimit=240, labelColor="#0b0b0b", labelOverlap=False, domain=False, ticks=False))
    x = alt.X("Adet:Q", scale=alt.Scale(domain=[0, max(df["Adet"].max() * 1.15, 1)]), axis=alt.Axis(title=None, grid=True, gridColor="#ecebe6", tickMinStep=1, format="d", labelColor="#52514e", domain=False))
    taban = alt.Chart(df, title=alt.TitleParams(baslik, anchor="start", fontSize=14, fontWeight=600, color="#0b0b0b"))
    cubuk = taban.mark_bar(color=SERI_RENGI, cornerRadiusEnd=4).encode(x=x, y=y, tooltip=[alt.Tooltip("Kategori:N"), alt.Tooltip("Adet:Q")])
    etiket = taban.mark_text(align="left", dx=4, color="#52514e", fontSize=12).encode(x=x, y=y, text="Adet:Q")
    return (cubuk + etiket).properties(height=max(150, 38 * len(df))).configure_view(strokeWidth=0)


def alan_karti(baslik: str, deger: str, alt_metin: str) -> None:
    st.markdown(
        f'<div class="alan-kart"><div class="baslik">{html.escape(baslik)}</div><div class="deger">{html.escape(deger) or "—"}</div>'
        f'<div class="alt">{html.escape(alt_metin)}</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------- kenar çubuğu
ayarlar = ayarlari_yukle()
bilgi = bilgi_tabani()
orkestrator = orkestrator_al()

with st.sidebar:
    st.subheader("Çağrı Bildirim Ajanı")
    st.caption(
        "Çağrı merkezi görüşmelerinden SPK uyumlu aylık müşteri bildirim raporunu dolduran çoklu ajan sistemi."
    )
    st.markdown("**Sistem**")
    st.markdown(
        f"- Dil modeli: `{ayarlar.llm_model}`\n"
        f"- Kural arama (RAG): `{orkestrator.kurallar.mod}`\n"
        f"- Konuşma tanıma: `{'hazır' if asr_kullanilabilir() else 'kurulu değil'}`\n"
        f"- Revizyon hakkı: `{ayarlar.max_revizyon}` · Onay eşiği: `%{ayarlar.dusuk_guven_esigi}`"
    )
    if orkestrator.kurallar.hata:
        st.warning(orkestrator.kurallar.hata)
    if st.button("Bağlantıyı test et", use_container_width=True):
        with st.spinner("Model sunucusu kontrol ediliyor…"):
            durum = orkestrator.llm.saglik_kontrolu()
        (st.success if durum["llm"] else st.error)(f"LLM: {'erişilebilir' if durum['llm'] else 'erişilemiyor'} · Embedding: {'var' if durum['embedding'] else 'yok (BM25)'}")
        if durum["hata"]:
            st.caption(durum["hata"])
    st.markdown("**Hafıza**")
    hs = orkestrator.hafiza.istatistik()
    k1, k2, k3 = st.columns(3)
    k1.metric("Çağrı", hs["cagri"])
    k2.metric("Düzeltme", hs["duzeltme"])
    k3.metric("Onay bekl.", hs["insan_onayi_bekleyen"])
    st.markdown("**Oturum kullanımı**")
    st.json(orkestrator.llm.kullanim.ozet(), expanded=False)

sekme_analiz, sekme_rapor, sekme_hafiza, sekme_deger, sekme_mimari = st.tabs(
    ["Çağrı Analizi", "Toplu İşlem ve Aylık Rapor", "Hafıza ve Düzeltmeler", "Değerlendirme", "Mimari"]
)

# ---------------------------------------------------------------------------- 1) tek çağrı
with sekme_analiz:
    sol, sag = st.columns([0.42, 0.58], gap="large")
    with sol:
        st.markdown("#### Girdi")
        kaynak = st.radio("Kaynak", ["Örnek çağrı", "Transkript yapıştır", "Ses dosyası yükle"], horizontal=True, label_visibility="collapsed")
        transkript, dosya_adi, ses_yolu = "", "", None
        if kaynak == "Örnek çağrı":
            dosyalar = ornek_dosyalar()
            if not dosyalar:
                st.info("data/ornek_cagrilar klasöründe örnek yok.")
            else:
                secim = st.selectbox("Örnek kayıt", dosyalar, format_func=lambda p: ("[ses] " if p.suffix != ".txt" else "") + p.stem)
                if secim.suffix == ".txt":
                    transkript, dosya_adi = secim.read_text(encoding="utf-8"), secim.with_suffix(".wav").name
                    st.text_area("Transkript", transkript, height=320, disabled=True)
                else:
                    ses_yolu = secim
                    st.audio(str(secim))
        elif kaynak == "Transkript yapıştır":
            transkript = st.text_area("Transkript (TEMSİLCİ: / MÜŞTERİ: satırları)", height=300, placeholder="TEMSİLCİ: Örnek Portföy, ben Elif, nasıl yardımcı olabilirim?\nMÜŞTERİ: ...")
            dosya_adi = st.text_input("Kayıt dosya adı (isteğe bağlı)", placeholder="26.09.03_101522_12_ELIF_AKSOY_05550000123_08500000000_1.wav")
        else:
            yuklenen = st.file_uploader("Ses kaydı", type=list(SES_UZANTILARI))
            if yuklenen is not None:
                if not asr_kullanilabilir():
                    st.error("Konuşma tanıma için: pip install -r requirements-asr.txt")
                else:
                    # İstemciden gelen yol bilgisi atılır; dosya adı yalnızca meta veri (tarih/temsilci) için korunur
                    gecici = Path(tempfile.mkdtemp()) / Path(yuklenen.name).name
                    gecici.write_bytes(yuklenen.getbuffer())
                    ses_yolu = gecici
                    st.audio(yuklenen)
        zorla = st.checkbox("Hafızada varsa da yeniden analiz et", value=False)
        calistir = st.button("Analiz et", type="primary", use_container_width=True, disabled=not (transkript.strip() or ses_yolu))

    with sag:
        st.markdown("#### Ajan izi ve sonuç")
        if calistir:
            if ses_yolu is not None:
                yol = ses_yolu
                sonuc = canli_calistir(lambda d: orkestrator.sesten_analiz(yol, d, zorla), "Ses çözümleniyor ve ajanlar çalışıyor…")
            else:
                metin, ad = transkript, dosya_adi
                sonuc = canli_calistir(lambda d: orkestrator.metinden_analiz(metin, ad, d, zorla), "Ajanlar çalışıyor…")
            if sonuc is not None:
                st.session_state["son_sonuc"] = sonuc.model_dump()

        if "son_sonuc" in st.session_state:
            sonuc = AnalizSonucu.model_validate(st.session_state["son_sonuc"])
            satir = sonuc.satir
            if sonuc.insan_onayi_gerekli:
                st.warning("**İnsan onayı gerekli**\n\n" + "\n".join(f"- {n}" for n in sonuc.insan_onayi_nedenleri))
            else:
                st.success("Kural motoru ve denetçi ajan onayladı — satır otomatik olarak rapora girebilir.")
            if sonuc.tekrar_arayan:
                st.info(f"Tekrar arayan müşteri: bu numaradan daha önce {sonuc.onceki_cagri_sayisi} çağrı var.")

            ust = st.columns(3)
            alt_ = st.columns(3)
            for kutu, alan in zip(ust + alt_, ["bildirim_turu", "bildirimin_konusu", "muhatap_kurum", "fon_kodu", "bildirim_sahibi"]):
                a = sonuc.alanlar.get(alan)
                with kutu:
                    alan_karti(ALAN_BASLIKLARI[alan], satir.get(alan, ""), f"%{a.confidence} · {a.kaynak}" if a else "")
            with alt_[2]:
                alan_karti("Analiz güveni", f"%{satir.get('analiz_guveni', 0)}", f"{satir.get('tarih') or 'tarih yok'} · {satir.get('gorusulen_mt') or 'temsilci yok'}")

            st.markdown("**Bildirim Detayı**")
            st.write(satir.get("bildirim_detayi", ""))

            with st.expander("Gerekçeler (ajanların transkriptten kanıtı)"):
                for alan, a in sonuc.alanlar.items():
                    st.markdown(f"**{ALAN_BASLIKLARI[alan]}** — {html.escape(a.gerekce) or '—'}  \n<span style='color:#6b6a65;font-size:.8rem'>{html.escape(a.kaynak)}, güven %{a.confidence}</span>", unsafe_allow_html=True)
            with st.expander("Planlayıcının planı"):
                st.json(sonuc.plan.model_dump())
            with st.expander(f"Tam ajan izi ({len(sonuc.iz)} olay)"):
                st.markdown("".join(iz_html(e) for e in sonuc.iz), unsafe_allow_html=True)

            st.markdown("#### İş birimi düzeltmesi")
            st.caption("Yanlış bulduğunuz alanı düzeltin. Düzeltme hafızaya yazılır ve benzer çağrılarda ajanlara örnek olarak verilir.")
            with st.form("duzeltme"):
                e = bilgi.enumlar
                f1, f2, f3 = st.columns(3)
                yeni = {
                    "bildirim_turu": f1.selectbox("Bildirim Türü", e["bildirim_turu"], index=e["bildirim_turu"].index(satir["bildirim_turu"]) if satir["bildirim_turu"] in e["bildirim_turu"] else 0),
                    "bildirimin_konusu": f2.selectbox("Bildirimin Konusu", e["bildirimin_konusu"], index=e["bildirimin_konusu"].index(satir["bildirimin_konusu"]) if satir["bildirimin_konusu"] in e["bildirimin_konusu"] else 0),
                    "muhatap_kurum": f3.selectbox("Muhatap Kurum", e["muhatap_kurum"], index=e["muhatap_kurum"].index(satir["muhatap_kurum"]) if satir["muhatap_kurum"] in e["muhatap_kurum"] else 0),
                }
                g1, g2 = st.columns(2)
                yeni["fon_kodu"] = g1.text_input("Fon Kodu", satir["fon_kodu"])
                yeni["bildirim_sahibi"] = g2.text_input("Bildirim Sahibi", satir["bildirim_sahibi"])
                yeni["bildirim_detayi"] = st.text_area("Bildirim Detayı", satir["bildirim_detayi"], height=140)
                aciklama = st.text_input("Düzeltme gerekçesi", placeholder="Örn. Fon başka banka üzerinden alınmış, muhatap Diğer Kurumlar olmalı")
                if st.form_submit_button("Düzeltmeyi kaydet"):
                    degisen = [a for a, v in yeni.items() if str(v).strip() != str(satir.get(a, "")).strip()]
                    if not degisen:
                        st.info("Değişiklik yok.")
                    else:
                        for a in degisen:
                            orkestrator.hafiza.duzeltme_kaydet(sonuc.cagri_id, a, str(satir.get(a, "")), str(yeni[a]).strip(), aciklama)
                        guncel = orkestrator.hafiza.cagri_getir(sonuc.cagri_id)
                        if guncel:
                            st.session_state["son_sonuc"] = guncel.model_dump()
                        st.success(f"{len(degisen)} alan düzeltildi ve hafızaya yazıldı: {', '.join(ALAN_BASLIKLARI[a] for a in degisen)}")
        else:
            st.info("Soldan bir çağrı seçip **Analiz et**'e basın. Ajanların planı, araç çağrıları, denetim ve revizyon adımları burada canlı görünür.")

# ---------------------------------------------------------------------------- 2) toplu + rapor
with sekme_rapor:
    ust_sol, ust_sag = st.columns([0.6, 0.4])
    with ust_sol:
        st.markdown("#### Toplu işlem")
        dosyalar = ornek_dosyalar()
        st.caption(f"`data/ornek_cagrilar` içinde {len(dosyalar)} kayıt var. Daha önce işlenenler hafızadan gelir (tekrar işlenmez).")
        if st.button("Tüm örnek kayıtları işle", disabled=not dosyalar):
            ilerleme = st.progress(0.0, text="Başlıyor…")
            for i, yol in enumerate(dosyalar, start=1):
                ilerleme.progress((i - 1) / len(dosyalar), text=f"{i}/{len(dosyalar)} · {yol.stem[:60]}")
                try:
                    if yol.suffix == ".txt":
                        orkestrator.metinden_analiz(yol.read_text(encoding="utf-8"), yol.with_suffix(".wav").name)
                    elif asr_kullanilabilir():
                        orkestrator.sesten_analiz(yol)
                except Exception as hata:  # bir kayıttaki hata toplu işi durdurmaz
                    st.error(f"{yol.name} atlandı: {hata}")
            ilerleme.progress(1.0, text="Tamamlandı")
            st.rerun()

    satirlar = numaralandir(orkestrator.hafiza.tum_satirlar())
    if not satirlar:
        st.info("Henüz işlenmiş çağrı yok.")
    else:
        stats = istatistik(satirlar)
        m = st.columns(4)
        m[0].metric("Toplam bildirim", stats["toplam_bildirim"])
        m[1].metric("Şikayet oranı", f"%{stats['sikayet_orani_yuzde']}")
        m[2].metric("İnsan onayı bekleyen", stats["insan_onayi_bekleyen"])
        m[3].metric("Farklı fon", len(stats["en_cok_gecen_fonlar"]))

        g1, g2, g3 = st.columns(3)
        g1.altair_chart(bar_grafik(stats["tur_dagilimi"], "Bildirim türü"), use_container_width=True)
        g2.altair_chart(bar_grafik(stats["konu_dagilimi"], "Bildirimin konusu"), use_container_width=True)
        g3.altair_chart(bar_grafik(stats["muhatap_dagilimi"], "Muhatap kurum"), use_container_width=True)

        st.markdown("#### Kümüle rapor")
        df = pd.DataFrame(satirlar)
        kolonlar = ["bildirim_no", "tarih", "gorusulen_mt", "bildirim_turu", "bildirim_sahibi", "muhatap_kurum", "fon_kodu", "bildirimin_konusu", "bildirim_detayi", "analiz_guveni", "insan_onayi_gerekli"]
        st.dataframe(
            df[[k for k in kolonlar if k in df.columns]].rename(columns={**ALAN_BASLIKLARI, "bildirim_no": "No", "tarih": "Tarih", "gorusulen_mt": "Temsilci", "analiz_guveni": "Güven", "insan_onayi_gerekli": "Onay gerekli"}),
            use_container_width=True,
            hide_index=True,
            height=360,
        )

        st.markdown("#### Rapor Ajanı — yönetici özeti")
        if st.button("Yönetici özeti üret"):
            with st.spinner("Rapor Ajanı yazıyor…"):
                st.session_state["yonetici_ozeti"] = yonetici_ozeti_yaz(orkestrator.llm, stats, satirlar)
        ozet = st.session_state.get("yonetici_ozeti")
        if ozet:
            st.write(ozet["ozet"])
            c1, c2 = st.columns(2)
            c1.markdown("**Öne çıkanlar**\n" + "\n".join(f"- {x}" for x in ozet["one_cikanlar"]))
            c2.markdown("**Öneriler**\n" + "\n".join(f"- {x}" for x in ozet["oneriler"]))
            for u in ozet.get("uyarilar", []):
                st.warning(u)

        cikti = ayarlar.veri_dizini / "ciktilar" / "aylik_bildirim_raporu.xlsx"
        excel_yaz(satirlar, cikti, stats, ozet)
        st.download_button("Excel raporunu indir", cikti.read_bytes(), file_name=cikti.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

# ---------------------------------------------------------------------------- 3) hafıza
with sekme_hafiza:
    st.markdown("#### İş birimi düzeltmeleri (geri bildirimden öğrenme)")
    st.caption("Bu düzeltmeler, benzer transkriptlerde Sınıflandırma ve Fon ajanlarının mesajına örnek olarak eklenir; ajanlar `gecmis_duzeltmeler` aracıyla da sorgulayabilir.")
    duzeltmeler = orkestrator.hafiza.duzeltmeler()
    if duzeltmeler:
        st.dataframe(pd.DataFrame(duzeltmeler).rename(columns={"cagri_id": "Çağrı", "alan": "Alan", "eski": "Eski", "yeni": "Yeni", "aciklama": "Gerekçe", "olusturma": "Zaman"}), use_container_width=True, hide_index=True)
    else:
        st.info("Henüz düzeltme yok. Çağrı Analizi sekmesindeki formdan ekleyebilirsiniz.")

    st.markdown("#### İşlenmiş çağrılar")
    sonuclar = orkestrator.hafiza.tum_sonuclar()
    if sonuclar:
        tablo = [
            {"Çağrı": s.cagri_id, "Tarih": s.satir.get("tarih"), "Telefon": s.satir.get("telefon"), "Tür": s.satir.get("bildirim_turu"), "Tekrar arayan": s.tekrar_arayan, "Onay gerekli": s.insan_onayi_gerekli, "Süre (sn)": s.sure_sn, "Model çağrısı": s.llm_kullanimi.get("cagri", 0)}
            for s in sonuclar
        ]
        st.dataframe(pd.DataFrame(tablo), use_container_width=True, hide_index=True)
    with st.expander("Hafızayı temizle"):
        if st.checkbox("Tüm çağrı ve düzeltmeleri silmek istediğimi onaylıyorum") and st.button("Temizle"):
            orkestrator.hafiza.temizle()
            st.session_state.pop("son_sonuc", None)
            st.rerun()

# ---------------------------------------------------------------------------- 4) değerlendirme
with sekme_deger:
    st.markdown("#### Ajan sistemi mi, tek LLM çağrısı mı?")
    st.caption(
        "Aynı maskeli altın etiketli set üzerinde iki yaklaşım karşılaştırılır. Tek çağrı: tüm kural kitabı ve fon sözlüğü tek prompta "
        "verilir; araç, denetim, revizyon ve kural motoru yoktur. Komut: `python -m bildirim_ajani degerlendir --mod ikisi`"
    )
    sonuc_dizini = ayarlar.veri_dizini / "degerlendirme" / "sonuclar"
    ozetler = {}
    for mod in ("tek_cagri", "ajan"):
        yol = sonuc_dizini / f"{mod}_ozet.json"
        if yol.exists():
            ozetler[mod] = json.loads(yol.read_text(encoding="utf-8"))
    if not ozetler:
        st.info("Henüz değerlendirme sonucu yok.")
    else:
        adlar = {"tek_cagri": "Tek LLM çağrısı", "ajan": "Çoklu ajan sistemi"}
        satirlar_d = []
        for alan in ["bildirim_turu", "bildirimin_konusu", "muhatap_kurum", "fon_kodu", "bildirim_sahibi"]:
            satir_d = {"Alan": ALAN_BASLIKLARI[alan]}
            for mod, oz in ozetler.items():
                satir_d[adlar[mod]] = oz["alan_dogrulugu_yuzde"][alan]
            satirlar_d.append(satir_d)
        for etiket, anahtar in [("Tam doğru satır", "tam_dogru_satir_yuzde"), ("Fon kodu kesinlik", "fon_kodu_kesinlik_yuzde"), ("Fon kodu duyarlılık", "fon_kodu_duyarlilik_yuzde")]:
            satir_d = {"Alan": etiket}
            for mod, oz in ozetler.items():
                satir_d[adlar[mod]] = oz[anahtar]
            satirlar_d.append(satir_d)
        st.dataframe(pd.DataFrame(satirlar_d), use_container_width=True, hide_index=True)
        stres = {}
        for mod in ("tek_cagri", "ajan"):
            yol = sonuc_dizini / f"{mod}_asr_stres_ozet.json"
            if yol.exists():
                stres[adlar[mod]] = json.loads(yol.read_text(encoding="utf-8"))
        if stres:
            st.markdown("**ASR stres testi** — fon kodları harf harf okunmuş gibi yazıldığında (\"ORT\" → \"o re te\")")
            st.dataframe(
                pd.DataFrame(
                    [{"Yaklaşım": ad, "Vaka": oz["vaka"], "Fon kodu doğruluğu": oz["alan_dogrulugu_yuzde"]["fon_kodu"], "Kesinlik": oz["fon_kodu_kesinlik_yuzde"], "Duyarlılık": oz["fon_kodu_duyarlilik_yuzde"]} for ad, oz in stres.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
        c = st.columns(len(ozetler))
        for kutu, (mod, oz) in zip(c, ozetler.items()):
            kutu.metric(f"{adlar[mod]} — vaka", oz["vaka"])
            kutu.caption(f"Ortalama {oz['ortalama_sure_sn']} sn ve {oz['ortalama_llm_cagrisi']} model çağrısı / kayıt · insan onayına düşen: {oz['insan_onayina_dusen']} · model: `{oz['model']}`")

# ---------------------------------------------------------------------------- 5) mimari
with sekme_mimari:
    st.markdown("#### Ajan akışı")
    st.graphviz_chart(
        """
digraph {
  rankdir=TB; bgcolor="transparent"; nodesep=0.35; ranksep=0.45; compound=true;
  node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#c9c8c1", fontname="Helvetica", fontsize=13, margin="0.18,0.08"];
  edge [color="#8a8984", fontname="Helvetica", fontsize=11, arrowsize=0.7];
  ses [label="Ses kaydı\nWhisper + Rol Ajanı"]; metin [label="Transkript"];
  on [label="Ön işleme\nkişisel veri maskeleme · ASR düzeltme"];
  plan [label="Planlayıcı Ajan\nrota + gerekli ajanlar", fillcolor="#efedfb"];
  haf [label="Hafıza (SQLite)\ntekrar işleme · tekrar arayan\niş birimi düzeltmeleri", fillcolor="#eef4fc"];
  rag [label="Kural Kitabı RAG\nembedding + BM25", fillcolor="#eef4fc"];
  subgraph cluster_uzman { label="Uzman ajanlar (paralel)"; fontname="Helvetica"; fontsize=12; color="#d9d8d2"; style="rounded";
    sin [label="Sınıflandırma\ntür · konu · muhatap"]; fon [label="Fon Kodu\nkod tarama · fon arama"]; kim [label="Kimlik\narayan adı"]; }
  oz [label="Özet Ajanı\nbildirim detayı"];
  km [label="Kural Motoru\ndeterministik", fillcolor="#fdf3e1"]; den [label="Denetçi Ajan", fillcolor="#fdeee8"];
  rev [label="Hedefli revizyon\nsorumlu ajana geri bildirim", fillcolor="#fde9f0"];
  sat [label="Rapor satırı\n+ insan onayı kararı"]; rap [label="Rapor Ajanı\nExcel + yönetici özeti"];
  {rank=same; ses; metin;} {rank=same; plan; haf; rag;} {rank=same; km; den; rev;} {rank=same; sat; rap;}
  ses -> on; metin -> on; on -> plan; haf -> plan [style=dashed, label=" geçmiş"];
  plan -> fon [lhead=cluster_uzman];
  rag -> fon [style=dashed, lhead=cluster_uzman, label=" kurallar"]; haf -> sin [style=dashed, lhead=cluster_uzman, label=" few-shot"];
  fon -> oz [ltail=cluster_uzman];
  oz -> km; km -> den; den -> rev [label=" sorun var"]; rev -> kim [lhead=cluster_uzman, style=dashed, constraint=false];
  den -> sat [label=" onay / hak bitti"]; sat -> rap; sat -> haf [style=dashed, label=" kaydet", constraint=false];
}
"""
    )
    st.markdown(
        "- **Planlama:** Planlayıcı, içeriksiz çağrıyı (hat kesildi) model çağırmadan ayırır, gerekmeyen ajanları atlar.\n"
        "- **Araç kullanımı:** fon sözlüğü arama, transkriptte kod tarama, kural arama, temsilci kontrolü, özel fon eşleşmesi, geçmiş düzeltmeler.\n"
        "- **Hafıza:** kısa süreli (çağrı durumu, ajanlar arası kararlar) ve uzun süreli (SQLite: çağrılar, tekrar arayanlar, düzeltmeler).\n"
        "- **Çok adımlı akıl yürütme ve öz-denetim:** Kural Motoru + Denetçi Ajan → ilgili ajana hedefli revizyon → çözülemeyen insan onayına.\n"
        "- **Çoklu ajan koordinasyonu:** bağımsız ajanlar paralel, bağımlı Özet Ajanı onların kararlarıyla çalışır."
    )
