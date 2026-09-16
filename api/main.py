from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

from zendesk_etl import openai_llm as llm
from zendesk_etl.pipeline_v2 import PipelineV2

from . import db
from .schemas import ChatRequest, ChatResponse, FeedbackRequest, ModelsResponse, UsageOverview

LOG_PATH = "data/feedback_v2.jsonl"

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    _state["pipe"] = PipelineV2()
    try:
        yield
    finally:
        _state["pipe"].close()


app = FastAPI(title="RMC GraphRAG v2 API", lifespan=lifespan)


def get_pipeline() -> PipelineV2:
    return _state["pipe"]


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats/usage", response_model=UsageOverview)
async def stats_usage() -> dict:
    return await run_in_threadpool(db.usage_overview)


@app.get("/api/models", response_model=ModelsResponse)
async def models() -> dict:
    return {"synth_models": llm.synth_model_choices(), "default_synth_model": llm.synth_model()}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> dict:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question boş olamaz")
    if req.synth_model and req.synth_model not in llm.synth_model_choices():
        raise HTTPException(status_code=400, detail=f"izin verilmeyen model: {req.synth_model}")
    pipe = get_pipeline()
    history = [h.model_dump() for h in req.history]
    active = req.active_context.model_dump()
    result = await run_in_threadpool(pipe.run, question, history, active,
                                     synth_model=req.synth_model)
    if result.get("smalltalk"):
        # Selamlama soru sayılmaz, metriklere yazılmaz.
        return result

    primary_module = next(
        (s.get("module") for s in result.get("router", []) if s.get("module")), None)
    answered = bool((result.get("answer") or "").strip()) and result.get("answer") != "(cevap üretilemedi)"
    calls = (result.get("usage") or {}).values()
    usage_totals = {
        "prompt_tokens": sum((c or {}).get("prompt_tokens") or 0 for c in calls) or None,
        "output_tokens": sum((c or {}).get("output_tokens") or 0 for c in calls) or None,
        "total_tokens": result.get("total_tokens"),
    }
    try:
        await run_in_threadpool(
            db.log_chat_event,
            session_id=req.session_id, question=question, primary_module=primary_module,
            evidence_count=len(result.get("evidence", [])), answered=answered,
            latency_ms=result.get("latency_ms"), usage=usage_totals,
            synth_model=result.get("synth_model"))
    except Exception:
        pass  # kullanım metrikleri ikincil — yazım hatası cevabı bloklamaz
    return result


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    result = req.result
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feedback": req.value,
        "question": result.get("question"),
        "standalone_question": result.get("standalone_question"),
        "router": result.get("router"),
        "evidence": [{
            "ticket_id": e.get("ticket_id"), "incident_id": e.get("incident_id"),
            "modul": e.get("modul"), "feature": e.get("feature"),
            "outcome": e.get("outcome"), "kanallar": e.get("kanallar"),
            "faaliyetler": e.get("faaliyetler"), "ekipler": e.get("ekipler"),
            "symptom": e.get("symptom"),
            "findings": (e.get("findings") or "")[:600],
            "resolution": e.get("resolution"),
        } for e in result.get("evidence", [])],
        "docs": [{"id": d.get("id"), "url": d.get("url"), "reason": d.get("reason")}
                 for d in result.get("docs", [])],
        "answer": result.get("answer"),
        "critique": req.critique,
    }

    def _write() -> None:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    await run_in_threadpool(_write)
    return {"status": "ok"}
