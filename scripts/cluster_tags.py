#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from zendesk_etl.llm import cluster_tags

INPUT = "data/normalized/tickets_method_d.jsonl"
OUT = "data/clustered_tag_catalog.json"


def collect_unique_tags(path: str) -> list[str]:
    tags: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                tags.update(json.loads(line).get("tags", []))
    return sorted(tags)


def main() -> int:
    tags = collect_unique_tags(INPUT)
    print(f"[Faz 0] {len(tags)} benzersiz etiket toplandı")
    if not tags:
        raise SystemExit("Etiket bulunamadı; önce bilet çekimini yapın.")

    catalog = cluster_tags(tags)
    json.dump(catalog, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    modules = catalog.get("catalog", [])
    print(f"[Faz 0] {len(modules)} modül kümesi -> {OUT}")
    for m in modules:
        subs = [s["sub_component"] for s in m.get("sub_components", [])]
        print(f"   {m['module']}: {', '.join(subs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
