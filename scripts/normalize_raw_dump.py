#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from zendesk_etl.normalize import normalize_ticket, is_solved

SRC = "data/raw/old_tickets_raw.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--scope", default="data/scope_ids.json")
    ap.add_argument("--out", default="data/normalized/from_dump.jsonl")
    ap.add_argument("--missing", default="data/missing_ids.json")
    ap.add_argument("--solved-only", action="store_true", default=True)
    args = ap.parse_args()

    scope: set[int] | None = None
    try:
        scope = set(json.load(open(args.scope, encoding="utf-8")))
        print(f"[kapsam] {len(scope):,} bilet ID'si yüklendi")
    except FileNotFoundError:
        print("[kapsam] dosya yok -> dökümdeki TÜM biletler alınacak")

    seen: set[int] = set()
    written = skipped_scope = skipped_status = 0
    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out:
        for line in open(args.src, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            t = rec.get("ticket") or {}
            tid = t.get("id")
            if tid is None:
                continue
            if scope is not None and tid not in scope:
                skipped_scope += 1
                continue
            if args.solved_only and not is_solved(t):
                skipped_status += 1
                continue
            norm = normalize_ticket(t, rec.get("comments") or [])
            # dökümden gelen ek bilgi: grup adı ve çekim zamanı (çapraz kontrol için)
            norm["zendesk_group_name"] = rec.get("zendesk_group_name")
            norm["source"] = "raw_dump"
            out.write(json.dumps(norm, ensure_ascii=False) + "\n")
            seen.add(tid)
            written += 1

    print(f"[yazıldı] {written:,} bilet -> {args.out}")
    print(f"  kapsam dışı atlanan : {skipped_scope:,}")
    print(f"  statü dışı atlanan  : {skipped_status:,}")

    if scope is not None:
        missing = sorted(scope - seen)
        json.dump(missing, open(args.missing, "w"), indent=0)
        print(f"[eksik] {len(missing):,} bilet dökümde YOK -> {args.missing}")
        print("  bunlar Zendesk'ten çekilecek (scripts.fetch_missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
