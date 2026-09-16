#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys

from bs4 import BeautifulSoup, Tag

SRC = "rmc_nav_menu.txt"
OUT = "data/ui_menu_tree.json"


def _label(li: Tag) -> str:
    """li'nin kendi başlığı: ilk <a>'nın metni (ikon/boşluk temizlenmiş)."""
    a = li.find("a", recursive=False) or li.find("a")
    if not a:
        return ""
    text = a.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _child_ul(li: Tag) -> Tag | None:
    """li'nin alt menüsü olan <ul> (doğrudan çocuk)."""
    return li.find("ul", recursive=False)


def _walk_ul(ul: Tag) -> dict[str, object]:
    """Bir <ul> altındaki li'leri {label: alt-ağaç} olarak döndürür."""
    node: dict[str, object] = {}
    for li in ul.find_all("li", recursive=False):
        label = _label(li)
        if not label:
            continue
        sub = _child_ul(li)
        node[label] = _walk_ul(sub) if sub else {}
    return node


def _flatten(tree: dict[str, object], prefix: str = "") -> list[str]:
    """Ağacı 'A -> B -> C' düz yol listesine çevirir (referans/denetim için)."""
    paths: list[str] = []
    for name, children in tree.items():
        path = f"{prefix} -> {name}" if prefix else name
        if isinstance(children, dict) and children:
            paths.extend(_flatten(children, path))
        else:
            paths.append(path)
    return paths


def main() -> int:
    soup = BeautifulSoup(open(SRC, encoding="utf-8"), "lxml")
    root = soup.select_one("div.nav-menu")
    if root is None:
        raise SystemExit(f"{SRC} içinde div.nav-menu bulunamadı.")

    # nav-menu > (wrapper div) > birden çok top-level <ul>
    tree: dict[str, object] = {}
    for ul in root.find_all("ul"):
        # Sadece en dıştaki ul'lerden başla: bir başka li'nin içindeki ul'leri atla
        if ul.find_parent("li"):
            continue
        merged = _walk_ul(ul)
        for k, v in merged.items():
            tree.setdefault(k, v)

    paths = _flatten(tree)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(tree, fh, ensure_ascii=False, indent=2)

    print(f"[ok] {len(tree)} kök başlık, {len(paths)} yaprak yol -> {OUT}")
    print("Örnek yollar:")
    for p in paths[:12]:
        print("   ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
