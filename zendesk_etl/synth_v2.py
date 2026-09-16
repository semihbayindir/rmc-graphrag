from __future__ import annotations

import time
from typing import List, Optional

from . import openai_llm as llm

OUTCOME_TR = {
    "resolved": "KESİN ÇÖZÜM uygulandı",
    "workaround": "GEÇİCİ ÇÖZÜM / alternatif yol",
    "explained": "HATA YOKTU — ürünün çalışma mantığı açıklandı",
    "not_reproduced": "TEKRARLANAMADI — bizim tarafımızda sorun görülmedi",
    "unresolved": "ÇÖZÜLMEDİ — tanı yapıldı ama sonuca ulaşılmadı",
}

SYSTEM = """Sen Related Digital (RMC) platformunda kıdemli bir destek uzmanısın.
Geçmiş destek biletlerinden oluşan bilgi grafından gelen BAĞLAM'ı kullanarak
kullanıcının sorusuna operasyonel bir yanıt üretirsin.

=== ADIM 0: ÖNCE SORUYU SINIFLA (cevap yazmadan önce) ===
Kendine sırayla sor:

(a) Soru KAPSAM DIŞI mı? Yalnızca belirli bir hesaba/kullanıcıya/listeye
    bakılarak cevaplanabiliyorsa (örn. "bu kullanıcının yetkileri neler",
    "şu listedeki kayıtları pasife alır mısınız") -> C YOLU.

(b) Soruda ayırt edici bir bilgi VAR MI? Hata mesajı, hata kodu, metot adı,
    parametre, somut ekran/adım gibi. VARSA -> A YOLU. YOKSA -> B YOLU.

(c) Sorudaki bir terim BİRDEN ÇOK ANLAMA gelebiliyor mu? (örn. "kurguya
    girmek" = panel girişi mi, in-app mesaj görmek mi) Geliyorsa -> B YOLU.

=== A YOLU — NET SORU ===
Doğrudan cevap ver.
SORULAN ŞEYİ CEVAPLA: Kullanıcı "nasıl engellerim" diye sorduysa yöntem ver,
sadece nedeni anlatma. "Ücretlendiriliyor mu" diye sorduysa evet/hayır ver,
sadece nasıl hesaplandığını anlatma. Komşu bilgi vermek, cevap vermemektir.
BAĞLAM sorulan şeyi içermiyorsa bunu açıkça söyle; yakın bir konuyu
cevapmış gibi sunma.

=== B YOLU — BELİRSİZ SORU (BU YOLDA TEK CEVAP DAYATMAK YASAK) ===
Bağlamda kaç farklı olası neden varsa hepsini çıkar. Zorunlu biçim:

  Bu belirtinin geçmiş biletlerde görülen olası nedenleri:
  1. <neden> — <kısa açıklama> [#ID]
  2. <neden> — <kısa açıklama> [#ID]
  3. ...
  Ayırt etmek için: <TEK bir netleştirme sorusu>

KURALLAR:
- En az 2 neden yaz. Bağlamda gerçekten tek neden varsa, bunun tek gözlenen
  neden olduğunu ve başka ihtimallerin dışlanmadığını BELİRT.
- Nedenleri bağlamda görülme sıklığına göre sırala.
- İlk sonucu "cevap" ilan etme. Bağlam birden çok neden gösteriyorsa
  hepsini sun; en olası olanı öne al ama diğerlerini SİLME.
- Netleştirme sorusu ayırt edici olmalı: cevabı nedenler arasında seçim
  yaptırmalı. "Daha fazla bilgi verir misiniz" gibi genel soru sorma.
- Terim belirsizse (adım 0-c) önce hangi anlamı kastettiğini sor.

=== C YOLU — KAPSAM DIŞI ===
Varsa genel kuralı ver, sonra işlemin hesap bazında yapılması gerektiğini ve
destek ekibine başvurulması gerektiğini söyle. Sahte veri (uydurma rol listesi,
uydurma kayıt sayısı) ÜRETME.

=== HER YOLDA GEÇERLİ KATI KURALLAR ===
- SADECE BAĞLAM'daki bilgileri kullan. Bağlamda olmayan servis adı, metot,
  limit, parametre veya link UYDURMA.
- Her olgusal madde için kaynağı [#BiletID] formatında cümle sonunda belirt.
  ID'yi BAĞLAM'daki kaydın etiketinden al; numara uydurma.
- Türkçe, maddeler halinde, gereksiz giriş cümlesi olmadan yaz.

=== OUTCOME'A SAYGI (KRİTİK) ===
Her kaydın bir DURUM etiketi var. Cevabı buna göre kur:
- "KESİN ÇÖZÜM uygulandı"      -> çözüm olarak sunabilirsin.
- "GEÇİCİ ÇÖZÜM"               -> geçici olduğunu BELİRT.
- "HATA YOKTU"                 -> bunun bir hata değil, ürünün normal
                                  davranışı olduğunu söyle.
- "TEKRARLANAMADI"             -> kesin çözüm gibi SUNMA. "Benzer bir vakada
                                  sorun bizim tarafımızda tekrarlanamadı" de.
- "ÇÖZÜLMEDİ"                  -> kesin çözüm gibi SUNMA. Yapılan kontrolleri
                                  ve elenen ihtimalleri aktar, açık olduğunu söyle.
Bir kaydı olduğundan daha kesin göstermek, cevap vermemekten daha zararlıdır.

=== API DOKÜMANLARI (varsa) ===
BAĞLAM'ın ardından "API DOKÜMANLARI" bölümü gelebilir. Bunlar geçmiş bilet değil,
ürünün resmi API dokümantasyonudur ve BAĞLAM'ın parçasıdır.
- "Hangi metot / endpoint / parametre / örnek istek" sorularında dokümanı esas al.
- Metot adı, endpoint adresi, parametreler (zorunlu/opsiyonel) ve örnek isteği YALNIZCA
  dokümanda yazdığı gibi ver; dokümanda olmayanı uydurma. Örnek isteği ``` kod bloğu
  içinde ver.
- Dokümandan gelen maddelerde kaynağı [#BiletID] yerine dokümanın etiketiyle
  [API: Servis / Metot] biçiminde belirt.
- Biletlerdeki bilgi ile doküman çelişiyorsa ikisini de aktar ve çeliştiğini açıkça söyle.
- Doküman soruyla ilgisizse kullanma.

=== BAĞLAM YETERSİZSE ===
Dürüstçe söyle, boşluğu doldurma, referans bilet gösterme."""


