#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import collections

# --- normalizasyon: ___data_loading / _data_loading__ / data_loading -> data_loading
_UND = re.compile(r"_+")
_TYPO = {"taget": "target", "analytic": "analytics", "servis": "service"}


def norm_tag(t: str) -> str:
    t = _UND.sub("_", (t or "").strip().strip("_").lower())
    for a, b in _TYPO.items():
        t = t.replace(a, b)
    return t


# --- eksen sözlükleri: (etiket kalıpları, metin kalıpları) ---
CHANNEL = {
    "email":       (["email", "mail", "em_integration", "deliverability"],
                    r"\b(e-?posta|e-?mail|mail|gönderen adı|smtp|deliverability|spam)"),
    "sms":         (["sms"], r"\bsms\b"),
    "mobile_push": (["mobile_push", "app_push", "mobil", "sdk", "geofence"],
                    r"\b(mobil push|app push|mobile push|android|ios|firebase|huawei|sdk)"),
    "web_push":    (["web_push"], r"\bweb push\b"),
    "in_app":      (["inapp"], r"\b(in-?app|uygulama içi)"),
    "web_reco":    (["web_recommendation", "recommendation"], r"\b(recommend|öneri motoru|reco)"),
    "cdp":         (["cdp"], r"\bcdp\b"),
}

# Türkçe sondan eklemeli: desenlerde sondaki \b kullanılmaz ("yükle" -> "yüklendi").
ACTIVITY = {
    "error":       (["error", "alert", "failure", "health_check"],
                    r"\b(hata|çalışmıyor|çalışmadı|alınamı|başarısız|kesinti|alarm|exception|timeout|düşüyor|patlıyor)"),
    "complaint":   (["complaint"], r"\b(şikayet|memnuniyetsiz|müşteri rahatsız)"),
    "report":      (["report"], r"\b(rapor|dışa aktar|export|raporlama)"),
    "creation":    (["creation", "create"], r"\b(oluştur|hazırla|kurgu kur|kampanya kur|tasarla|yarat)"),
    "integration": (["integration"], r"\b(entegrasyon|integration|web service|endpoint|api çağrı|sdk kur)"),
    "data_ops":    (["data_loading", "data_export", "data_update", "data_deleting", "data_limit"],
                    r"\b(veri yükle|data yükle|liste yükle|veri güncelle|veri sil|toplu yükle|import|veri aktar|yükleme)"),
    "transaction": (["transactional"], r"\b(transactional|işlemsel|tekil gönderim)"),
    "settings":    (["setting", "configuration"], r"\b(ayar|konfigürasyon|tanımla|yapılandır)"),
    "access":      (["reset_password", "subuser", "user_creation", "whitelist"],
                    r"\b(şifre|parola|kullanıcı aç|yetki|erişim|ip whitelist|hesap aç|giriş yapamı|login)"),
    "scheduled":   (["scheduled"], r"\b(zamanlan|scheduled|planlanmış gönderim)"),
    "triggered":   (["trigger"], r"\b(tetikle|triggered|otomatik gönderim)"),
}


# Biletlerin bu oranından fazlasında geçen etiketler eksen sinyali sayılmaz.
STOP_RATIO = 0.20


def build_stoplist(tags_by: dict[int, set[str]]) -> set[str]:
    n = len(tags_by)
    c: collections.Counter = collections.Counter()
    for v in tags_by.values():
        for t in v:
            c[t] += 1
    return {t for t, k in c.items() if k / n > STOP_RATIO}


def _tag_hit(tag: str, pat: str) -> bool:
    """Alt dizi DEĞİL, sınır duyarlı eşleşme: 'account' -> 'account' evet,
    'account_settings' evet, ama 'my_account_x' gibi gevşek eşleşmeler dışarıda."""
    return tag == pat or tag.startswith(pat + "_") or tag.endswith("_" + pat) or f"_{pat}_" in tag


def _match(axis: dict, tags: set[str], text: str, require_text: bool = False) -> list[str]:
    """require_text=True ise etiket tek başına yetmez; metinde de kanıt aranır.

    activity için True: etiket havuzu gürültülü (bkz. STOP_RATIO notu).
    channel için False: kanal etiketleri (email/sms/push) belirgin ve temiz.
    """
    low = text.lower()
    out = []
    for name, (tag_pats, txt_re) in axis.items():
        hit_tag = any(_tag_hit(t, p) for t in tags for p in tag_pats)
        hit_txt = bool(re.search(txt_re, low))
        if hit_txt or (hit_tag and not require_text):
            out.append(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/graph_ready_v3.jsonl")
    ap.add_argument("--tickets", nargs="+", default=[
        "data/normalized/from_dump.jsonl",
        "data/normalized/from_api.jsonl",
        "data/normalized/tickets_method_d.jsonl",
    ])
    ap.add_argument("--out", default="data/facets.jsonl")
    args = ap.parse_args()

    tags_by: dict[int, set[str]] = {}
    for p in args.tickets:
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            tags_by.setdefault(r["id"], {norm_tag(t) for t in r.get("tags", [])})
    stop = build_stoplist(tags_by)
    print(f"[etiket] {len(tags_by):,} bilet | benzersiz normalize etiket: "
          f"{len({t for v in tags_by.values() for t in v}):,}")
    print(f"[stoplist] ayırt edici olmayan {len(stop)} etiket elendi: {sorted(stop)}")

    ch_c, ac_c = collections.Counter(), collections.Counter()
    n_inc = both = no_ch = no_ac = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for line in open(args.inp, encoding="utf-8"):
            r = json.loads(line)
            tags = tags_by.get(r["ticket_id"], set()) - stop
            for i in r["incidents"]:
                n_inc += 1
                txt = " ".join([i.get("symptom") or "", i.get("findings") or "",
                                i.get("resolution") or ""])
                ch = _match(CHANNEL, tags, txt)
                ac = _match(ACTIVITY, tags, txt)
                for x in ch: ch_c[x] += 1
                for x in ac: ac_c[x] += 1
                if not ch: no_ch += 1
                if not ac: no_ac += 1
                if ch and ac: both += 1
                out.write(json.dumps({
                    "ticket_id": r["ticket_id"], "incident_id": i["incident_id"],
                    "channel": ch, "activity": ac,
                }, ensure_ascii=False) + "\n")

    print(f"\n[kapsam] {n_inc:,} incident")
    print(f"  channel  atanan: {n_inc-no_ch:,} (%{100*(n_inc-no_ch)/n_inc:.1f})  | boş: {no_ch:,}")
    print(f"  activity atanan: {n_inc-no_ac:,} (%{100*(n_inc-no_ac)/n_inc:.1f})  | boş: {no_ac:,}")
    print(f"  ikisi de dolu  : {both:,} (%{100*both/n_inc:.1f})")
    print(f"\n[channel]");  [print(f"  {k:<14}{v:>7,}") for k, v in ch_c.most_common()]
    print(f"\n[activity]"); [print(f"  {k:<14}{v:>7,}") for k, v in ac_c.most_common()]
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
