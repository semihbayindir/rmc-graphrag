#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re, sys, collections
from zendesk_etl.graphrag_v2 import RetrieverV2
from zendesk_etl.router_v2 import Router

TR = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")
STOP = set("""ne nedir neden nasil nasıl mi mı mu mü bir bu su şu icin için olan olarak ve veya ile
mumkun mümkün mudur var yok sebebi nedeni detayini paylasabilir misiniz goruntulenebilir
edilebilir yapilabilir oluyor olabilir gerekiyor destekleniyor uygulaniyor gorebilir miyiz
aliyorum calistigimizda istedigimde girdigimde ragmen tumunu hangi kadar surede tamamen
ayri uzerinde son bunu buna sonra once daha cok az""".split())


def keywords(q: str, n: int = 10) -> list[str]:
    w = re.findall(r"[\wçğıöşüÇĞİÖŞÜ']+", q)
    out = []
    for x in w:
        if len(x) < 4:
            continue
        if x.lower().translate(TR) in STOP:
            continue
        out.append(x)
    return out[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="data/golden/golden_v1.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="data/golden/eval_v1.json")
    ap.add_argument("--mode", choices=["regex", "router", "hybrid"], default="hybrid",
                    help="regex=eski taban, router=+niyet, hybrid=+vektör")
    args = ap.parse_args()

    G = json.load(open(args.golden, encoding="utf-8"))
    r = RetrieverV2()
    rt = Router() if args.mode in ("router", "hybrid") else None
    print(f"[mod] {args.mode}")
    rows = []
    for q in G:
        if rt:
            # Router çok niyet üretebilir; her niyeti çekip RRF ile birleştir.
            from zendesk_etl.graphrag_v2 import rrf
            parts = []
            for it in rt.route(q["question"]).intents:
                kw = it.keywords or keywords(q["question"])
                if not kw:
                    continue
                if args.mode == "hybrid":
                    parts.append(r.hybrid(q["question"], kw, it.module, it.channel, it.activity, k=args.k * 2))
                else:
                    parts.append(r.retrieve(kw, it.module, it.channel, it.activity, k=args.k * 2))
            hits = rrf(*parts)[:args.k] if parts else []
        else:
            kw = keywords(q["question"])
            hits = r.retrieve(kw, k=args.k) if kw else []
        rank = None
        if q.get("source_ticket_id"):
            for idx, h in enumerate(hits, 1):
                if h["ticket_id"] == q["source_ticket_id"]:
                    rank = idx
                    break
        rows.append({"question": q["question"], "tier": q["tier"], "origin": q["origin"],
                     "gt": q.get("source_ticket_id"), "rank": rank,
                     "n_hits": len(hits),
                     "moduller": [h["modul"] for h in hits],
                     "top": [{"t": h["ticket_id"], "m": h["modul"], "o": h["outcome"],
                              "s": round(h["skor"], 2)} for h in hits[:3]]})
    r.close()
    json.dump(rows, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    gt = [x for x in rows if x["gt"]]
    hit = [x for x in gt if x["rank"]]
    mrr = sum(1 / x["rank"] for x in hit) / len(gt) if gt else 0
    print(f"=== YER GERÇEKLİ SORULAR ({len(gt)}) ===")
    print(f"  Recall@{args.k} : {len(hit)}/{len(gt)}  (%{100*len(hit)/max(len(gt),1):.1f})")
    print(f"  MRR        : {mrr:.3f}")
    rd = collections.Counter(x["rank"] for x in hit)
    print(f"  sıra dağılımı: {dict(sorted(rd.items()))}")
    print(f"\n=== TIER BAZINDA ===")
    for t in ("1", "2", "3"):
        sub = [x for x in rows if x["tier"] == t]
        bos = sum(1 for x in sub if x["n_hits"] == 0)
        sg = [x for x in sub if x["gt"]]
        sh = [x for x in sg if x["rank"]]
        rec = f"{len(sh)}/{len(sg)}" if sg else "—"
        print(f"  T{t}: {len(sub):>3} soru | sonuçsuz {bos:>2} | recall {rec}")
    print(f"\n=== KAÇIRILANLAR ===")
    for x in gt:
        if not x["rank"]:
            print(f"  #{x['gt']} | {x['question'][:74]}")
            print(f"     dönen: {[t['t'] for t in x['top']]} moduller={x['moduller'][:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