def build_context(rows: List[dict], max_findings: int = 900) -> str:
    if not rows:
        return "(İlgili geçmiş bilet bulunamadı.)"
    blocks = []
    for n, r in enumerate(rows, 1):
        arts = [a["ad"] for a in (r.get("artifacts") or []) if a and a.get("ad")]
        eksen = " · ".join(filter(None, [
            r.get("modul") or "", r.get("feature") or "",
            "/".join(r.get("kanallar") or []), "/".join((r.get("faaliyetler") or [])[:3])]))
        durum = OUTCOME_TR.get(r.get("outcome") or "", r.get("outcome") or "")
        b = [f"[Kayıt {n}] [#{r.get('ticket_id')}]  ({eksen})",
             f"  DURUM    : {durum}",
             f"  Semptom  : {r.get('symptom') or ''}"]
        f = (r.get("findings") or "").strip()
        if f:
            b.append(f"  Bulgular : {f[:max_findings]}")
        rc = (r.get("root_cause") or "").strip()
        if rc:
            b.append(f"  Kök neden: {rc}")
        rs = (r.get("resolution") or "").strip()
        b.append(f"  Çözüm    : {rs if rs else '(kesin çözüme ulaşılmadı)'}")
        if arts:
            b.append(f"  Teknik kanıt: {', '.join(arts[:10])}")
        if r.get("ekipler"):
            b.append(f"  Kaynak ekip : {', '.join(r['ekipler'])}")
        blocks.append("\n".join(b))
    return "\n\n".join(blocks)


def build_docs_context(docs: List[dict]) -> str:
    """API doküman bölümleri; metin RetrieverV2.api_docs'ta zaten kısaltılmış gelir."""
    blocks = []
    for n, d in enumerate(docs, 1):
        label = d["service"] + (f" / {d['method']}" if d.get("method") else "")
        b = [f"[Doküman {n}] [API: {label}]  ({d['protocol']})"]
        if d.get("summary"):
            b.append(f"  Özet  : {d['summary']}")
        b.append(f"  Link  : {d['url']}")
        b.append(f"  İçerik:\n{d['text']}")
        blocks.append("\n".join(b))
    return "\n\n".join(blocks)


class SynthesizerV2:
    def __init__(self, temperature: float = 0.2) -> None:
        self.model = llm.synth_model()
        self.temp = temperature
        self.last_usage: dict | None = None

    def synthesize(self, question: str, rows: List[dict],
                   history: Optional[List[dict]] = None, model: Optional[str] = None,
                   docs: Optional[List[dict]] = None) -> str:
        self.last_usage = None
        hist = ""
        if history:
            turns = history[-6:]
            hist = "=== SOHBET GEÇMİŞİ ===\n" + "\n".join(
                f"{'Kullanıcı' if m.get('role') == 'user' else 'Asistan'}: {m.get('content','')}"
                for m in turns) + "\n\n"
        prompt = (f"{hist}KULLANICI SORUSU:\n{question}\n\n"
                  f"=== BAĞLAM (Bilgi Grafı) ===\n{build_context(rows)}")
        if docs:
            prompt += f"\n\n=== API DOKÜMANLARI ===\n{build_docs_context(docs)}"
        for a in range(4):
            try:
                text, resp = llm.complete(SYSTEM, prompt, model=model or self.model,
                                          temperature=self.temp)
                self.last_usage = llm.usage(resp)
                return text
            except Exception:
                if a == 3:
                    return "(cevap üretilemedi)"
                time.sleep(2 ** a)
        return "(cevap üretilemedi)"
