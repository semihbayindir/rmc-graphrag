#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zendesk_etl.client import ZendeskClient
from zendesk_etl.config import settings


def count(client: ZendeskClient, query: str) -> int:
    """search.json 'count' alanı — tüm eşleşmeleri saymanın en ucuz yolu."""
    res = client.get("search.json", params={"query": query, "filter[type]": "ticket"})
    return res.get("count", 0)


def main() -> int:
    client = ZendeskClient()
    since = (datetime.now(timezone.utc) - timedelta(days=settings.months_back * 30)).strftime("%Y-%m-%d")
    g = settings.tech_groups[0]

    variants = {
        "grup + solved>= + tarih (mevcut sorgu)": f'type:ticket status>=solved created>={since} group:"{g}"',
        "grup + solved>= (tarihsiz)":            f'type:ticket status>=solved group:"{g}"',
        "grup (tüm statüler, tarihsiz)":          f'type:ticket group:"{g}"',
        "grup + sadece solved":                   f'type:ticket status:solved group:"{g}"',
        "grup + sadece closed":                   f'type:ticket status:closed group:"{g}"',
        "grup + open/pending":                    f'type:ticket status<solved group:"{g}"',
        "grup + created>= (statüsüz)":            f'type:ticket created>={since} group:"{g}"',
        "grup + UPDATED>= + solved":              f'type:ticket status>=solved updated>={since} group:"{g}"',
        "grup + UPDATED>= (statüsüz)":            f'type:ticket updated>={since} group:"{g}"',
    }
    print(f"Grup: {g!r}  | tarih eşiği: {since}\n")
    for label, q in variants.items():
        print(f"  {count(client, q):>6}  {label}")
        print(f"          query = {q}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
