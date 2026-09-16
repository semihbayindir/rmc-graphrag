#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://relateddigital.atlassian.net/wiki"


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="RMCKBT")
    ap.add_argument("--out", default="data/confluence_tree.json")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    pages: list[dict] = []
    start = 0
    while True:
        q = urllib.parse.urlencode({
            "spaceKey": args.space, "limit": args.limit, "start": start,
            "expand": "ancestors", "type": "page",
        })
        d = get(f"{BASE}/rest/api/content?{q}")
        res = d.get("results", [])
        for p in res:
            pages.append({
                "id": p.get("id"),
                "title": p.get("title"),
                "path": [a.get("title") for a in (p.get("ancestors") or [])],
            })
        print(f"  {len(pages):,} sayfa...", flush=True)
        if len(res) < args.limit:
            break
        start += args.limit
        time.sleep(0.3)

    json.dump(pages, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    depth = {}
    for p in pages:
        depth[len(p["path"])] = depth.get(len(p["path"]), 0) + 1
    print(f"\n[done] {len(pages):,} sayfa -> {args.out}")
    print(f"  derinlik dağılımı: {dict(sorted(depth.items()))}")
    roots = sorted({(p["path"][0] if p["path"] else p["title"]) for p in pages})
    print(f"  {len(roots)} kök dal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
