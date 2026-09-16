from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, field_validator


class HistoryTurn(BaseModel):
    role: str
    content: str


class ActiveContext(BaseModel):
    module: Optional[str] = None
    channel: Optional[str] = None


class ChatRequest(BaseModel):
    question: str
    history: list[HistoryTurn] = []
    active_context: ActiveContext = ActiveContext()
    session_id: Optional[str] = None  # tarayıcıda üretilen anonim kimlik — kullanım metrikleri için
    synth_model: Optional[str] = None  # boşsa OPENAI_SYNTH_MODEL; izin listesi: GET /api/models


class RouterStep(BaseModel):
    intent: int
    module: Optional[str] = None
    channel: Optional[str] = None
    activity: Optional[str] = None
    keywords: list[str] = []
    count: int


class EvidenceRow(BaseModel):
    ticket_id: Any
    incident_id: Any
    skor: Optional[float] = None
    symptom: Optional[str] = None
    findings: Optional[str] = None
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    outcome: Optional[str] = None
    modul: Optional[str] = None
    feature: Optional[str] = None
    kanallar: list[str] = []
    faaliyetler: list[str] = []
    ekipler: list[str] = []
    tarih: Optional[str] = None
    artifacts: list[dict] = []
    rrf: Optional[float] = None

    @field_validator("tarih", "ticket_id", "incident_id", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> Any:
        # neo4j.time.DateTime (i.created_at) pydantic'in native tanımadığı bir tip;
        # isoformat'ı varsa onu, yoksa str() kullan.
        if v is None or isinstance(v, (str, int, float)):
            return v
        iso = getattr(v, "isoformat", None)
        return iso() if callable(iso) else str(v)


class DocRow(BaseModel):
    """Cevaba eklenen API doküman bölümü (RetrieverV2.api_docs)."""
    id: str
    protocol: str
    service: str
    method: Optional[str] = None
    summary: str = ""
    url: str
    text: str = ""  # sentez bağlamına giren (kısaltılmış) metin
    reason: str = ""  # hangi sinyalle eklendi


class ChatResponse(BaseModel):
    question: str
    standalone_question: str
    is_followup: bool = False  # True ise bu tur önceki turun bağlamını (modül/kanal + geçmiş) kullandı
    router: list[RouterStep]
    evidence: list[EvidenceRow]
    docs: list[DocRow] = []
    answer: str
    synth_model: Optional[str] = None  # cevabı üreten model
    smalltalk: bool = False  # selamlama/teşekkür — arama yapılmadı, sabit cevap
    active_context: ActiveContext


class FeedbackRequest(BaseModel):
    value: str  # "up" | "down"
    critique: str = ""
    result: dict  # sonraki turda yeniden üretmemek için ham sonuç


class ModelsResponse(BaseModel):
    synth_models: list[str]
    default_synth_model: str


class RecentQuestion(BaseModel):
    ts: float
    question: Optional[str] = None
    primary_module: Optional[str] = None
    evidence_count: int
    answered: int
    latency_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    synth_model: Optional[str] = None


class TopModuleAsked(BaseModel):
    module: str
    c: int


class FeedbackCounts(BaseModel):
    up: int
    down: int


class UsageOverview(BaseModel):
    total_questions: int
    questions_last_7d: int
    answered: int
    answered_rate: Optional[float] = None
    zero_evidence_count: int
    zero_evidence_rate: Optional[float] = None
    distinct_sessions: int
    avg_latency_ms: Optional[float] = None
    total_prompt_tokens: int
    total_output_tokens: int
    total_tokens: int
    top_modules: list[TopModuleAsked]
    recent: list[RecentQuestion]
    feedback: FeedbackCounts
