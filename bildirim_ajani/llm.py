"""OpenAI uyumlu sohbet/embedding istemcisi.

Ollama, vLLM, LM Studio veya OpenAI uyumlu herhangi bir sağlayıcı ile çalışır; sağlayıcı
ve model .env üzerinden seçilir. Yeniden deneme, zaman aşımı ve JSON onarımı burada toplanır
ki ajanlar sadece kendi işine odaklansın.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import OpenAI

from .config import Ayarlar, ayarlari_yukle


class LLMHatasi(RuntimeError):
    """Model çağrısı yeniden denemelere rağmen başarısız olduğunda fırlatılır."""


@dataclass
class AracCagrisi:
    id: str
    ad: str
    argumanlar: dict[str, Any]
    ham_argumanlar: str


@dataclass
class LLMYaniti:
    icerik: str
    arac_cagrilari: list[AracCagrisi]
    girdi_token: int = 0
    cikti_token: int = 0
    sure_sn: float = 0.0

    def asistan_mesaji(self) -> dict[str, Any]:
        """Sohbet geçmişine eklenecek asistan mesajını üretir."""
        mesaj: dict[str, Any] = {"role": "assistant", "content": self.icerik or ""}
        if self.arac_cagrilari:
            mesaj["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.ad, "arguments": c.ham_argumanlar},
                }
                for c in self.arac_cagrilari
            ]
        return mesaj


@dataclass
class Kullanim:
    """Oturum boyunca biriken çağrı istatistikleri."""

    cagri: int = 0
    girdi_token: int = 0
    cikti_token: int = 0
    toplam_sure_sn: float = 0.0
    hata: int = 0
    _kilit: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def ekle(self, yanit: LLMYaniti) -> None:
        with self._kilit:
            self.cagri += 1
            self.girdi_token += yanit.girdi_token
            self.cikti_token += yanit.cikti_token
            self.toplam_sure_sn += yanit.sure_sn

    def ozet(self) -> dict[str, Any]:
        return {
            "cagri": self.cagri,
            "girdi_token": self.girdi_token,
            "cikti_token": self.cikti_token,
            "sure_sn": round(self.toplam_sure_sn, 1),
            "hata": self.hata,
        }


_JSON_BLOK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def json_ayikla(metin: str) -> dict[str, Any]:
    """Model çıktısından ilk JSON nesnesini çıkarır (kod bloğu, ön/son metin toleranslı)."""
    if not metin or not metin.strip():
        raise ValueError("boş yanıt")
    aday = metin.strip()
    blok = _JSON_BLOK.search(aday)
    if blok:
        aday = blok.group(1).strip()
    try:
        veri = json.loads(aday)
        if isinstance(veri, dict):
            return veri
    except json.JSONDecodeError:
        pass
    bas = aday.find("{")
    son = aday.rfind("}")
    if bas == -1 or son <= bas:
        raise ValueError("yanıtta JSON nesnesi yok")
    veri = json.loads(aday[bas : son + 1])
    if not isinstance(veri, dict):
        raise ValueError("JSON nesnesi bekleniyordu")
    return veri


class LLMIstemci:
    """Sohbet, araç çağırma, JSON çıktı ve embedding için tek giriş noktası."""

    def __init__(self, ayarlar: Ayarlar | None = None) -> None:
        self.ayarlar = ayarlar or ayarlari_yukle()
        self._istemci = OpenAI(
            base_url=self.ayarlar.llm_base_url,
            api_key=self.ayarlar.llm_api_key or "yerel",
            timeout=self.ayarlar.llm_timeout,
            max_retries=0,
        )
        self._embed_istemci = OpenAI(
            base_url=self.ayarlar.embedding_url,
            api_key=self.ayarlar.llm_api_key or "yerel",
            timeout=60,
            max_retries=0,
        )
        self.kullanim = Kullanim()

    @property
    def model(self) -> str:
        return self.ayarlar.llm_model

    def sohbet(
        self,
        mesajlar: list[dict[str, Any]],
        araclar: list[dict[str, Any]] | None = None,
        json_modu: bool = False,
        sicaklik: float | None = None,
    ) -> LLMYaniti:
        """Tek bir sohbet çağrısı yapar; geçici hatalarda üstel bekleme ile yeniden dener."""
        parametreler: dict[str, Any] = {
            "model": self.ayarlar.llm_model,
            "messages": mesajlar,
            "temperature": self.ayarlar.llm_temperature if sicaklik is None else sicaklik,
        }
        if araclar:
            parametreler["tools"] = araclar
        if json_modu:
            parametreler["response_format"] = {"type": "json_object"}
        if self.ayarlar.llm_reasoning_effort:
            parametreler["extra_body"] = {"reasoning_effort": self.ayarlar.llm_reasoning_effort}

        son_hata: Exception | None = None
        for deneme in range(self.ayarlar.llm_max_retries + 1):
            baslangic = time.perf_counter()
            try:
                cevap = self._istemci.chat.completions.create(**parametreler)
            except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError) as hata:
                son_hata = hata
            except openai.APIStatusError as hata:
                if hata.status_code < 500:
                    self.kullanim.hata += 1
                    raise LLMHatasi(f"Model isteği reddedildi ({hata.status_code}): {hata.message}") from hata
                son_hata = hata
            else:
                yanit = self._yaniti_coz(cevap, time.perf_counter() - baslangic)
                self.kullanim.ekle(yanit)
                return yanit
            if deneme < self.ayarlar.llm_max_retries:
                time.sleep(min(2**deneme, 8))
        self.kullanim.hata += 1
        raise LLMHatasi(f"Model {self.ayarlar.llm_max_retries + 1} denemede yanıt vermedi: {son_hata}")

    def json_iste(self, mesajlar: list[dict[str, Any]], sicaklik: float | None = None) -> dict[str, Any]:
        """JSON çıktı ister; ayrıştırılamazsa hatayı modele gösterip bir kez onarım ister."""
        yanit = self.sohbet(mesajlar, json_modu=True, sicaklik=sicaklik)
        try:
            return json_ayikla(yanit.icerik)
        except (ValueError, json.JSONDecodeError) as hata:
            onarim = mesajlar + [
                {"role": "assistant", "content": yanit.icerik or ""},
                {
                    "role": "user",
                    "content": f"Yanıtın geçerli JSON değil ({hata}). Sadece istenen JSON nesnesini döndür.",
                },
            ]
            yanit = self.sohbet(onarim, json_modu=True, sicaklik=0)
            return json_ayikla(yanit.icerik)

    def embed(self, metinler: list[str]) -> list[list[float]]:
        """Metinlerin embedding vektörlerini döndürür."""
        cevap = self._embed_istemci.embeddings.create(model=self.ayarlar.embedding_model, input=metinler)
        return [d.embedding for d in cevap.data]

    def saglik_kontrolu(self) -> dict[str, Any]:
        """Model sunucusuna erişimi ve modelin varlığını kontrol eder."""
        durum: dict[str, Any] = {"llm": False, "embedding": False, "model": self.model, "hata": ""}
        try:
            self.sohbet([{"role": "user", "content": "Sadece 'tamam' yaz."}], sicaklik=0)
            durum["llm"] = True
        except LLMHatasi as hata:
            durum["hata"] = str(hata)
        try:
            self.embed(["test"])
            durum["embedding"] = True
        except Exception as hata:  # embedding yoksa sistem BM25 ile çalışmaya devam eder
            durum["hata"] = (durum["hata"] + f" | embedding: {hata}").strip(" |")
        return durum

    @staticmethod
    def _yaniti_coz(cevap: Any, sure: float) -> LLMYaniti:
        mesaj = cevap.choices[0].message
        cagrilar: list[AracCagrisi] = []
        for cagri in mesaj.tool_calls or []:
            ham = cagri.function.arguments or "{}"
            try:
                argumanlar = json.loads(ham) if ham.strip() else {}
            except json.JSONDecodeError:
                argumanlar = {"_ayrisma_hatasi": ham}
            cagrilar.append(AracCagrisi(id=cagri.id, ad=cagri.function.name, argumanlar=argumanlar, ham_argumanlar=ham))
        kullanim = getattr(cevap, "usage", None)
        return LLMYaniti(
            icerik=mesaj.content or "",
            arac_cagrilari=cagrilar,
            girdi_token=getattr(kullanim, "prompt_tokens", 0) or 0,
            cikti_token=getattr(kullanim, "completion_tokens", 0) or 0,
            sure_sn=sure,
        )
