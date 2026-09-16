#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys, time
from typing import List
from openai import LengthFinishReasonError
from pydantic import BaseModel

from zendesk_etl import openai_llm as llm


class Group(BaseModel):
    ids: List[int]


class Merges(BaseModel):
    gruplar: List[Group]


SYS = """Sana numaralı bir ALAN ADI listesi verilecek. Her satırda alan adı ve
o alanı ayırt eden teknik terimler var.

TEK GÖREVİN: Hangi numaraların AYNI KAVRAMI ifade ettiğini bulmak.

Birleştir:
  - Türkçe/İngilizce aynı şey ("IP Whitelist" = "IP beyaz listesi")
  - Eşanlamlı ("Mail gönderimi" = "E-posta gönderimi")
  - Aynı şeyin dar/geniş yazımı ("Push" = "Push Bildirim")

BİRLEŞTİRME:
  - Farklı faaliyetleri ("E-posta gönderimi" ile "E-posta raporlama" AYRI)
  - Farklı kanalları ("SMS gönderimi" ile "Push gönderimi" AYRI)
  - Farklı ürün alanlarını (terimleri örtüşmüyorsa AYRI)

Şüphedeysen BİRLEŞTİRME. Yanlış birleştirme, ayrı bırakmaktan daha zararlıdır.
Yalnızca 2+ üyeli grupları döndür; tek başına kalanları yazma.
İsim ÖNERME, sadece numara grupları ver."""


def call(lines: list[str]) -> list[list[int]]:
    for a in range(5):
        try:
            m, _ = llm.parse(Merges, SYS, "\n".join(lines), temperature=0.0, max_tokens=8000)
            return [g.ids for g in m.gruplar]
        except LengthFinishReasonError:
            # max_tokens biterse çıktı kesilir; tekrar denemek işe yaramaz.
            print("    [uyarı] max_tokens yetmedi (finish=length) — parti atlandı", flush=True)
            return []
        except Exception:
            if a == 4:
                return []
            time.sleep(2 ** a)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/ontology_candidates.json")
    ap.add_argument("--out", default="data/ontology_merged.json")
    ap.add_argument("--batch", type=int, default=45)
    args = ap.parse_args()

    C = json.load(open(args.inp, encoding="utf-8"))
    print(f"[giriş] {len(C)} küme")

    # Union-find: partiler arası birleşmeler de birikir
    parent = list(range(len(C)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Örtüşen partiler: sınırdaki çiftlerin kaçmaması için yarım adım kaydır
    step = args.batch // 2
    seen = 0
    for start in range(0, len(C), step):
        chunk = list(range(start, min(start + args.batch, len(C))))
        if len(chunk) < 2:
            break
        lines = [f"{i}. {C[i]['area']}  |  {', '.join(C[i]['keywords'][:5])}" for i in chunk]
        for g in call(lines):
            ids = [i for i in g if 0 <= i < len(C)]
            for k in ids[1:]:
                union(ids[0], k)
        seen += 1
        print(f"  parti {seen} ({chunk[0]}-{chunk[-1]})", flush=True)

    groups = {}
    for i in range(len(C)):
        groups.setdefault(find(i), []).append(i)

    out = []
    for root, idxs in groups.items():
        idxs.sort(key=lambda i: -C[i]["count"])
        head = C[idxs[0]]
        merged = {
            "area": head["area"],
            "count": sum(C[i]["count"] for i in idxs),
            "birlesen_etiketler": [C[i]["area"] for i in idxs],
            "anchor": next((C[i]["anchor"] for i in idxs if C[i]["anchor"] == "tam"),
                           next((C[i]["anchor"] for i in idxs if C[i]["anchor"] == "kısmi"), "YOK")),
            "anchor_via": next((C[i]["anchor_via"] for i in idxs if C[i]["anchor"] == "tam"), ""),
            "keywords": list(dict.fromkeys(k for i in idxs for k in C[i]["keywords"]))[:10],
            "eski_moduller": {},
            "ornek_ticketlar": list(dict.fromkeys(t for i in idxs for t in C[i]["ornek_ticketlar"]))[:6],
        }
        em = {}
        for i in idxs:
            for m, c in C[i]["eski_moduller"].items():
                em[m] = em.get(m, 0) + c
        merged["eski_moduller"] = dict(sorted(em.items(), key=lambda x: -x[1])[:4])
        out.append(merged)
    out.sort(key=lambda x: -x["count"])
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n_merged = sum(1 for o in out if len(o["birlesen_etiketler"]) > 1)
    print(f"\n[done] {len(C)} -> {len(out)} küme ({n_merged} tanesi birleşme sonucu)")
    import collections
    b = collections.Counter(o["anchor"] for o in out)
    for k in ("tam", "kısmi", "YOK"):
        c = [o for o in out if o["anchor"] == k]
        print(f"  çapa {k:<6}: {len(c):>4} küme | {sum(o['count'] for o in c):>6,} olay")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
