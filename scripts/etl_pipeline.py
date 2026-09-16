#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from zendesk_etl.denoise import build_ticket_text
from zendesk_etl.llm import Extractor, QuotaError

LOCK_PATH = "data/.etl.lock"


def acquire_lock() -> None:
    """Aynı anda ikinci bir ETL çalışmasını engelle (mükerrer yazım kazasına karşı)."""
    if os.path.exists(LOCK_PATH):
        try:
            old_pid = int(open(LOCK_PATH).read().strip())
            os.kill(old_pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            old_pid = None
        else:
            raise SystemExit(
                f"[KİLİT] Zaten çalışan bir ETL var (PID {old_pid}). "
                f"Durdurmak için: kill {old_pid}  |  Kilidi zorla silmek için: rm {LOCK_PATH}"
            )
    with open(LOCK_PATH, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_PATH) and os.remove(LOCK_PATH))


def load_ids(path: str, key: str = "ticket_id") -> set[int]:
    ids: set[int] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        ids.add(json.loads(line)[key])
                    except (ValueError, KeyError):
                        continue
    except FileNotFoundError:
        pass
    return ids


def iter_tickets(paths: list[str]):
    """Birden çok normalize kaynağını sırayla akıtır; mükerrer ID'yi bir kez verir."""
    seen: set[int] = set()
    for path in paths:
        if not os.path.exists(path):
            print(f"  [uyarı] girdi yok, atlanıyor: {path}")
            continue
        n = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tid = rec.get("id")
                if tid in seen:
                    continue
                seen.add(tid)
                n += 1
                yield rec
        print(f"  [girdi] {path}: {n:,} bilet")


def load_team_map(path: str = "data/teams_resolved.json") -> dict[int, str]:
    """author_id -> ekip. SOURCED_FROM atfı için (bkz. data/teams.yaml)."""
    try:
        agents = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"  [uyarı] {path} yok -> ekip atfı yapılmayacak")
        return {}
    return {a["user_id"]: a["team"] for a in agents}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        nargs="+",
        default=["data/normalized/from_dump.jsonl", "data/normalized/from_api.jsonl"],
    )
    ap.add_argument("--teams", default="data/teams_resolved.json")
    ap.add_argument("--output", default="data/graph_ready_tickets.jsonl")
    ap.add_argument("--quarantine", default="data/quarantine_tickets.jsonl")
    ap.add_argument(
        "--skip-ids",
        nargs="*",
        default=[],
        help="Bu JSONL dosyalarındaki ticket_id'ler işlenmez (ör. eski Gemini çıktısı).",
    )
    ap.add_argument("--ui", default="data/ui_menu_tree.json")
    ap.add_argument("--catalog", default="data/clustered_tag_catalog.json")
    ap.add_argument("--api", default="data/api_reference.json")
    ap.add_argument("--workers", type=int, default=50)
    ap.add_argument("--limit", type=int, default=0, help="0 = hepsi")
    ap.add_argument("--retry-quarantine", action="store_true")
    args = ap.parse_args()

    acquire_lock()

    ui_tree_json = json.dumps(json.load(open(args.ui, encoding="utf-8")), ensure_ascii=False)
    tag_catalog_json = json.dumps(json.load(open(args.catalog, encoding="utf-8")), ensure_ascii=False)
    api_reference_json = json.dumps(json.load(open(args.api, encoding="utf-8")), ensure_ascii=False)
    extractor = Extractor(ui_tree_json, tag_catalog_json, api_reference_json)
    team_map = load_team_map(args.teams)
    print(f"[model] {extractor.model} / reasoning_effort={extractor.effort} "
          f"| {len(team_map)} ajan -> ekip eşlemesi")

    done = load_ids(args.output)
    skip = set(done)
    if not args.retry_quarantine:
        skip |= load_ids(args.quarantine)
    prev = set()
    for pth in args.skip_ids:
        prev |= load_ids(pth)
    skip |= prev
    print(f"[resume] {len(done)} işlenmiş, {len(skip) - len(done) - len(prev)} karantinada, "
          f"{len(prev)} önceki koşudan -> atlanacak")

    todo = []
    for t in iter_tickets(args.input):
        if t.get("id") in skip:
            continue
        todo.append(t)
        if args.limit and len(todo) >= args.limit:
            break
    print(f"[çalışılacak] {len(todo)} bilet | {args.workers} işçi")

    out_lock = threading.Lock()
    q_lock = threading.Lock()
    out_fh = open(args.output, "a", encoding="utf-8")
    q_fh = open(args.quarantine, "a", encoding="utf-8")
    counters = {"ok": 0, "quarantine": 0}

    def process(ticket: dict) -> tuple[int, str]:
        tid = ticket.get("id")
        try:
            text = build_ticket_text(ticket)
            result = extractor.extract(tid, text, ticket.get("tags", []))
            # Ekip, grup atamasından değil yorum yazarından türetilir.
            teams = sorted({
                team_map[c["author_id"]]
                for c in ticket.get("comments", [])
                if c.get("author_id") in team_map
            })
            result["source_teams"] = teams
            result["zendesk_group_id"] = ticket.get("group_id")
            result["created_at"] = ticket.get("created_at")
        except QuotaError as exc:
            # Dead-letter queue: hatalı bileti karantinaya al, akışı DURDURMA.
            with q_lock:
                q_fh.write(json.dumps({"ticket_id": tid, "error": str(exc)}, ensure_ascii=False) + "\n")
                q_fh.flush()
                counters["quarantine"] += 1
            return tid, "quarantine"
        except Exception as exc:  # noqa: BLE001 - beklenmedik hata da karantinaya
            with q_lock:
                q_fh.write(json.dumps({"ticket_id": tid, "error": f"unexpected: {exc}"}, ensure_ascii=False) + "\n")
                q_fh.flush()
                counters["quarantine"] += 1
            return tid, "quarantine"
        with out_lock:
            out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_fh.flush()  # append + flush: kesintide veri kaybı yok
            counters["ok"] += 1
        return tid, "ok"

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(process, t) for t in todo]
            for i, fut in enumerate(as_completed(futures), 1):
                tid, status = fut.result()
                if i % 25 == 0 or status == "quarantine":
                    total = counters["ok"] + counters["quarantine"]
                    print(f"  [{total}/{len(todo)}] #{tid} -> {status} "
                          f"(ok={counters['ok']}, karantina={counters['quarantine']})", flush=True)
    finally:
        out_fh.close()
        q_fh.close()

    print(f"[done] {counters['ok']} başarılı, {counters['quarantine']} karantina -> {args.output}")
    st = extractor.stats
    print(f"[openai] {st['calls']:,} çağrı | prompt {st['prompt_tokens']:,} tok "
          f"(cache %{extractor.cache_ratio()*100:.0f}) | çıktı {st['completion_tokens']:,} tok")

    if counters["ok"]:
        records = [json.loads(l) for l in open(args.output, encoding="utf-8") if l.strip()]
        json_path = args.output.rsplit(".", 1)[0] + ".json"
        json.dump(records, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[done] birleşik dizi -> {json_path} ({len(records)} kayıt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
