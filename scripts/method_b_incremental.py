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
    start_time_epoch,
)
from zendesk_etl.normalize import is_solved, normalize_ticket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Filtreleme yapma, hepsini al")
    args = parser.parse_args()

    client = ZendeskClient()
    group_map = resolve_group_ids(client, settings.tech_groups)
    print(f"[Yöntem B] Hedef gruplar (id->ad): {group_map or '(hepsi)'}")

    start_time = start_time_epoch(settings.months_back)
    out_path = f"{settings.out_norm_dir}/tickets_method_b.jsonl"

    seen = 0
    with JsonlWriter(out_path) as writer:
        stream = client.paginate_incremental(
            "incremental/tickets/cursor.json", start_time=start_time, data_key="tickets"
        )
        for ticket in stream:
            seen += 1
            if not args.all:
                if group_map and ticket.get("group_id") not in group_map:
                    continue
                if not is_solved(ticket):
                    continue
            comments = fetch_comments(client, ticket["id"])
            writer.write(normalize_ticket(ticket, comments))
            if seen % 200 == 0:
                print(f"  ...{seen} tarandı, {writer.count} eşleşti")

    print(f"[Yöntem B] Tamamlandı: {seen} tarandı, {writer.count} kaydedildi -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
