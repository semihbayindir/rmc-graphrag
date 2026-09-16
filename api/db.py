from __future__ import annotations

import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("USAGE_DB_PATH", "data/usage.db")
FEEDBACK_PATH = "data/feedback_v2.jsonl"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session_id TEXT,
    question TEXT,
    primary_module TEXT,
    evidence_count INTEGER NOT NULL,
    answered INTEGER NOT NULL,
    latency_ms INTEGER,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    synth_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_events_ts ON chat_events(ts);
"""


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(_SCHEMA)
        # Sonradan eklenen kolon: mevcut data/usage.db dosyaları yerinde yükseltilir.
        cols = {r[1] for r in c.execute("PRAGMA table_info(chat_events)")}
        if "synth_model" not in cols:
            c.execute("ALTER TABLE chat_events ADD COLUMN synth_model TEXT")


def log_chat_event(
    *, session_id: str | None, question: str, primary_module: str | None,
    evidence_count: int, answered: bool, latency_ms: int | None,
    usage: dict | None, synth_model: str | None = None,
) -> None:
    usage = usage or {}
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "INSERT INTO chat_events (ts, session_id, question, primary_module, "
            "evidence_count, answered, latency_ms, prompt_tokens, output_tokens, total_tokens, "
            "synth_model) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), session_id, question, primary_module, evidence_count,
             int(answered), latency_ms, usage.get("prompt_tokens"),
             usage.get("output_tokens"), usage.get("total_tokens"), synth_model),
        )


def _feedback_counts() -> dict:
    up = down = 0
    try:
        with open(FEEDBACK_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("feedback") == "up":
                    up += 1
                elif rec.get("feedback") == "down":
                    down += 1
    except FileNotFoundError:
        pass
    return {"up": up, "down": down}


def usage_overview() -> dict:
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        total = c.execute("SELECT COUNT(*) AS c FROM chat_events").fetchone()["c"]
        answered = c.execute(
            "SELECT COUNT(*) AS c FROM chat_events WHERE answered=1").fetchone()["c"]
        zero_evidence = c.execute(
            "SELECT COUNT(*) AS c FROM chat_events WHERE evidence_count=0").fetchone()["c"]
        distinct_sessions = c.execute(
            "SELECT COUNT(DISTINCT session_id) AS c FROM chat_events "
            "WHERE session_id IS NOT NULL").fetchone()["c"]
        avg_latency = c.execute(
            "SELECT AVG(latency_ms) AS a FROM chat_events WHERE latency_ms IS NOT NULL"
        ).fetchone()["a"]
        tokens = c.execute(
            "SELECT SUM(prompt_tokens) AS p, SUM(output_tokens) AS o, SUM(total_tokens) AS t "
            "FROM chat_events").fetchone()
        last_7d = c.execute(
            "SELECT COUNT(*) AS c FROM chat_events WHERE ts >= ?",
            (time.time() - 7 * 86400,)).fetchone()["c"]
        top_modules = c.execute(
            "SELECT primary_module AS module, COUNT(*) AS c FROM chat_events "
            "WHERE primary_module IS NOT NULL GROUP BY primary_module "
            "ORDER BY c DESC LIMIT 8").fetchall()
        recent = c.execute(
            "SELECT ts, question, primary_module, evidence_count, answered, "
            "latency_ms, total_tokens, synth_model FROM chat_events ORDER BY ts DESC LIMIT 20"
        ).fetchall()

    return {
        "total_questions": total,
        "questions_last_7d": last_7d,
        "answered": answered,
        "answered_rate": (answered / total) if total else None,
        "zero_evidence_count": zero_evidence,
        "zero_evidence_rate": (zero_evidence / total) if total else None,
        "distinct_sessions": distinct_sessions,
        "avg_latency_ms": avg_latency,
        "total_prompt_tokens": tokens["p"] or 0,
        "total_output_tokens": tokens["o"] or 0,
        "total_tokens": tokens["t"] or 0,
        "top_modules": [dict(r) for r in top_modules],
        "recent": [
            {**dict(r), "ts": r["ts"]} for r in recent
        ],
        "feedback": _feedback_counts(),
    }
