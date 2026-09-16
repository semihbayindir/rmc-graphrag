from __future__ import annotations

import re
from typing import Optional

GREETINGS = (
    "selamünaleyküm", "selamün aleyküm", "merhabalar", "merhaba", "selamlar", "selam",
    "slm", "mrb", "mrhb", "sa", "günaydın", "iyi günler", "iyi akşamlar", "iyi çalışmalar",
    "kolay gelsin", "nasılsınız", "nasılsın", "naber", "hey", "hi", "hello",
)
THANKS = (
    "çok teşekkür ederim", "teşekkür ederim", "çok teşekkürler", "teşekkürler", "teşekkür",
    "tşkler", "tşk", "sağ olun", "sağolun", "sağ ol", "sağol", "eyvallah", "eline sağlık",
    "elinize sağlık", "thanks", "thank you", "tamamdır", "tamam", "anladım", "ok", "okey",
    "görüşürüz", "hoşça kal", "hoşçakal", "iyi geceler", "bye",
)
# Tek başına sohbet sayılmaz; yalnızca yukarıdakilerle birlikte gelirse yok sayılır.
FILLERS = ("hocam", "arkadaşlar", "ekip", "herkese", "size", "sizlere", "de", "da", "çok",
           "bot", "asistan")
MAX_WORDS = 8

GREETING_REPLY = (
    "Merhaba! Ben RMC destek asistanıyım; geçmiş destek biletlerinden yararlanarak "
    "teknik sorularınızı yanıtlıyorum. Yaşadığınız sorunu ya da aldığınız hata mesajını "
    "yazabilirsiniz."
)
THANKS_REPLY = "Rica ederim! Başka bir sorunuz olursa yazabilirsiniz."

# Türkçe karakterleri ASCII'ye katla: "gunaydin", "tesekkurler", "sagol" de eşleşsin.
_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)


def _pattern(phrases: tuple[str, ...]) -> re.Pattern:
    alts = sorted({_fold(p) for p in phrases}, key=len, reverse=True)
    body = "|".join(re.escape(a).replace("\\ ", " ").replace(" ", r"\s+") for a in alts)
    return re.compile(rf"\b(?:{body})\b")


_GREET, _THANK, _FILL = _pattern(GREETINGS), _pattern(THANKS), _pattern(FILLERS)


def reply(message: str) -> Optional[str]:
    """Mesaj yalnızca selamlama/teşekkürse sabit cevabı, değilse None döner."""
    text = re.sub(r"[^\w\s]|_", " ", _fold(message))  # noktalama ve emoji
    if not text.strip() or len(text.split()) > MAX_WORDS:
        return None
    thanks, greet = bool(_THANK.search(text)), bool(_GREET.search(text))
    if not (thanks or greet):
        return None
    if _FILL.sub(" ", _THANK.sub(" ", _GREET.sub(" ", text))).strip():
        return None
    return THANKS_REPLY if thanks else GREETING_REPLY
