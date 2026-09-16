from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel

from . import openai_llm as llm
from . import smalltalk
from .graphrag_v2 import RetrieverV2, rrf
from .router_v2 import Router
from .synth_v2 import SynthesizerV2

# is_followup true değilse eksen taşınmaz ve geçmiş sentezleyiciye verilmez.
class RewriteOut(BaseModel):
    is_followup: bool
    standalone_question: str


REWRITE_SYS = """Kullanıcının SON mesajını analiz et, iki alan üret:

1. is_followup — SON mesaj, ÖNCEKİ sohbetteki konunun DEVAMI mı?
   true:  zamir/eksik bağlam var ('o', 'bu servis', 'peki'), ya da açıkça
          önceki mesajdaki bir şeye (hata, modül, kayıt) referans veriyor.
   false: SON mesaj yeni/bağımsız bir konu — farklı modül, farklı hata,
          farklı servis. EMİN DEĞİLSEN FALSE YAZ: yanlışlıkla "devam sorusu"
          sayıp önceki konuyla birleştirmek, devam sorusunu yanlışlıkla yeni
          konu saymaktan DAHA KÖTÜ bir hataya yol açar (yanlış modüle
          yönlendirilmiş arama).

2. standalone_question —
   is_followup=true  ise: zamirleri/eksik bağlamı geçmişten doldurup TEK
                      BAŞINA ANLAMLI bir soru üret.
   is_followup=false ise: SON mesajı AYNEN döndür, geçmişten hiçbir şey ekleme."""


class PipelineV2:
    def __init__(self) -> None:
        self.retriever = RetrieverV2()
        self.router = Router()
        self.synth = SynthesizerV2()
        self.model = llm.chat_model()
        self.last_rewrite_usage: dict | None = None

    def close(self) -> None:
        self.retriever.close()

    def rewrite(self, question: str, history: list[dict] | None) -> tuple[str, bool]:
        """(standalone_question, is_followup) döner. Geçmiş yoksa ya da rewrite
        başarısız olursa is_followup=False — emin olunmayan durumda bağlam
        karıştırmamak, karıştırıp yanlış modüle sapmaktan güvenlidir."""
        self.last_rewrite_usage = None
        if not history:
            return question, False
        turns = "\n".join(
            f"{'Kullanıcı' if m.get('role') == 'user' else 'Asistan'}: {m.get('content','')}"
            for m in history[-6:])
        try:
            out, resp = llm.parse(RewriteOut, REWRITE_SYS,
                                  f"SOHBET GEÇMİŞİ:\n{turns}\n\nSON MESAJ: {question}",
                                  model=self.model, temperature=0.0)
            self.last_rewrite_usage = llm.usage(resp)
            standalone = (out.standalone_question or question).strip() or question
            return standalone, out.is_followup
        except Exception:
            return question, False

    def run(self, question: str, history: list[dict] | None = None,
            active: dict | None = None, k: int = 5,
            synth_model: str | None = None) -> dict:
        """synth_model yalnızca cevap üretimini etkiler (boşsa OPENAI_SYNTH_MODEL);
        rewrite ve router her zaman OPENAI_MODEL'de kalır. Doğrulama çağıranın işi."""
        t0 = time.time()
        active = active or {}

        # Selamlama/teşekkür: arama ve LLM çağrısı yok. Aktif bağlam aynen döner ki
        # "selam"dan sonraki takip sorusu önceki konuyu kaybetmesin.
        canned = smalltalk.reply(question)
        if canned:
            return {
                "question": question, "standalone_question": question, "is_followup": False,
                "router": [], "evidence": [], "docs": [], "answer": canned, "synth_model": None,
                "steps": [], "active_context": active, "usage": {}, "total_tokens": None,
                "latency_ms": int((time.time() - t0) * 1000), "smalltalk": True,
            }

        standalone, is_followup = self.rewrite(question, history)
        intents = self.router.route(standalone).intents

        # Önceki turun modül/kanalı yalnızca takip sorusunda taşınır.
        base_active = active if is_followup else {}
        if is_followup:
            for it in intents:
                if it.module is None and active.get("module"):
                    it.module = active["module"]
                if it.channel is None and active.get("channel"):
                    it.channel = active["channel"]

        parts, steps = [], []
        for n, it in enumerate(intents, 1):
            kw = it.keywords or [standalone]
            rows = self.retriever.hybrid(standalone, kw, it.module, it.channel,
                                         it.activity, k=k * 2)
            parts.append(rows)
            steps.append({"intent": n, "module": it.module, "channel": it.channel,
                          "activity": it.activity, "keywords": kw, "count": len(rows)})
        evidence = rrf(*parts)[:k] if parts else []
        # API dokümanları yalnızca sinyal varsa eklenir (bkz. RetrieverV2.api_docs).
        docs = self.retriever.api_docs(standalone, [kw for s in steps for kw in s["keywords"]],
                                       [it.module for it in intents], evidence)
        # Sohbet geçmişi yalnızca takip sorusunda verilir.
        answer = self.synth.synthesize(standalone, evidence, history if is_followup else None,
                                       model=synth_model, docs=docs)

        # Sonraki tur için aktif bağlam: en güçlü kanıtın ekseni.
        new_active = dict(base_active)
        if evidence:
            top = evidence[0]
            if top.get("modul"):
                new_active["module"] = top["modul"]
            if top.get("kanallar"):
                new_active["channel"] = top["kanallar"][0]

        usage = {"rewrite": self.last_rewrite_usage, "router": self.router.last_usage,
                  "synth": self.synth.last_usage}
        total_tokens = sum(
            (u or {}).get("total_tokens") or 0 for u in usage.values())

        return {
            "question": question,
            "standalone_question": standalone,
            "is_followup": is_followup,
            "router": [s for s in steps],
            "evidence": evidence,
            "answer": answer,
            "docs": docs,
            "synth_model": synth_model or self.synth.model,
            "steps": steps,
            "active_context": new_active,
            "usage": usage,
            "total_tokens": total_tokens or None,
            "latency_ms": int((time.time() - t0) * 1000),
        }
