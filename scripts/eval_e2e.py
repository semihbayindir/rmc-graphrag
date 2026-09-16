#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, sys, time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional
from pydantic import BaseModel, Field

from zendesk_etl import openai_llm as llm
from zendesk_etl.router_v2 import Router
from zendesk_etl.graphrag_v2 import RetrieverV2, rrf
from zendesk_etl.synth_v2 import SynthesizerV2, build_context, build_docs_context


class Verdict(BaseModel):
    tier_basarisi: Literal["evet", "kismen", "hayir"]
    kaynak_gosterimi: Literal["evet", "eksik", "yok"]
    halusinasyon: bool = Field(description="Bağlamda olmayan bir iddia var mı")
    outcome_saygisi: Literal["evet", "hayir", "ilgisiz"]
    gerekce: str


RUBRIC = {
 "1": "T1 — BİLGİ SORUSU. Cevap, sorulan olguyu doğru ve somut biçimde veriyor mu? "
      "Beklenen cevap verildiyse onunla örtüşmeli. Genel laf değil, olgu aranır.",
 "2": "T2 — BELİRSİZ TANI SORUSU. Tek bir cevap dayatmak YANLIŞTIR. Doğru davranış: "
      "birden çok olası nedeni kaynaklarıyla sıralamak VE ayırt edici bir netleştirme "
      "sorusu sormak. İkisi de varsa 'evet', biri eksikse 'kismen'.",
 "3": "T3 — KAPSAM DIŞI. Soru belirli bir hesaba bakmayı gerektiriyor. Doğru davranış: "
      "varsa genel kuralı söyleyip, işlemin hesap bazında yapılması gerektiğini belirtmek. "
      "Uydurulmuş veri (sahte rol listesi, sahte kayıt sayısı) varsa 'hayir'.",
}

JUDGE_SYS = """Bir destek chatbot'unun cevabını değerlendiriyorsun.
Sana SORU, chatbot'un CEVABI ve cevabın dayandığı BAĞLAM verilecek.

Değerlendirme ölçütü tier'a göre değişir; aşağıda verilecek.

Ayrıca her cevapta şunlara bak:
- kaynak_gosterimi: olgusal maddelerde [#BiletID] var mı?
- halusinasyon: BAĞLAM'da geçmeyen bir servis adı, limit, parametre veya
  olgu iddia edilmiş mi? Bağlamdaki bilgiyi yeniden ifade etmek halüsinasyon
  DEĞİLDİR.
- outcome_saygisi: bağlamdaki kayıt "TEKRARLANAMADI" veya "ÇÖZÜLMEDİ" ise,
  cevap onu kesin çözüm gibi sunmuş mu? Sunmuşsa 'hayir'. Böyle bir kayıt
  yoksa 'ilgisiz'.

Katı ol; şüphedeysen düşük puan ver."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="data/golden/golden_v1.json")
    ap.add_argument("--out", default="data/golden/e2e_v1.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    G = json.load(open(args.golden, encoding="utf-8"))
    if args.limit:
        G = G[: args.limit]
    rt, rv, sy = Router(), RetrieverV2(), SynthesizerV2()

    JMODEL = llm.judge_model()
    # gpt-5.5 temperature'ı yalnızca effort='none' ile kabul ediyor; yargıçta
    # akıl yürütme tercih edildiği için temperature bu durumda gönderilmez.
    JEFFORT = os.environ.get("OPENAI_JUDGE_REASONING_EFFORT") or "low"

    prog = {"n": 0}
    plock = threading.Lock()

    def one(q):
        parts = []
        intents = rt.route(q["question"]).intents
        for it in intents:
            if it.keywords:
                parts.append(rv.hybrid(q["question"], it.keywords, it.module,
                                       it.channel, it.activity, k=args.k * 2))
        rows = rrf(*parts)[: args.k] if parts else []
        docs = rv.api_docs(q["question"], [kw for it in intents for kw in it.keywords],
                           [it.module for it in intents], rows)
        ans = sy.synthesize(q["question"], rows, docs=docs)
        # Yargıç dokümanları da görmeli; görmezse dokümandan gelen doğru bilgiyi
        # "bağlamda yok" diye halüsinasyon sayar.
        ctx = build_context(rows) + (f"\n\n=== API DOKÜMANLARI ===\n{build_docs_context(docs)}"
                                     if docs else "")
        exp = f"\nBEKLENEN CEVAP (referans):\n{q['expected_answer']}" if q.get("expected_answer") else ""
        prompt = (f"ÖLÇÜT:\n{RUBRIC[q['tier']]}\n\nSORU:\n{q['question']}{exp}\n\n"
                  f"CHATBOT CEVABI:\n{ans}\n\n=== BAĞLAM ===\n{ctx[:9000]}")
        verdict = None
        for a in range(4):
            try:
                verdict, _ = llm.parse(Verdict, JUDGE_SYS, prompt, model=JMODEL,
                                       temperature=0.0, effort=JEFFORT)
                break
            except Exception:
                if a == 3: break
                time.sleep(2 ** a)
        with plock:
            prog["n"] += 1
            v = (verdict.tier_basarisi if verdict else "hata")
            print(f"  [{prog['n']:>3}/{len(G)}] T{q['tier']} {v:<7} {q['question'][:58]}",
                  flush=True)
        return {"question": q["question"], "tier": q["tier"], "origin": q["origin"],
                "n_ctx": len(rows), "moduller": [r.get("modul") for r in rows],
                "answer": ans, "verdict": (verdict.model_dump() if verdict else None)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as p:
        res = list(p.map(one, G))
    rv.close()
    json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    import collections
    ok = [x for x in res if x["verdict"]]
    print(f"=== UÇTAN UCA ({len(ok)}/{len(res)} değerlendirildi, {time.time()-t0:.0f}s) ===")
    for t in ("1", "2", "3"):
        sub = [x for x in ok if x["tier"] == t]
        if not sub: continue
        c = collections.Counter(x["verdict"]["tier_basarisi"] for x in sub)
        skor = (c["evet"] + 0.5 * c["kismen"]) / len(sub)
        print(f"  T{t}: {len(sub):>3} soru | evet {c['evet']:>3} kismen {c['kismen']:>3} "
              f"hayir {c['hayir']:>3} | skor {skor:.2f}")
    c = collections.Counter(x["verdict"]["tier_basarisi"] for x in ok)
    print(f"  TOPLAM skor: {(c['evet']+0.5*c['kismen'])/len(ok):.2f}")
    h = sum(1 for x in ok if x["verdict"]["halusinasyon"])
    kg = collections.Counter(x["verdict"]["kaynak_gosterimi"] for x in ok)
    os_ = collections.Counter(x["verdict"]["outcome_saygisi"] for x in ok)
    print(f"\n  halüsinasyon : {h}/{len(ok)}")
    print(f"  kaynak       : {dict(kg)}")
    print(f"  outcome saygı: {dict(os_)}")
    print(f"\n=== BAŞARISIZLAR ===")
    for x in ok:
        if x["verdict"]["tier_basarisi"] == "hayir":
            print(f"  T{x['tier']} | {x['question'][:70]}")
            print(f"     {x['verdict']['gerekce'][:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
