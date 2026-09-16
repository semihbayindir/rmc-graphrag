#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from zendesk_etl.client import ZendeskClient
from zendesk_etl.extract import JsonlWriter, fetch_comments, load_written_ids
from zendesk_etl.normalize import normalize_ticket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="data/missing_ids.json")
    ap.add_argument("--out", default="data/normalized/from_api.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true", default=True)
    args = ap.parse_args()

    ids = json.load(open(args.ids, encoding="utf-8"))
    done = load_written_ids(args.out) if args.resume else set()
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[giriş] {len(ids):,} eksik bilet | {len(done):,} zaten yazılmış | {len(todo):,} çekilecek")
    if not todo:
        print("[done] çekilecek bilet yok")
        return 0

    client = ZendeskClient()
    lock = threading.Lock()
    writer = JsonlWriter(args.out, append=bool(done))
    counters = {"ok": 0, "fail": 0}
    failures: list[tuple[int, str]] = []

    def work(tid: int):
        try:
            t = client.get(f"tickets/{tid}.json")["ticket"]
            cs = fetch_comments(client, tid)
            rec = normalize_ticket(t, cs)
            rec["zendesk_group_name"] = None  # döküm dışı; grup id'si zaten kayıtta
            rec["source"] = "api"
            with lock:
                writer.write(rec)
                counters["ok"] += 1
                n = counters["ok"] + counters["fail"]
                if n % 50 == 0:
                    print(f"  {n}/{len(todo)}  (ok={counters['ok']}, hata={counters['fail']})", flush=True)
        except Exception as exc:  # noqa: BLE001
            with lock:
                counters["fail"] += 1
                failures.append((tid, str(exc)[:120]))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(as_completed([pool.submit(work, t) for t in todo]))

    writer.close()
    print(f"\n[done] ok={counters['ok']:,} hata={counters['fail']:,} -> {args.out}")
    print(f"[oauth] token {client.token.refresh_count} kez alındı/yenilendi")
    if failures:
        json.dump(failures, open("data/fetch_failures.json", "w"), ensure_ascii=False, indent=2)
        print(f"  hatalar -> data/fetch_failures.json (ilk 3: {failures[:3]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
