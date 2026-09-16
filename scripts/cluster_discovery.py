#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re, sys, collections, unicodedata

TR = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")


def norm(s: str) -> str:
    s = (s or "").strip().lower().translate(TR)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Kök kırpma ile deterministik kümeleme.
#   "gönderme"/"gönderimi"/"gönderim" -> "gonde"
#   "bildirim"/"bildirimleri"         -> "bildi"
_GENERIC = {"ile", "icin", "olan", "bir", "ve", "veya", "sorun", "hata", "islem", "genel"}


def stems(area: str) -> frozenset[str]:
    out = set()
    for w in norm(area).split():
        if len(w) < 3 or w in _GENERIC:
            continue
        out.add(w[:5])
    return frozenset(out)


def jac(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class UF:
    """Union-find: tek bağlantılı (single-linkage) kümeleme."""

    def __init__(self, n): self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def cluster_areas(areas: list[str], thr: float) -> dict[str, int]:
    """Tam bağlantı kümeleme: iki küme ancak tüm çapraz çiftleri eşiği geçerse birleşir."""
    S = [stems(a) for a in areas]
    n = len(areas)
    # aday çiftler: ortak kökü olanlar (O(n^2) taramadan kaçın)
    inv = collections.defaultdict(list)
    for i, st in enumerate(S):
        for t in st:
            inv[t].append(i)
    pairs = {}
    for t, idxs in inv.items():
        if len(idxs) > 4000:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if (i, j) in pairs:
                    continue
                v = jac(S[i], S[j])
                if v >= thr:
                    pairs[(i, j)] = v
    cl = {i: [i] for i in range(n)}
    owner = list(range(n))
    for (i, j), _ in sorted(pairs.items(), key=lambda x: -x[1]):
        ci, cj = owner[i], owner[j]
        if ci == cj:
            continue
        # tam bağlantı koşulu: her çapraz çift eşiği geçmeli
        if all(jac(S[x], S[y]) >= thr for x in cl[ci] for y in cl[cj]):
            cl[ci].extend(cl[cj])
            for y in cl[cj]:
                owner[y] = ci
            del cl[cj]
    return {a: owner[i] for i, a in enumerate(areas)}


def load_anchors():
    a = {}
    try:
        for p in json.load(open("data/confluence_tree.json", encoding="utf-8")):
            for seg in (p["path"] + [p["title"]]):
                k = norm(seg)
                if 2 < len(k) < 60:
                    a.setdefault(k, set()).add("confluence")
    except FileNotFoundError:
        pass
    try:
        ui = json.load(open("data/ui_menu_tree.json", encoding="utf-8"))
        for m, subs in ui.items():
            a.setdefault(norm(m), set()).add("ui")
            for s in subs:
                a.setdefault(norm(s), set()).add("ui")
    except FileNotFoundError:
        pass
    try:
        api = json.load(open("data/api_reference.json", encoding="utf-8"))
        names = api if isinstance(api, list) else list(api.keys()) if isinstance(api, dict) else []
        for n in names:
            a.setdefault(norm(str(n)), set()).add("api")
    except FileNotFoundError:
        pass
    return a


# Çapa adı olarak işe yaramayacak kadar genel olanlar.
_ANCHOR_STOP = {
    "email", "e posta", "posta", "mail", "push", "sms", "campaign", "kampanya",
    "gonderim", "genel", "rapor", "report", "data", "veri", "temp", "test",
    "api", "url", "list", "liste", "user", "kullanici", "settings", "ayarlar",
}
_MIN_ANCHOR = 8


def anchor_of(label: str, objs: list[str], kws: list[str], anchors: dict) -> tuple[str, str, str]:
    """Çapa eşlemesi: önce tam, sonra en az _MIN_ANCHOR karakterlik ve _ANCHOR_STOP dışı kısmi."""
    def exact(txt):
        k = norm(txt)
        return ("tam", "+".join(sorted(anchors[k])), txt) if k and k in anchors else None

    def partial(txt):
        k = norm(txt)
        if not k or len(k) < _MIN_ANCHOR:
            return None
        best = None
        for ak, src in anchors.items():
            if len(ak) < _MIN_ANCHOR or ak in _ANCHOR_STOP:
                continue
            if ak in k or k in ak:
                # eşleşen kısım, kısa olanın en az %70'ini kaplamalı
                if min(len(ak), len(k)) / max(len(ak), len(k)) >= 0.7:
                    cand = ("kısmi", "+".join(sorted(src)), f"{txt} ~ {ak}")
                    if best is None:
                        best = cand
        return best

    cands = [label] + [o for o in objs if o] + [k for k in kws if k]
    for c in cands:
        h = exact(c)
        if h:
            return h
    for c in cands:
        h = partial(c)
        if h:
            return h
    return ("YOK", "", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/ontology_discovery.jsonl")
    ap.add_argument("--min", type=int, default=8, help="küme için asgari incident")
    ap.add_argument("--thr", type=float, default=0.5, help="kök Jaccard eşiği")
    ap.add_argument("--out", default="data/ontology_candidates.json")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.inp, encoding="utf-8")]
    print(f"[giriş] {len(rows):,} keşif kaydı")

    raw = collections.Counter(r["area"] for r in rows)
    uniq = sorted(raw)
    cmap = cluster_areas(uniq, args.thr)
    canon = collections.Counter()
    members = collections.defaultdict(list)
    variants = collections.defaultdict(set)
    for r in rows:
        a = r["area"]
        if not norm(a):
            continue
        cid = cmap.get(a)
        canon[cid] += 1
        variants[cid].add(a)
        members[cid].append(r)
    # küme etiketi: en sık geçen varyant
    label = {cid: collections.Counter(m["area"] for m in members[cid]).most_common(1)[0][0]
             for cid in members}
    print(f"[normalize] {len(raw):,} ham alan -> {len(canon):,} küme "
          f"(eşik {args.thr}, %{100*(1-len(canon)/max(len(raw),1)):.0f} tekilleşme)")

    anchors = load_anchors()
    print(f"[çapa] {len(anchors):,} benzersiz çapa adı yüklendi")

    out = []
    for cid, n in canon.most_common():
        if n < args.min:
            continue
        lbl = label[cid]
        mods = collections.Counter(m["old_module"] for m in members[cid])
        kws = collections.Counter(w for m in members[cid] for w in m["keywords"])
        objs = collections.Counter(m["object"] for m in members[cid] if m["object"])
        top_kw = [w for w, _ in kws.most_common(8)]
        top_ob = [o for o, _ in objs.most_common(4)]
        kind, src, via = anchor_of(lbl, top_ob, top_kw, anchors)
        out.append({
            "area": lbl, "count": n, "varyant_sayisi": len(variants[cid]),
            "varyantlar": sorted(variants[cid])[:8],
            "anchor": kind, "anchor_source": src, "anchor_via": via,
            "eski_moduller": dict(mods.most_common(3)),
            "keywords": top_kw,
            "objeler": top_ob,
            "ornek_ticketlar": [m["ticket_id"] for m in members[cid][:5]],
        })
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    byk = collections.Counter(o["anchor"] for o in out)
    cov = sum(o["count"] for o in out)
    print(f"\n[küme] >={args.min} incident: {len(out)} küme, {cov:,} incident "
          f"(%{100*cov/len(rows):.0f} kapsam)")
    for k in ("tam", "kısmi", "YOK"):
        c = [o for o in out if o["anchor"] == k]
        print(f"  çapa {k:<6}: {len(c):>4} küme | {sum(o['count'] for o in c):>6,} incident")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
