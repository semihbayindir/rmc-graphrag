#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from typing import List
from pydantic import BaseModel

from zendesk_etl import openai_llm as llm
from zendesk_etl.config import settings
from zendesk_etl.llm import RateLimiter


class Discovery(BaseModel):
    area: str          # ürünün hangi alanı — 1-4 kelime, serbest
    object: str        # üzerinde işlem yapılan somut şey — ekran, servis, tablo, ayar
    keywords: List[str]  # bu olayı ayırt eden 2-5 teknik terim


SYS = """Sana bir destek olayının bulguları verilecek. Üç şey çıkar.

area — Bu olay ürünün HANGİ ALANIYLA ilgili? 1-4 kelimeyle, ürünün kendi
       terminolojisiyle yaz. Sana hazır bir liste VERİLMİYOR; metinde ne
       geçiyorsa ona göre kendi ifadeni kur. Uydurma, metne dayan.

object — Üzerinde işlem yapılan SOMUT şey nedir? Bir ekran, bir servis/metot,
       bir veritabanı nesnesi, bir ayar, bir dosya. Yoksa boş string.

keywords — Bu olayı benzerlerinden ayıran 2-5 teknik terim. Metinde geçen
       gerçek terimler; genel kelime yazma.

Türkçe metinde İngilizce ürün terimleri geçiyorsa onları OLDUĞU GİBİ koru.
Kısaltma açma, normalleştirme yapma — ham hâliyle ver."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/graph_ready_v3.jsonl")
    ap.add_argument("--out", default="data/ontology_discovery.jsonl")
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    done = set()
    try:
        for l in open(args.out, encoding="utf-8"):
            r = json.loads(l); done.add((r["ticket_id"], r["incident_id"]))
    except FileNotFoundError:
        pass

    todo = []
    for l in open(args.inp, encoding="utf-8"):
        r = json.loads(l)
        for i in r["incidents"]:
            k = (r["ticket_id"], i["incident_id"])
            if i["outcome"] == "none" or k in done:
                continue
            f = (i["findings"] or "").strip()
            if len(f) < 60:
                continue
            todo.append((k, i["affected_component"]["module"],
                         f"SEMPTOM: {i['symptom']}\nBULGULAR: {f[:1100]}"))
    if args.limit:
        todo = todo[: args.limit]
    print(f"[giriş] {len(todo):,} incident ({len(done):,} yapılmış)")

    lim = RateLimiter(settings.openai_rpm)
    lock = threading.Lock(); fh = open(args.out, "a", encoding="utf-8")
    cnt = {"ok": 0, "fail": 0}; st = {"pt": 0, "ch": 0, "ct": 0}

    def work(item):
        (tid, iid), old_mod, text = item
        for a in range(5):
            lim.wait()
            try:
                v, resp = llm.parse(Discovery, SYS, text, temperature=0.2, max_tokens=400)
                with lock:
                    st["pt"] += resp.usage.prompt_tokens; st["ch"] += llm.cached_tokens(resp)
                    st["ct"] += resp.usage.completion_tokens
                    fh.write(json.dumps({"ticket_id": tid, "incident_id": iid,
                                         "area": v.area, "object": v.object,
                                         "keywords": v.keywords, "old_module": old_mod},
                                        ensure_ascii=False) + "\n")
                    fh.flush(); cnt["ok"] += 1
                    n = cnt["ok"] + cnt["fail"]
                    if n % 1000 == 0:
                        print(f"  {n:,}/{len(todo):,}", flush=True)
                return
            except Exception:
                if a == 4:
                    with lock: cnt["fail"] += 1
                    return
                time.sleep(2 ** a)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as p:
        list(p.map(work, todo))
    fh.close()
    print(f"\n[done] ok={cnt['ok']:,} hata={cnt['fail']} | {time.time()-t0:.0f}s | "
          f"prompt {st['pt']:,} (cache {st['ch']:,}) çıktı {st['ct']:,} token")
    return 0


if __name__ == "__main__":
    sys.exit(main())
