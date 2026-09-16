from __future__ import annotations

import os
import threading
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from .config import settings  # noqa: F401  (.env yükler)

T = TypeVar("T", bound=BaseModel)

_client = None
_client_lock = threading.Lock()


def client():
    """Süreç boyunca tek istemci. SDK 429/5xx/timeout'u kendisi yeniden dener."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from openai import OpenAI
                _client = OpenAI(
                    timeout=float(os.environ.get("OPENAI_TIMEOUT_S", "120")),
                    max_retries=int(os.environ.get("OPENAI_MAX_RETRIES", "4")),
                )
    return _client


def chat_model() -> str:
    return os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini"


def synth_model() -> str:
    """Cevap üretimi (sentez) modeli; boşsa OPENAI_MODEL ile aynı."""
    return os.environ.get("OPENAI_SYNTH_MODEL") or chat_model()


def synth_model_choices() -> list[str]:
    """Arayüzden seçilebilen sentez modellerinin izin listesi."""
    raw = os.environ.get("OPENAI_SYNTH_MODEL_CHOICES") or ""
    choices = [m.strip() for m in raw.split(",") if m.strip()]
    default = synth_model()
    return choices if default in choices else [default, *choices]


def judge_model() -> str:
    return os.environ.get("OPENAI_JUDGE_MODEL") or "gpt-5.5"


def embed_model() -> str:
    return os.environ.get("OPENAI_EMBED_MODEL") or "text-embedding-3-large"


def embed_dim() -> int:
    return int(os.environ.get("OPENAI_EMBED_DIM") or "768")


def sampling(model: str, temperature: Optional[float], effort: Optional[str] = None) -> dict:
    """Modele uygun örnekleme parametreleri; reasoning modellerinde temperature yalnızca effort='none' ile gider."""
    effort = effort or os.environ.get("OPENAI_REASONING_EFFORT") or "none"
    if model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        kw: dict = {"reasoning_effort": effort}
        if effort == "none" and temperature is not None:
            kw["temperature"] = temperature
        return kw
    return {"temperature": temperature} if temperature is not None else {}


def _messages(system: str, user: str) -> list[dict]:
    msgs = [{"role": "system", "content": system}] if system else []
    return msgs + [{"role": "user", "content": user}]


def parse(schema: Type[T], system: str, user: str, *, model: Optional[str] = None,
          temperature: Optional[float] = 0.0, effort: Optional[str] = None,
          max_tokens: Optional[int] = None):
    """Strict şemalı çağrı; (parsed, resp) döner.

    parsed None ise (refusal) ValueError; çıktı max_tokens'ta kesilirse SDK
    LengthFinishReasonError fırlatır. Çağıran taraf ikisini de yakalamalı.
    """
    model = model or chat_model()
    kw = sampling(model, temperature, effort)
    if max_tokens:
        kw["max_completion_tokens"] = max_tokens
    resp = client().chat.completions.parse(
        model=model, messages=_messages(system, user), response_format=schema, **kw)
    msg = resp.choices[0].message
    if msg.parsed is None:
        raise ValueError(f"yapılandırılmış çıktı yok (refusal={msg.refusal!r})")
    return msg.parsed, resp


def complete(system: str, user: str, *, model: Optional[str] = None,
             temperature: Optional[float] = 0.2, effort: Optional[str] = None):
    """Serbest metin çağrısı; (metin, resp) döner."""
    model = model or chat_model()
    resp = client().chat.completions.create(
        model=model, messages=_messages(system, user), **sampling(model, temperature, effort))
    return (resp.choices[0].message.content or "").strip(), resp


def embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """(vektörler, kullanılan token) döner. Model/boyut graftaki vektörlerle AYNI olmalı."""
    resp = client().embeddings.create(model=embed_model(), input=texts, dimensions=embed_dim())
    vecs = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    return vecs, resp.usage.total_tokens


def usage(resp) -> dict | None:
    """Token kullanımı, api/db.py'nin beklediği anahtarlarla.

    İkincil metrik — alan yoksa None döner, ana akışı asla kesmez.
    """
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {"prompt_tokens": getattr(u, "prompt_tokens", None),
            "output_tokens": getattr(u, "completion_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None)}


def cached_tokens(resp) -> int:
    details = getattr(getattr(resp, "usage", None), "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0
