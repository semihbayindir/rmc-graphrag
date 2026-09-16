"use client";
import React, { useEffect, useRef, useState } from "react";
import { PaperPlaneIcon } from "@/icons";
import DocCard from "@/components/chat/DocCard";
import EvidenceCard from "@/components/chat/EvidenceCard";
import { formatText } from "@/components/chat/formatText";
import { getSessionId } from "@/lib/session";
import type { ActiveContext, ChatResponse, HistoryTurn, ModelsResponse } from "@/types/api";

const MODEL_KEY = "rmc_synth_model";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  result?: ChatResponse; // yalnızca assistant mesajlarında — kanıt/feedback için
  feedback?: "up" | "down";
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeContext, setActiveContext] = useState<ActiveContext>({});
  const [critiqueFor, setCritiqueFor] = useState<number | null>(null);
  const [critiqueText, setCritiqueText] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [synthModel, setSynthModel] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Mesaj kutusu içeriğe göre INPUT_MAX_PX'e kadar büyür, sonra kendi içinde kayar.
  // Genişlik değişince de yeniden ölçülür (satır kırılımı genişliğe bağlı).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const INPUT_MAX_PX = 200;
    const resize = () => {
      el.style.height = "auto";
      // scrollHeight kenarlıkları içermez; border-box'ta kırpılmaması için eklenir.
      const full = el.scrollHeight + el.offsetHeight - el.clientHeight;
      el.style.height = `${Math.min(full, INPUT_MAX_PX)}px`;
      el.style.overflowY = full > INPUT_MAX_PX ? "auto" : "hidden";
    };
    resize();
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        resize();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [input]);

  // Model listesi API'den gelir, seçim tarayıcıda hatırlanır.
  useEffect(() => {
    fetch("/api/models")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data: ModelsResponse) => {
        let saved: string | null = null;
        try {
          saved = window.localStorage.getItem(MODEL_KEY);
        } catch {}
        setModels(data.synth_models);
        setSynthModel(saved && data.synth_models.includes(saved) ? saved : data.default_synth_model);
      })
      .catch(() => {});
  }, []);

  function chooseModel(value: string) {
    setSynthModel(value);
    try {
      window.localStorage.setItem(MODEL_KEY, value);
    } catch {}
  }

  const scrollToBottom = () =>
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });

  async function send() {
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    const history: HistoryTurn[] = messages.map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);
    scrollToBottom();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          history,
          active_context: activeContext,
          session_id: getSessionId(),
          synth_model: synthModel || undefined,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result: ChatResponse = await res.json();
      setActiveContext(result.active_context);
      setMessages((prev) => [...prev, { role: "assistant", content: result.answer, result }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "⚠️ İstek başarısız oldu. API çalışıyor mu?" },
      ]);
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  }

  async function sendFeedback(index: number, value: "up" | "down", critique = "") {
    const msg = messages[index];
    if (!msg.result) return;
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, feedback: value } : m))
    );
    setCritiqueFor(null);
    setCritiqueText("");
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value, critique, result: msg.result }),
      });
    } catch {
      // sessizce yut — geri bildirim ikincil bir işlev
    }
  }

  return (
    <div className="flex h-[calc(100vh-140px)] flex-col rounded-2xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-white/[0.03]">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4 md:p-6">
        {messages.length === 0 && !loading && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <h1 className="text-xl font-semibold text-gray-800 dark:text-white/90">
              RMC Bilgi Asistanı
            </h1>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              Bir soru sorarak başlayın.
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                m.role === "user"
                  ? "max-w-[80%] rounded-2xl rounded-br-sm bg-brand-500 px-4 py-3 text-sm text-white"
                  : "max-w-[85%] rounded-2xl rounded-bl-sm bg-gray-100 px-4 py-3 text-sm text-gray-800 dark:bg-white/5 dark:text-gray-200"
              }
            >
              {/* <p> değil: cevap <pre> kod blokları içerebilir */}
              <div className="whitespace-pre-wrap">{formatText(m.content)}</div>

              {m.result && (m.result.evidence.length > 0 || (m.result.docs?.length ?? 0) > 0) && (
                <details className="mt-3 border-t border-gray-200 pt-3 dark:border-gray-700">
                  <summary className="cursor-pointer select-none text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
                    Kanıt ({m.result.evidence.length} kayıt
                    {m.result.docs?.length ? ` · ${m.result.docs.length} doküman` : ""})
                  </summary>
                  <div className="mt-2 space-y-2">
                    {m.result.docs?.map((doc) => (
                      <DocCard key={doc.id} doc={doc} />
                    ))}
                    {m.result.evidence.map((row, j) => (
                      <EvidenceCard key={j} row={row} />
                    ))}
                  </div>
                </details>
              )}

              {m.role === "assistant" && m.result && !m.result.smalltalk && (
                <div className="mt-3 flex items-center gap-3 border-t border-gray-200 pt-2 text-xs dark:border-gray-700">
                  <button
                    onClick={() => sendFeedback(i, "up")}
                    disabled={!!m.feedback}
                    className={`rounded px-2 py-1 hover:bg-gray-200 dark:hover:bg-white/10 ${
                      m.feedback === "up" ? "font-semibold text-success-600" : "text-gray-500"
                    }`}
                  >
                    👍 Beğen
                  </button>
                  <button
                    onClick={() => setCritiqueFor(critiqueFor === i ? null : i)}
                    disabled={!!m.feedback}
                    className={`rounded px-2 py-1 hover:bg-gray-200 dark:hover:bg-white/10 ${
                      m.feedback === "down" ? "font-semibold text-error-600" : "text-gray-500"
                    }`}
                  >
                    👎 Beğenmedim
                  </button>
                  {m.feedback && (
                    <span className="text-gray-400">✅ kaydedildi</span>
                  )}
                  {m.result.synth_model && (
                    <span
                      title="Bu cevabı üreten model"
                      className="ml-auto rounded bg-gray-200 px-2 py-0.5 font-mono text-[11px] text-gray-600 dark:bg-white/10 dark:text-gray-300"
                    >
                      {m.result.synth_model}
                    </span>
                  )}
                </div>
              )}

              {critiqueFor === i && (
                <div className="mt-2 flex gap-2">
                  <input
                    autoFocus
                    value={critiqueText}
                    onChange={(e) => setCritiqueText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") sendFeedback(i, "down", critiqueText);
                    }}
                    placeholder="Neyi yanlış/eksik buldunuz? (bir cümle yeterli)"
                    className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-800 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                  />
                  <button
                    onClick={() => sendFeedback(i, "down", critiqueText)}
                    className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs text-white"
                  >
                    Gönder
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm bg-gray-100 px-4 py-3 text-sm text-gray-500 dark:bg-white/5 dark:text-gray-400">
              🧭 Yönlendirici + hibrit arama çalışıyor…
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-gray-200 p-4 dark:border-gray-800">
        <div className="flex items-end gap-2">
          {models.length > 1 && (
            <select
              value={synthModel}
              onChange={(e) => chooseModel(e.target.value)}
              disabled={loading}
              title="Cevabı üreten model"
              aria-label="Cevap modeli"
              className="h-11 shrink-0 rounded-lg border border-gray-300 bg-transparent px-3 text-sm text-gray-700 disabled:opacity-40 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-300"
            >
              {models.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          )}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder="Bir soru yazın…"
            className="flex-1 resize-none rounded-lg border border-gray-300 bg-transparent px-4 py-2.5 text-sm text-gray-800 shadow-theme-xs placeholder:text-gray-400 focus:border-brand-300 focus:outline-hidden focus:ring-3 focus:ring-brand-500/10 dark:border-gray-800 dark:bg-white/[0.03] dark:text-white/90 dark:placeholder:text-white/30"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white disabled:opacity-40"
            aria-label="Gönder"
          >
            <PaperPlaneIcon />
          </button>
        </div>
      </div>
    </div>
  );
}
