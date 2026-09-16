#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys, threading, time, collections
from concurrent.futures import ThreadPoolExecutor
from typing import List, Literal

from pydantic import BaseModel

from zendesk_etl import openai_llm as llm
from zendesk_etl.config import settings
from zendesk_etl.llm import RateLimiter

CH = ["email", "sms", "mobile_push", "web_push", "in_app", "web_reco", "cdp"]
AC = ["error", "complaint", "report", "creation", "integration", "data_ops",
      "transaction", "settings", "access", "scheduled", "triggered"]


class Facets(BaseModel):
    channel: List[Literal["email","sms","mobile_push","web_push","in_app","web_reco","cdp"]]
    activity: List[Literal["error","complaint","report","creation","integration","data_ops",
                           "transaction","settings","access","scheduled","triggered"]]


SYS = f"""Bir destek olayını iki BAĞIMSIZ eksene ayır. SADECE listedeki değerleri kullan.

channel = olayın hangi iletişim kanalıyla ilgili olduğu. Kanal geçmiyorsa BOŞ liste.
  {', '.join(CH)}

activity = olayda yapılan/yaşanan işin türü. EN FAZLA 2 tane, en belirgin olanları.
  error        hata, çalışmama, kesinti
  complaint    müşteri şikayeti / memnuniyetsizlik
  report       rapor alma, dışa aktarma
  creation     kampanya/kurgu/şablon oluşturma
  integration  entegrasyon, API/SDK bağlama
  data_ops     veri yükleme/güncelleme/silme/aktarma
  transaction  transactional (tekil/işlemsel) gönderim
  settings     ayar, konfigürasyon, tanımlama
  access       hesap, şifre, yetki, IP izni, giriş
  scheduled    zamanlanmış gönderim
  triggered    tetiklenmiş/otomatik gönderim

Emin değilsen BOŞ liste bırak. Uydurma; zorlama eşleştirme yapma."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/graph_ready_v3.jsonl")
    ap.add_argument("--out", default="data/facets_llm.jsonl")
    ap.add_argument("--workers", type=int, default=40)
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
            todo.append((k, f"SYMPTOM: {i['symptom']}\nFINDINGS: {(i['findings'] or '')[:900]}"))
    if args.limit:
        todo = todo[: args.limit]
    print(f"[giriş] {len(todo):,} incident ({len(done):,} zaten yapılmış, none'lar atlandı)")

    lim = RateLimiter(settings.openai_rpm)
    lock = threading.Lock()
    fh = open(args.out, "a", encoding="utf-8")
    cnt = {"ok": 0, "fail": 0}
    stats = {"pt": 0, "ch": 0, "ct": 0}

    def work(item):
        (tid, iid), text = item
        for a in range(5):
            lim.wait()
            try:
                f, resp = llm.parse(Facets, SYS, text, temperature=0.0, max_tokens=400)
                with lock:
                    stats["pt"] += resp.usage.prompt_tokens
                    stats["ch"] += llm.cached_tokens(resp)
                    stats["ct"] += resp.usage.completion_tokens
                    fh.write(json.dumps({"ticket_id": tid, "incident_id": iid,
                                         "channel": f.channel, "activity": f.activity},
                                        ensure_ascii=False) + "\n")
                    fh.flush(); cnt["ok"] += 1
                    n = cnt["ok"] + cnt["fail"]
                    if n % 500 == 0:
                        print(f"  {n:,}/{len(todo):,} (ok={cnt['ok']:,} hata={cnt['fail']})", flush=True)
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
    print(f"\n[done] ok={cnt['ok']:,} hata={cnt['fail']:,} | {time.time()-t0:.0f}s")
    print(f"[token] {llm.chat_model()} | prompt {stats['pt']:,} "
          f"(cache %{100*stats['ch']/max(stats['pt'],1):.0f}) | çıktı {stats['ct']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
