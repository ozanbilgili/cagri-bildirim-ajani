"""Kural kitabı üzerinde hibrit (embedding + BM25) arama.

Embedding sunucusu yoksa veya hata verirse sistem sessizce BM25'e düşer; arama hiçbir
zaman analizi durdurmaz.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np

from .knowledge_base import BilgiTabani, KuralParcasi, ascii_katla

log = logging.getLogger(__name__)


class Gomucu(Protocol):
    def embed(self, metinler: list[str]) -> list[list[float]]: ...


def kelimelere_ayir(metin: str) -> list[str]:
    """ASCII'ye katlanmış, 2+ harfli kelimeler (basit Türkçe kök kırpma ile)."""
    kelimeler = re.findall(r"[a-z0-9]{2,}", ascii_katla(metin))
    return [k[:6] for k in kelimeler]  # kaba kök: 'satamiyorum' ~ 'satamı', ek farklarını yumuşatır


class BM25:
    """Bağımlılıksız küçük BM25 uygulaması."""

    def __init__(self, belgeler: list[str], k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.belgeler = [kelimelere_ayir(d) for d in belgeler]
        self.ort_uzunluk = sum(len(d) for d in self.belgeler) / max(len(self.belgeler), 1)
        df: Counter[str] = Counter()
        for d in self.belgeler:
            df.update(set(d))
        n = len(self.belgeler)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.belgeler]

    def skorla(self, sorgu: str) -> list[float]:
        terimler = kelimelere_ayir(sorgu)
        skorlar = []
        for tf, belge in zip(self.tf, self.belgeler):
            skor = 0.0
            for t in terimler:
                if t not in tf:
                    continue
                pay = tf[t] * (self.k1 + 1)
                payda = tf[t] + self.k1 * (1 - self.b + self.b * len(belge) / (self.ort_uzunluk or 1))
                skor += self.idf.get(t, 0) * pay / payda
            skorlar.append(skor)
        return skorlar


def _normalize(skorlar: np.ndarray) -> np.ndarray:
    if skorlar.size == 0:
        return skorlar
    en_kucuk, en_buyuk = float(skorlar.min()), float(skorlar.max())
    if en_buyuk - en_kucuk < 1e-9:
        return np.zeros_like(skorlar)
    return (skorlar - en_kucuk) / (en_buyuk - en_kucuk)


class KuralDeposu:
    """Kural parçalarını indeksler ve alan filtresiyle hibrit arama yapar."""

    def __init__(self, bilgi: BilgiTabani, gomucu: Gomucu | None, onbellek_dizini: Path | None = None) -> None:
        self.parcalar: list[KuralParcasi] = bilgi.kural_parcalari
        self.bm25 = BM25([p.metin for p in self.parcalar])
        self.gomucu = gomucu
        self.onbellek_dizini = onbellek_dizini
        self.vektorler: np.ndarray | None = None
        self.mod = "bm25"
        self.hata = ""
        if gomucu is not None:
            self._vektorleri_hazirla()

    def _vektorleri_hazirla(self) -> None:
        icerik_ozeti = hashlib.sha256("\n".join(p.metin for p in self.parcalar).encode()).hexdigest()[:16]
        model_adi = getattr(getattr(self.gomucu, "ayarlar", None), "embedding_model", "model")
        dosya = None
        if self.onbellek_dizini:
            dosya = self.onbellek_dizini / f"kurallar_{re.sub(r'[^a-zA-Z0-9]', '_', model_adi)}_{icerik_ozeti}.npy"
            if dosya.exists():
                self.vektorler = np.load(dosya)
                self.mod = "hibrit"
                return
        try:
            vektorler = np.asarray(self.gomucu.embed([p.metin for p in self.parcalar]), dtype=np.float32)
        except Exception as hata:  # ağ/model hatası: BM25 ile devam
            self.hata = f"Embedding alınamadı, BM25 kullanılıyor: {hata}"
            log.warning(self.hata)
            return
        vektorler /= np.linalg.norm(vektorler, axis=1, keepdims=True) + 1e-9
        self.vektorler = vektorler
        self.mod = "hibrit"
        if dosya:
            dosya.parent.mkdir(parents=True, exist_ok=True)
            np.save(dosya, vektorler)

    def ara(self, sorgu: str, alanlar: str = "GDKIJLE", k: int = 4) -> list[tuple[KuralParcasi, float]]:
        """Sorguya en ilgili k kuralı döndürür (yalnızca verilen alan harflerinden)."""
        if not sorgu.strip():
            return []
        bm25 = _normalize(np.asarray(self.bm25.skorla(sorgu), dtype=np.float32))
        skorlar = bm25
        if self.vektorler is not None and self.gomucu is not None:
            try:
                q = np.asarray(self.gomucu.embed([sorgu[:4000]])[0], dtype=np.float32)
                q /= np.linalg.norm(q) + 1e-9
                kosinus = _normalize(self.vektorler @ q)
                skorlar = 0.65 * kosinus + 0.35 * bm25
            except Exception as hata:
                self.hata = f"Sorgu embedding'i alınamadı, BM25 kullanıldı: {hata}"
        sirali = sorted(
            ((p, float(s)) for p, s in zip(self.parcalar, skorlar) if p.alan in alanlar),
            key=lambda x: -x[1],
        )
        return sirali[:k]

    def ara_json(self, sorgu: str, alanlar: str = "GDKIJLE", k: int = 3) -> str:
        """Araç çağrısı için kısa JSON çıktı."""
        return json.dumps(
            [{"kural": p.id, "metin": p.metin, "skor": round(s, 2)} for p, s in self.ara(sorgu, alanlar, k)],
            ensure_ascii=False,
        )
