#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from typing import Optional

from bs4 import BeautifulSoup

WIKI = "https://relateddigital.atlassian.net/wiki"
ROOTS = {"REST": "428802257", "SOAP": "428966381"}
OUT = "data/api_docs_v2.jsonl"

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_H2 = re.compile(r"<h2([^>]*)>(.*?)</h2>", re.S)
_ID_ATTR = re.compile(r'\bid="([^"]+)"')
# Tek kelimelik ama metot olmayan başlıklar.
_NOT_METHOD = {"overview", "introduction", "parameters", "parametreler", "request", "response",
               "example", "examples", "notes", "errors", "genel", "general", "methods"}
MIN_GENERAL_CHARS = 200


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return {}


def plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def method_name(heading: str) -> Optional[str]:
    """h2 metni bir metot adı mı? Küçük harf/rakamla başlayan parça öncekine
    eklenir (Confluence bölmesi); başka boşluk kalırsa metot değildir."""
    parts = heading.split()
    if not parts:
        return None
    name = parts[0]
    for p in parts[1:]:
        if p[0].islower() or p[0].isdigit():
            name += p
        else:
            return None
    # Küçük harf şartı: "MAYIS2018" gibi sürüm notu başlıkları metot değildir.
    if not _IDENT.match(name) or name.lower() in _NOT_METHOD or name.upper() == name:
        return None
    return name


def to_text(fragment: str) -> str:
    """HTML parçasını okunur metne çevirir: tablolar satır satır ' | ', örnek
    istekler kod bloğu, h3+ alt başlıklar '## ' ile korunur."""
    soup = BeautifulSoup(fragment, "lxml")
    for bad in soup(["script", "style"]):
        bad.decompose()
    for pre in soup.find_all("pre"):
        pre.replace_with("\n```\n" + pre.get_text() + "\n```\n")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
        tr.replace_with(" | ".join(c for c in cells) + "\n")
    for h in soup.find_all(re.compile(r"^h[3-6]$")):
        h.replace_with("\n## " + h.get_text(" ", strip=True) + "\n")
    text = soup.get_text("\n")
    text = re.sub(r"Back to Top\s*\^", "", text)  # Confluence gezinme bağlantısı, içerik değil
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def index_summaries(page_html: str) -> dict[str, str]:
    """Sayfa başındaki özet tablosu: '#Sayfa-Metot' linkli satırların 2. hücresi."""
    out: dict[str, str] = {}
    soup = BeautifulSoup(page_html, "lxml")
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        a = cells[0].find("a", href=re.compile(r"^#")) if len(cells) >= 2 else None
        if a:
            name = re.sub(r"\s+", "", a.get_text())
            desc = cells[1].get_text(" ", strip=True)
            if name and desc:
                out.setdefault(name.lower(), desc)
    return out


def split_page(protocol: str, page: dict) -> list[dict]:
    html = page["body"]["view"]["value"]
    service = page["title"].strip()
    url = WIKI + page["_links"]["webui"]
    summaries = index_summaries(html)
    heads = list(_H2.finditer(html))

    docs, general = [], [html[: heads[0].start()] if heads else html]
    seen: dict[str, int] = {}
    for n, h in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else len(html)
        body = html[h.end(): end]
        name = method_name(plain(h.group(2)))
        if not name:
            general.append(h.group(0) + body)  # başlığıyla birlikte genel bölüme
            continue
        key = name.lower()
        seen[key] = seen.get(key, 0) + 1
        anchor = _ID_ATTR.search(h.group(1))
        docs.append({
            "id": f"{protocol}:{service}:{name}" + (f"#{seen[key]}" if seen[key] > 1 else ""),
            "protocol": protocol, "service": service, "method": name,
            "summary": summaries.get(key, ""),
            "url": url + (f"#{anchor.group(1)}" if anchor else ""),
            "text": to_text(body),
        })

    general_text = to_text("".join(general))
    if len(general_text) >= MIN_GENERAL_CHARS:
        docs.insert(0, {
            "id": f"{protocol}:{service}:genel", "protocol": protocol, "service": service,
            "method": None, "summary": "", "url": url, "text": general_text,
        })
    for d in docs:
        d["page_id"] = page["id"]
        d["chars"] = len(d["text"])
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    docs: list[dict] = []
    for protocol, root in ROOTS.items():
        pages = get(f"{WIKI}/rest/api/content/{root}/descendant/page"
                    f"?limit=200&expand=body.view")["results"]
        print(f"\n== {protocol}: {len(pages)} sayfa")
        for page in pages:
            part = split_page(protocol, page)
            docs += part
            methods = [d for d in part if d["method"]]
            gen = next((d for d in part if not d["method"]), None)
            longest = max((d["chars"] for d in methods), default=0)
            print(f"  {page['title'][:44]:<44} {len(methods):>3} metot"
                  f" | genel {gen['chars'] if gen else 0:>6,} kr | en uzun metot {longest:>6,} kr"
                  f" | özetli {sum(1 for d in methods if d['summary']):>3}")
            print("     " + ", ".join(d["method"] for d in methods)[:600])

    with open(args.out, "w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    methods = [d for d in docs if d["method"]]
    lens = sorted(d["chars"] for d in docs)
    print(f"\n[done] {len(docs)} bölüm ({len(methods)} metot + {len(docs) - len(methods)} genel) -> {args.out}")
    print(f"  bölüm uzunluğu: medyan {lens[len(lens) // 2]:,} kr, en uzun {lens[-1]:,} kr, "
          f"toplam {sum(lens):,} kr | boş metinli metot: {sum(1 for d in methods if d['chars'] < 50)}")

    print(f"  tekil metot adı: {len({d['method'].lower() for d in methods})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
