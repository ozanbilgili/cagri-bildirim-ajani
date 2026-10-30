"""Araç çağırabilen ajan döngüsü (ReAct benzeri: düşün → araç çağır → gözlemle → karar ver)."""

from __future__ import annotations

import json
from typing import Any, Callable

from ..llm import LLMIstemci, json_ayikla
from ..schemas import IzOlayi
from ..tools import AracKutusu

IzFonksiyonu = Callable[[IzOlayi], None]


def _kisalt(metin: str, uzunluk: int = 400) -> str:
    return metin if len(metin) <= uzunluk else metin[:uzunluk] + "…"


class AracliAjan:
    """Sistem mesajı + araç seti ile çalışan, sonunda JSON karar döndüren ajan."""

    ad: str = "Ajan"
    arac_adlari: list[str] = []

    def __init__(self, llm: LLMIstemci, max_adim: int = 5) -> None:
        self.llm = llm
        self.max_adim = max_adim

    def sistem_mesaji(self) -> str:
        raise NotImplementedError

    def calistir(self, kullanici_mesaji: str, kutu: AracKutusu | None, iz: IzFonksiyonu) -> dict[str, Any]:
        """Ajanı çalıştırır; araç çağrılarını yürütür ve son JSON kararı döndürür."""
        mesajlar: list[dict[str, Any]] = [
            {"role": "system", "content": self.sistem_mesaji()},
            {"role": "user", "content": kullanici_mesaji},
        ]
        semalar = kutu.semalar() if kutu and self.arac_adlari else None

        for _ in range(self.max_adim):
            yanit = self.llm.sohbet(mesajlar, araclar=semalar)
            if yanit.arac_cagrilari and kutu is not None:
                mesajlar.append(yanit.asistan_mesaji())
                for cagri in yanit.arac_cagrilari:
                    sonuc = kutu.calistir(cagri.ad, cagri.argumanlar)
                    iz(
                        IzOlayi(
                            tur="arac",
                            ajan=self.ad,
                            mesaj=f"{cagri.ad}({json.dumps(cagri.argumanlar, ensure_ascii=False)})",
                            veri={"sonuc": _kisalt(sonuc)},
                        )
                    )
                    mesajlar.append({"role": "tool", "tool_call_id": cagri.id, "content": sonuc})
                continue
            try:
                return json_ayikla(yanit.icerik)
            except (ValueError, json.JSONDecodeError) as hata:
                iz(IzOlayi(tur="uyari", ajan=self.ad, mesaj=f"Geçersiz JSON, düzeltme isteniyor: {hata}"))
                mesajlar.append({"role": "assistant", "content": yanit.icerik or ""})
                mesajlar.append({"role": "user", "content": "Yanıtın geçerli JSON değil. Sadece istenen JSON nesnesini döndür."})

        iz(IzOlayi(tur="uyari", ajan=self.ad, mesaj="Adım sınırına ulaşıldı; araçsız son karar isteniyor."))
        mesajlar.append({"role": "user", "content": "Araç kullanma hakkın bitti. Topladığın bilgilerle SADECE final JSON'u döndür."})
        return self.llm.json_iste(mesajlar, sicaklik=0)
