#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from zendesk_etl.client import ZendeskClient
from zendesk_etl.config import settings
from zendesk_etl.extract import (
    JsonlWriter,
    fetch_comments,
    resolve_group_ids,
    solved_search_query,
    start_time_epoch,
)
from zendesk_etl.normalize import is_solved, normalize_ticket


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--search", action="store_true", help="Yöntem A (Search Export) kullan")
    args = ap.parse_args()

    client = ZendeskClient()

    me = client.get("users/me.json").get("user", {})
    print(f"[ok] Bağlandı: {me.get('name')} <{me.get('email')}> | rol={me.get('role')}")
    print(f"[cfg] subdomain={settings.subdomain}  gruplar={settings.tech_groups}  ay={settings.months_back}")

    out = f"{settings.out_norm_dir}/smoke_test.jsonl"
    with JsonlWriter(out) as writer:
        if args.search:
            query = solved_search_query(settings.tech_groups, settings.months_back)
            print(f"[Yöntem A] {query}")
            stream = client.paginate_cursor(
                "search/export.json",
                params={"query": query, "filter[type]": "ticket", "page[size]": 100},
                data_key="results",
            )
            for ticket in stream:
                comments = fetch_comments(client, ticket["id"])
                writer.write(normalize_ticket(ticket, comments))
                print(f"  #{ticket['id']} [{ticket.get('status')}] {ticket.get('subject')!r} "
                      f"({len(comments)} yorum, {sum(1 for c in comments if c.get('public') is False)} internal)")
                if writer.count >= args.limit:
                    break
        else:
            group_map = resolve_group_ids(client, settings.tech_groups)
            print(f"[Yöntem B] hedef gruplar: {group_map or '(hepsi)'}")
            stream = client.paginate_incremental(
                "incremental/tickets/cursor.json",
                start_time=start_time_epoch(settings.months_back),
                data_key="tickets",
            )
            scanned = 0
            for ticket in stream:
                scanned += 1
                if scanned % 100 == 0:
                    print(f"  ...{scanned} bilet tarandı, {writer.count} eşleşti", flush=True)
                if group_map and ticket.get("group_id") not in group_map:
                    continue
                if not is_solved(ticket):
                    continue
                comments = fetch_comments(client, ticket["id"])
                writer.write(normalize_ticket(ticket, comments))
                print(f"  #{ticket['id']} [{ticket.get('status')}] {ticket.get('subject')!r} "
                      f"({len(comments)} yorum, {sum(1 for c in comments if c.get('public') is False)} internal)")
                if writer.count >= args.limit:
                    break
            print(f"[info] {scanned} bilet tarandı, {writer.count} eşleşti")

    print(f"[done] {writer.count} bilet -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
