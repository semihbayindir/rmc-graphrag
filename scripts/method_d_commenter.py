#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from zendesk_etl.client import ZendeskClient
from zendesk_etl.config import settings
from zendesk_etl.extract import (
    JsonlWriter,
    commenter_search_query,
    fetch_comments,
    get_group_agent_ids,
    load_written_ids,
    resolve_group_ids,
)
from zendesk_etl.normalize import normalize_ticket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=settings.months_back)
    ap.add_argument("--all-statuses", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = sınırsız")
    ap.add_argument(
        "--extra-agents",
        default="",
        help="Ek user_id'ler (virgülle). .env ZENDESK_EXTRA_AGENT_IDS ile birleşir.",
    )
    args = ap.parse_args()

    client = ZendeskClient()

    # 1) SAT gruplarının ID'leri -> ajan user_id'leri
    group_map = resolve_group_ids(client, settings.tech_groups)
    if not group_map:
        raise SystemExit("SAT grubu bulunamadı; ZENDESK_TECH_GROUPS değerini kontrol edin.")

    agent_ids: set[int] = set()
    for gid, gname in group_map.items():
        ids = get_group_agent_ids(client, gid)
        print(f"[grup] {gname} (#{gid}) -> {len(ids)} güncel ajan")
        agent_ids.update(ids)

    # Gruptan ayrılmış eski ajanları ekle (.env + CLI)
    extra = set(settings.extra_agent_ids)
    extra.update(int(x) for x in args.extra_agents.split(",") if x.strip().isdigit())
    new_extra = extra - agent_ids
    if extra:
        print(f"[ek] {len(extra)} eski/ek ajan ID'si (yeni eklenen: {sorted(new_extra)})")
    agent_ids.update(extra)
    print(f"[toplam] {len(agent_ids)} benzersiz SAT ajanı (güncel + eski)")

    # 2) Her ajan için commenter araması. Arama zaten TAM bilet nesnesini döndürür;
    #    yeniden çekmemek için bileti sakla (id -> ticket), dedupe et.
    tickets: dict[int, dict] = {}
    for uid in sorted(agent_ids):
        q = commenter_search_query(uid, args.months, solved_only=not args.all_statuses)
        n_before = len(tickets)
        for t in client.paginate_cursor(
            "search/export.json",
            params={"query": q, "filter[type]": "ticket", "page[size]": 100},
            data_key="results",
        ):
            tickets.setdefault(t["id"], t)
            if args.limit and len(tickets) >= args.limit:
                break
        print(f"  ajan #{uid}: +{len(tickets) - n_before} (toplam benzersiz: {len(tickets)})")
        if args.limit and len(tickets) >= args.limit:
            break

    print(f"[birleşik] {len(tickets)} benzersiz bilet SAT tarafından yorumlanmış")

    # 3) Yorumları çek, normalize et. Resume: daha önce yazılanları atla, dosyaya ekle.
    out = f"{settings.out_norm_dir}/tickets_method_d.jsonl"
    done = load_written_ids(out)
    if done:
        print(f"[resume] {len(done)} bilet zaten yazılmış, atlanacak")
    todo = [tid for tid in sorted(tickets) if tid not in done]
    print(f"[çekilecek] {len(todo)} bilet")

    with JsonlWriter(out, append=True) as writer:
        for i, tid in enumerate(todo, 1):
            comments = fetch_comments(client, tid)
            writer.write(normalize_ticket(tickets[tid], comments))
            if i % 50 == 0:
                print(f"  ...{i}/{len(todo)} bilet çekildi (yorumlarıyla)", flush=True)

    print(f"[done] bu çalışmada {writer.count} bilet eklendi -> {out} "
          f"(toplam ~{len(done) + writer.count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
