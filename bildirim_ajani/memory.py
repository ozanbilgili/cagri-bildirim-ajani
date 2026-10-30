"""Uzun süreli hafıza (SQLite).

- İşlenmiş çağrılar: aynı kayıt ikinci kez işlenmez, aynı numaradan tekrar arayanlar bulunur.
- İş birimi düzeltmeleri: kullanıcının arayüzde düzelttiği alanlar saklanır ve benzer
  çağrılarda ajanlara örnek olarak geri verilir (geri bildirimden öğrenme).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .rag import BM25
from .schemas import AnalizSonucu

_SEMA = """
CREATE TABLE IF NOT EXISTS cagrilar (
    id TEXT PRIMARY KEY,
    dosya_adi TEXT,
    telefon TEXT,
    tarih TEXT,
    temsilci TEXT,
    transkript TEXT,
    satir_json TEXT,
    sonuc_json TEXT,
    insan_onayi INTEGER DEFAULT 0,
    olusturma TEXT
);
CREATE INDEX IF NOT EXISTS ix_cagrilar_telefon ON cagrilar(telefon);
CREATE TABLE IF NOT EXISTS duzeltmeler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cagri_id TEXT,
    alan TEXT,
    eski TEXT,
    yeni TEXT,
    aciklama TEXT,
    transkript_ozeti TEXT,
    olusturma TEXT
);
"""


def cagri_kimligi(icerik: str | bytes) -> str:
    """Kayıt içeriğinden kararlı kimlik üretir (tekrar işlemeyi önlemek için)."""
    veri = icerik.encode("utf-8") if isinstance(icerik, str) else icerik
    return hashlib.sha256(veri).hexdigest()[:16]


class Hafiza:
    """SQLite tabanlı kalıcı hafıza."""

    def __init__(self, yol: Path) -> None:
        self.yol = yol
        yol.parent.mkdir(parents=True, exist_ok=True)
        with self._baglanti() as db:
            db.executescript(_SEMA)

    @contextmanager
    def _baglanti(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.yol, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------ çağrılar
    def cagri_kaydet(self, sonuc: AnalizSonucu, transkript: str) -> None:
        satir = sonuc.satir
        with self._baglanti() as db:
            db.execute(
                """INSERT OR REPLACE INTO cagrilar
                   (id, dosya_adi, telefon, tarih, temsilci, transkript, satir_json, sonuc_json, insan_onayi, olusturma)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sonuc.cagri_id,
                    satir.get("dosya_adi", ""),
                    satir.get("telefon", ""),
                    satir.get("tarih", ""),
                    satir.get("gorusulen_mt", ""),
                    transkript,
                    json.dumps(satir, ensure_ascii=False),
                    sonuc.model_dump_json(),
                    int(sonuc.insan_onayi_gerekli),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def cagri_getir(self, cagri_id: str) -> AnalizSonucu | None:
        with self._baglanti() as db:
            kayit = db.execute("SELECT sonuc_json FROM cagrilar WHERE id = ?", (cagri_id,)).fetchone()
        return AnalizSonucu.model_validate_json(kayit["sonuc_json"]) if kayit else None

    def cagri_sil(self, cagri_id: str) -> None:
        with self._baglanti() as db:
            db.execute("DELETE FROM cagrilar WHERE id = ?", (cagri_id,))

    def arayan_gecmisi(self, telefon: str, haric_id: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Aynı numaradan daha önce gelen çağrıların özetleri."""
        if not telefon:
            return []
        with self._baglanti() as db:
            kayitlar = db.execute(
                "SELECT id, tarih, satir_json FROM cagrilar WHERE telefon = ? AND id != ? ORDER BY tarih DESC LIMIT ?",
                (telefon, haric_id, limit),
            ).fetchall()
        gecmis = []
        for k in kayitlar:
            satir = json.loads(k["satir_json"])
            gecmis.append(
                {
                    "cagri_id": k["id"],
                    "tarih": k["tarih"],
                    "bildirim_turu": satir.get("bildirim_turu", ""),
                    "bildirimin_konusu": satir.get("bildirimin_konusu", ""),
                    "ozet": (satir.get("bildirim_detayi", "") or "")[:220],
                }
            )
        return gecmis

    def tum_satirlar(self) -> list[dict[str, Any]]:
        with self._baglanti() as db:
            kayitlar = db.execute("SELECT satir_json, insan_onayi FROM cagrilar ORDER BY tarih, olusturma").fetchall()
        satirlar = []
        for k in kayitlar:
            satir = json.loads(k["satir_json"])
            satir["insan_onayi_gerekli"] = bool(k["insan_onayi"])
            satirlar.append(satir)
        return satirlar

    def tum_sonuclar(self) -> list[AnalizSonucu]:
        with self._baglanti() as db:
            kayitlar = db.execute("SELECT sonuc_json FROM cagrilar ORDER BY tarih, olusturma").fetchall()
        return [AnalizSonucu.model_validate_json(k["sonuc_json"]) for k in kayitlar]

    # ------------------------------------------------------------------ düzeltmeler
    def duzeltme_kaydet(self, cagri_id: str, alan: str, eski: str, yeni: str, aciklama: str = "") -> None:
        """İş birimi düzeltmesini kaydeder ve çağrının rapor satırını günceller."""
        with self._baglanti() as db:
            kayit = db.execute("SELECT transkript, satir_json, sonuc_json FROM cagrilar WHERE id = ?", (cagri_id,)).fetchone()
            if kayit is None:
                raise KeyError(f"Çağrı bulunamadı: {cagri_id}")
            ozet = (kayit["transkript"] or "")[:1500]
            db.execute(
                """INSERT INTO duzeltmeler (cagri_id, alan, eski, yeni, aciklama, transkript_ozeti, olusturma)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cagri_id, alan, eski, yeni, aciklama, ozet, datetime.now().isoformat(timespec="seconds")),
            )
            satir = json.loads(kayit["satir_json"])
            satir[alan] = yeni
            sonuc = AnalizSonucu.model_validate_json(kayit["sonuc_json"])
            sonuc.satir = satir
            if alan in sonuc.alanlar:
                sonuc.alanlar[alan].value = yeni
                sonuc.alanlar[alan].kaynak = "iş birimi düzeltmesi"
                sonuc.alanlar[alan].confidence = 100
            db.execute(
                "UPDATE cagrilar SET satir_json = ?, sonuc_json = ? WHERE id = ?",
                (json.dumps(satir, ensure_ascii=False), sonuc.model_dump_json(), cagri_id),
            )

    def duzeltmeler(self) -> list[dict[str, Any]]:
        with self._baglanti() as db:
            kayitlar = db.execute(
                "SELECT id, cagri_id, alan, eski, yeni, aciklama, olusturma FROM duzeltmeler ORDER BY id DESC"
            ).fetchall()
        return [dict(k) for k in kayitlar]

    def benzer_duzeltmeler(self, transkript: str, alanlar: tuple[str, ...] | None = None, k: int = 3) -> list[dict[str, Any]]:
        """Bu transkripte en çok benzeyen geçmiş düzeltmeleri döndürür (few-shot örnek)."""
        with self._baglanti() as db:
            kayitlar = [dict(r) for r in db.execute("SELECT * FROM duzeltmeler").fetchall()]
        if alanlar:
            kayitlar = [r for r in kayitlar if r["alan"] in alanlar]
        if not kayitlar:
            return []
        bm25 = BM25([f"{r['transkript_ozeti']} {r['aciklama']}" for r in kayitlar])
        skorlar = bm25.skorla(transkript[:3000])
        sirali = sorted(zip(kayitlar, skorlar), key=lambda x: -x[1])
        return [
            {"alan": r["alan"], "eski": r["eski"], "yeni": r["yeni"], "aciklama": r["aciklama"], "benzerlik": round(s, 2)}
            for r, s in sirali[:k]
            if s > 0
        ]

    def istatistik(self) -> dict[str, int]:
        with self._baglanti() as db:
            cagri = db.execute("SELECT COUNT(*) FROM cagrilar").fetchone()[0]
            duzeltme = db.execute("SELECT COUNT(*) FROM duzeltmeler").fetchone()[0]
            onay = db.execute("SELECT COUNT(*) FROM cagrilar WHERE insan_onayi = 1").fetchone()[0]
        return {"cagri": cagri, "duzeltme": duzeltme, "insan_onayi_bekleyen": onay}

    def temizle(self) -> None:
        with self._baglanti() as db:
            db.execute("DELETE FROM cagrilar")
            db.execute("DELETE FROM duzeltmeler")
