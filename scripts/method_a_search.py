#!/usr/bin/env python3
from __future__ import annotations

import sys

from zendesk_etl.client import ZendeskClient
from zendesk_etl.config import settings
from zendesk_etl.extract import JsonlWriter, fetch_comments, solved_search_query
from zendesk_etl.normalize import normalize_ticket


def main() -> int:
    client = ZendeskClient()
    query = solved_search_query(settings.tech_groups, settings.months_back)
    print(f"[Yöntem A] Search sorgusu: {query}")

    out_path = f"{settings.out_norm_dir}/tickets_method_a.jsonl"
    with JsonlWriter(out_path) as writer:
        results = client.paginate_cursor(
            "search/export.json",
            params={"query": query, "filter[type]": "ticket", "page[size]": 100},
            data_key="results",
        )
        for ticket in results:
            comments = fetch_comments(client, ticket["id"])
            writer.write(normalize_ticket(ticket, comments))
            if writer.count % 50 == 0:
                print(f"  ...{writer.count} bilet işlendi")

    print(f"[Yöntem A] Tamamlandı: {writer.count} bilet -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
