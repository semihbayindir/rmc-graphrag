#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, collections, sys
import yaml

from scripts.cluster_discovery import stems, jac, cluster_areas, norm

# Eski taksonomi -> yeni ontoloji. Yalnızca 3. adım fallback'i; keşif kaydı
# olmayan ~400 incident için. Belirsiz olanlar bilinçli olarak None bırakıldı.
OLD2NEW = {
    "Email Engine": "Email Engine", "Campaign Management": "Kampanya Yönetimi",
    "Data Management": "Üye Yükleme", "Account & User Management": "Panel Erişimi",
    "CDP & Segmentation": "Segmentasyon", "Reporting & Analytics": "Kampanya Raporları",
    "REST/SOAP API": "REST/SOAP API", "REST API": "REST/SOAP API",
    "SOAP Web Service": "REST/SOAP API", "Integration": "Üye Entegrasyonu",
    "Mobile Push": "Mobile Push", "Web Push": "Web Push", "SMS Gateway": "SMS Gateway",
    "System & Infrastructure": "Email Deliverability", "Access / Infrastructure": "Panel Erişimi",
    "Content & Template Management": "Email Template",
    "Consent Management (IYS)": "Consent / İYS", "Web Recommendation": "Web Recommendation",
    "Target": "Target Kurguları", "Audience": "Segmentasyon", "Segment": "Segmentasyon",
    "Analytics": "Custom Report", "Autopilot": "Autopilot",
    "Autopilot & Triggering": "Autopilot", "A/B Testing": "A/B Testing",
    "In-App Messaging": "In-App Messaging", "Recommend": "Web Recommendation",
    "Management": "Kullanıcı ve Yetki Yönetimi", "Settings": "Kullanıcı ve Yetki Yönetimi",
    "Campaign": "Kampanya Yönetimi", "DevOps & ETL": "Scheduled Export",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ontology", default="ontology/v1.yaml")
    ap.add_argument("--discovery", default="data/ontology_discovery.jsonl")
    ap.add_argument("--incidents", default="data/graph_ready_v3.jsonl")
    ap.add_argument("--out", default="data/module_map.jsonl")
    ap.add_argument("--thr", type=float, default=0.5)
    args = ap.parse_args()

    ont = yaml.safe_load(open(args.ontology, encoding="utf-8"))
    label2mod = {}
    for m in ont["modules"]:
        for a in (m.get("birlesen") or []):
            label2mod[norm(a)] = m["name"]
    print(f"[ontoloji] {len(ont['modules'])} modül · {len(label2mod)} etiket")

    disc = {}
    for l in open(args.discovery, encoding="utf-8"):
        r = json.loads(l)
        disc[(r["ticket_id"], r["incident_id"])] = r["area"]
    areas = sorted({a for a in disc.values() if norm(a)})
    print(f"[keşif] {len(disc):,} kayıt · {len(areas):,} benzersiz ifade")

    # 1) ham ifade -> küme -> küme etiketi -> modül
    cmap = cluster_areas(areas, args.thr)
    members = collections.defaultdict(list)
    for a in areas:
        members[cmap[a]].append(a)
    freq = collections.Counter(disc.values())
    area2mod = {}
    for cid, mem in members.items():
        lbl = max(mem, key=lambda x: freq[x])          # kümenin en sık varyantı
        mod = label2mod.get(norm(lbl))
        if mod is None:                                 # küme etiketi tutmadıysa üyelere bak
            for a in mem:
                if norm(a) in label2mod:
                    mod = label2mod[norm(a)]
                    break
        if mod:
            for a in mem:
                area2mod[a] = mod
    print(f"[adım 1] {len(members):,} küme -> {len(area2mod):,} ifade eşlendi")

    # 2) kalan ifadeler: ontoloji etiketleriyle kök benzerliği
    ont_stems = [(norm(k), stems(k), v) for k, v in label2mod.items()]
    step2 = 0
    for a in areas:
        if a in area2mod:
            continue
        sa = stems(a)
        best, bv = None, 0.0
        for _, sk, mod in ont_stems:
            v = jac(sa, sk)
            if v > bv:
                best, bv = mod, v
        if best and bv >= args.thr:
            area2mod[a] = best
            step2 += 1
    print(f"[adım 2] kök benzerliğiyle +{step2:,} ifade")

    # 3) kalanlar: incident'in kendi metnini modül anahtar-kelime profiline eşle.
    cand = json.load(open("data/ontology_candidates.json", encoding="utf-8"))
    lbl2kw = {norm(c["area"]): c["keywords"] for c in cand}
    mod_kw: dict[str, set[str]] = collections.defaultdict(set)
    for lbl, mod in label2mod.items():
        for k in lbl2kw.get(lbl, []):
            kk = norm(k)
            if len(kk) >= 4:
                mod_kw[mod].add(kk)
    # çok yaygın terimler ayırt etmez: 3+ modülde geçenleri at
    freq_kw = collections.Counter(k for v in mod_kw.values() for k in v)
    for mod in mod_kw:
        mod_kw[mod] = {k for k in mod_kw[mod] if freq_kw[k] <= 2}
    print(f"[adım 3] {len(mod_kw)} modül için anahtar-kelime profili "
          f"(ort {sum(len(v) for v in mod_kw.values())//max(len(mod_kw),1)} terim)")

    inc_text = {}
    for l in open(args.incidents, encoding="utf-8"):
        r = json.loads(l)
        for i in r["incidents"]:
            inc_text[(r["ticket_id"], i["incident_id"])] = norm(
                " ".join([i["symptom"], i["findings"] or "",
                          " ".join(str(a) for a in i["technical_artifacts"][:12])])[:1500])

    def by_keywords(k):
        t = inc_text.get(k, "")
        if not t:
            return None
        best, bs = None, 0
        for mod, kws in mod_kw.items():
            sc = sum(1 for w in kws if w in t)
            if sc > bs:
                best, bs = mod, sc
        return best if bs >= 2 else None

    stats = collections.Counter()
    permod = collections.Counter()
    unmapped = collections.Counter()
    with open(args.out, "w", encoding="utf-8") as out:
        for l in open(args.incidents, encoding="utf-8"):
            r = json.loads(l)
            for i in r["incidents"]:
                k = (r["ticket_id"], i["incident_id"])
                mod, how = None, None
                if i["outcome"] == "none":
                    how = "none"
                else:
                    a = disc.get(k)
                    if a and a in area2mod:
                        mod, how = area2mod[a], "kesif"
                    else:
                        mod = by_keywords(k)
                        how = "anahtar_kelime" if mod else None
                        if not mod:
                            mod = OLD2NEW.get(i["affected_component"]["module"])
                            how = "eski_modul" if mod else "eslesmedi"
                            if not mod and a:
                                unmapped[a] += 1
                stats[how] += 1
                if mod:
                    permod[mod] += 1
                out.write(json.dumps({"ticket_id": k[0], "incident_id": k[1],
                                      "module": mod, "kaynak": how}, ensure_ascii=False) + "\n")

    tot = sum(stats.values())
    bilgi = tot - stats["none"]
    print(f"\n=== SONUÇ ({tot:,} incident) ===")
    print(f"  outcome=none          {stats['none']:>7,}")
    print(f"  keşif zinciriyle      {stats['kesif']:>7,}  (%{100*stats['kesif']/bilgi:.1f})")
    print(f"  anahtar kelimeyle     {stats['anahtar_kelime']:>7,}  (%{100*stats['anahtar_kelime']/bilgi:.1f})")
    print(f"  eski modül fallback   {stats['eski_modul']:>7,}  (%{100*stats['eski_modul']/bilgi:.1f})")
    print(f"  eşleşmedi (null)      {stats['eslesmedi']:>7,}  (%{100*stats['eslesmedi']/bilgi:.1f})")
    print(f"\n  kullanılan modül: {len(permod)}/{len(ont['modules'])}")
    print(f"  en büyük 8: {dict(permod.most_common(8))}")
    kullanilmayan = [m['name'] for m in ont['modules'] if m['name'] not in permod]
    print(f"  hiç kullanılmayan: {kullanilmayan}")
    if unmapped:
        print(f"\n  eşleşmeyen ifadeler (ilk 8): {dict(unmapped.most_common(8))}")
    json.dump(dict(permod.most_common()), open("data/module_dist.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
