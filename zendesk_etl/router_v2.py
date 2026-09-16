from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from . import openai_llm as llm

MODULES = ["A/B Testing", "API Erişimi", "Autopilot", "Consent / İYS", "Custom Report", "Email Deliverability", "Email Engine", "Email Template", "Event Entegrasyonu", "Gönderim Limitleri", "In-App Messaging", "Kampanya Raporları", "Kampanya Yönetimi", "Kullanıcı ve Yetki Yönetimi", "Mobil SDK Entegrasyonu", "Mobile Push", "Panel Erişimi", "REST/SOAP API", "Reklam Platformu Entegrasyonu", "SMS Gateway", "SSL Sertifikası", "Scheduled Export", "Search Recommendation", "Segmentasyon", "Target Kurguları", "Tetiklenmiş Kampanya", "Transactional Email", "Transactional Push", "Unsubscribe Raporları", "Veri Ambarı (DWH)", "Web Push", "Web Recommendation", "WhatsApp", "Zamanlanmış Kampanya", "Ürün Feed Entegrasyonu", "Üye Entegrasyonu", "Üye Silme", "Üye Yükleme", "Üye ve İzin Yönetimi", "Şifre Yönetimi"]
CHANNELS = ["email", "sms", "mobile_push", "web_push", "in_app", "web_reco", "cdp"]
ACTIVITIES = ["error", "complaint", "report", "creation", "integration", "data_ops", "transaction", "settings", "access", "scheduled", "triggered"]


class Intent(BaseModel):
    module: Optional[Literal["A/B Testing","API Erişimi","Autopilot","Consent / İYS","Custom Report","Email Deliverability","Email Engine","Email Template","Event Entegrasyonu","Gönderim Limitleri","In-App Messaging","Kampanya Raporları","Kampanya Yönetimi","Kullanıcı ve Yetki Yönetimi","Mobil SDK Entegrasyonu","Mobile Push","Panel Erişimi","REST/SOAP API","Reklam Platformu Entegrasyonu","SMS Gateway","SSL Sertifikası","Scheduled Export","Search Recommendation","Segmentasyon","Target Kurguları","Tetiklenmiş Kampanya","Transactional Email","Transactional Push","Unsubscribe Raporları","Veri Ambarı (DWH)","Web Push","Web Recommendation","WhatsApp","Zamanlanmış Kampanya","Ürün Feed Entegrasyonu","Üye Entegrasyonu","Üye Silme","Üye Yükleme","Üye ve İzin Yönetimi","Şifre Yönetimi"]] = None
    channel: Optional[Literal["email","sms","mobile_push","web_push","in_app","web_reco","cdp"]] = None
    activity: Optional[Literal["error","complaint","report","creation","integration","data_ops","transaction","settings","access","scheduled","triggered"]] = None
    keywords: List[str] = Field(default_factory=list)


class RouterOut(BaseModel):
    intents: List[Intent] = Field(default_factory=list)


SYSTEM = """Kullanıcının teknik destek sorusunu, bir bilgi grafında arama yapmak
üzere niyetlere ayır.

Her niyet için dört alan:
  module   — sorunun ilgili olduğu ürün bileşeni. Emin değilsen BOŞ bırak.
  channel  — email/sms/mobile_push/web_push/in_app/web_reco/cdp. Geçmiyorsa BOŞ.
  activity — yapılan/yaşanan işin türü. Emin değilsen BOŞ.
  keywords — aramada kullanılacak ayırt edici terimler.

KEYWORDS KURALLARI (en önemli alan burası):
  - Hata kodu, metot adı, parametre adı, tablo adı geçiyorsa AYNEN al
    (Invalid IP!, PostTransactionalPush, EMAIL_PERMIT, dbo.CAMPAIGNS).
  - Kaynak veriler TÜRKÇE; İngilizceye çevirme. 'unsubscribe report' değil
    'abonelikten çıkma', 'unsub raporu'.
  - 'nasıl', 'hangi', 'neden' gibi genel kelimeleri KOYMA.

MULTI-INTENT: Soru birbirinden bağımsız iki şey soruyorsa her biri için ayrı
niyet üret. İlgili adımları tek niyette topla.

BOŞ BIRAKMAK GÜVENLİDİR: module/channel/activity artık katı filtre değil,
sıralama ağırlığıdır. Emin olmadığın ekseni boş bırak; uydurma."""


class Router:
    def __init__(self) -> None:
        self.model = llm.chat_model()
        self.last_usage: dict | None = None

    def route(self, question: str) -> RouterOut:
        self.last_usage = None
        try:
            out, resp = llm.parse(RouterOut, SYSTEM, question, model=self.model, temperature=0.0)
            self.last_usage = llm.usage(resp)
            if out.intents:
                return out
        except Exception:
            pass
        # Router çökerse soruyu tek keyword-niyetine düşür; akış durmasın.
        return RouterOut(intents=[Intent(keywords=[question])])
