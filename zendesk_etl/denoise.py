from __future__ import annotations

import re
from typing import Any

# Bir yorumun içinde bu kalıptan SONRASINI (imza/uyarı bloğu) kes.
_CUT_MARKERS = [
    r"bu (e-?posta|elektronik posta|ileti).{0,60}gizli",          # KVKK gizlilik uyarısı
    r"this (e-?mail|message).{0,60}confidential",
    r"yasal uyar[ıi]",
    r"kvkk",
    r"l[üu]tfen bu (e-?postay[ıi]|iletiyi) yazd[ıi]rmadan",       # karbon salınımı
    r"please consider the environment",
    r"6698 say[ıi]l[ıi]",
    r"-{2,}\s*forwarded message",
    r"__+",                                                        # imza ayıracı ____
]
_CUT_RE = re.compile("|".join(_CUT_MARKERS), re.IGNORECASE)

# Tamamen atılacak selamlama / kapanış satırları.
_NOISE_LINE = re.compile(
    r"^\s*(merhaba|selamlar|sevgiler|iyi (çalışmalar|günler|akşamlar)|sayg[ıi]lar[ıi]mla|"
    r"teşekk[üu]rler|kolay gel[st]in|hi|hello|thanks|regards|best)\b.*$",
    re.IGNORECASE,
)
_QUOTE_LINE = re.compile(r"^\s*>.*$")          # alıntı zinciri
_URL = re.compile(r"https?://\S+")


def _clean_body(text: str) -> str:
    if not text:
        return ""
    # İmza/uyarı bloğundan öncesini al
    m = _CUT_RE.search(text)
    if m:
        text = text[: m.start()]
    lines: list[str] = []
    for line in text.splitlines():
        if _QUOTE_LINE.match(line) or _NOISE_LINE.match(line):
            continue
        line = line.strip()
        if line:
            lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def build_ticket_text(ticket: dict[str, Any], max_chars: int = 24000) -> str:
    """description + yorumları kronolojik, temizlenmiş tek metne indirger.

    Internal notlar [İÇ NOT] etiketiyle vurgulanır (kök neden burada saklı).
    """
    parts: list[str] = []
    subject = (ticket.get("subject") or "").strip()
    if subject:
        parts.append(f"KONU: {subject}")

    desc = _clean_body(ticket.get("description") or "")
    if desc:
        parts.append(f"[AÇIKLAMA - İlk Sorun]\n{desc}")

    for c in ticket.get("comments", []):
        body = _clean_body(c.get("body") or "")
        if not body:
            continue
        tag = "İÇ NOT (teknik ekip)" if c.get("public") is False else "YORUM"
        parts.append(f"[{tag} | {c.get('created_at','')}]\n{body}")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        # Baş (sorun) ve son (çözüm) genelde en değerli; ortadan kırp.
        head = text[: max_chars // 2]
        tail = text[-max_chars // 2 :]
        text = head + "\n\n[...uzun metin kırpıldı...]\n\n" + tail
    return text
