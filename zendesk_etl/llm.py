from __future__ import annotations

import os
import threading
import time
from typing import List, Literal

from openai import BadRequestError
from pydantic import BaseModel

from . import openai_llm as llm


class QuotaError(Exception):
    """Model çıktısı doğrulanamadı veya kalıcı hata (karantinaya alınır)."""


class RateLimiter:
    """Thread-safe token-bucket: birden çok işçi arasında toplam RPM'i sınırlar."""

    def __init__(self, rpm: int) -> None:
        self.min_interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.min_interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


# --- Etiket kümeleme ---
class SubComponentCluster(BaseModel):
    sub_component: str
    tags: List[str]


class ModuleCluster(BaseModel):
    module: str
    sub_components: List[SubComponentCluster]


class TagCatalog(BaseModel):
    catalog: List[ModuleCluster]


TAG_CLUSTER_PROMPT = """Sen kıdemli bir teknik ürün analistisin. Aşağıda bir Zendesk destek \
sisteminden çıkarılmış ham, karmaşık ve tutarsız operasyonel etiketler (tags) listesi var.

Bu karmaşık operasyonel etiketleri analiz et ve mantıksal Modül -> Alt-Bileşen (Sub-Component) \
ilişkilerine göre kümeleyerek JSON bir katalog oluştur. Bu katalog özellikle API, entegrasyon, \
sistem ve arka plan süreçlerini kapsamalıdır (arayüz menüsünün kaçırdığı teknik alanlar).

Kurallar:
- Anlamsız veya salt kimlik/isim gibi etiketleri (örn. kişi adları, sayısal id'ler) katalog dışında bırak.
- Baştaki/sondaki alt çizgileri normalleştir ama orijinal etiketi tags listesinde koru.
- Modül isimlerini insan-okur biçimde ver (örn. 'REST/SOAP API', 'Push & SMS Gateway', \
'Email Engine', 'Access / Infrastructure', 'Data Warehouse').

HAM ETİKETLER:
{tags}
"""


def cluster_tags(tags: list[str]) -> dict:
    out, _ = llm.parse(TagCatalog, "", TAG_CLUSTER_PROMPT.format(tags="\n".join(sorted(tags))),
                       temperature=0.2)
    return out.model_dump()


# --- Bilet çıkarım şeması ---
class AffectedComponentV3(BaseModel):
    module: str
    sub_component: str


class IncidentV3(BaseModel):
    incident_id: int
    symptom: str
    findings: str
    root_cause: str
    resolution: str
    outcome: Literal[
        "resolved", "workaround", "explained", "not_reproduced", "unresolved", "none"
    ]
    affected_component: AffectedComponentV3
    technical_artifacts: List[str]


class TicketExtractionV3(BaseModel):
    ticket_id: int
    incidents: List[IncidentV3]


SYSTEM_PROMPT_V3 = """Sen bir kurumsal destek bilgi analistisin. Bu graf yalnızca teknik ekibi değil, TÜM operasyonel ekipleri kapsar; dolayısıyla teknik olmayan ama yeniden kullanılabilir operasyonel bilgi de değerlidir.

=== GÖREV & ÇIKTI ===
Bileti analiz et ve çıktıyı aşağıdaki şemada ver:

{{
  "ticket_id": <bilet ID>,
  "incidents": [                      // bilette KAÇ bağımsız konu varsa o kadar öğe
    {{
      "incident_id":   <1'den başlayan sıra>,
      "symptom":       "Sorunun veya talebin ne olduğu",
      "findings":      "Tanı sürecinde ortaya çıkan olgular, elenen ihtimaller, kısıtlar, kurallar, loglar, davranışlar",
      "root_cause":    "Kök neden. Belirlenemediyse boş string",
      "resolution":    "Varsa kesin çözüm. Yoksa boş string",
      "outcome":       "resolved | workaround | explained | not_reproduced | unresolved | none",
      "affected_component": {{ "module": "...", "sub_component": "..." }},
      "technical_artifacts": ["..."]
    }}
  ]
}}

MULTI-INTENT: Bir bilette birbirinden bağımsız birden fazla konu konuşulmuş olabilir. Her bağımsız konu AYRI bir incident'tir. Birbiriyle ilgili adımları tek incident'te topla, ilgisiz konuları BİRLEŞTİRME.

GÜRÜLTÜ: E-posta imzaları, KVKK uyarıları, karbon salınımı metinleri ve 'Merhaba' gibi selamlamaları TAMAMEN YOK SAY.

=== BİLGİ YAKALAMA KURALLARI ===
1) symptom: Sorunun veya talebin ne olduğu.
2) findings: TANI SÜRECİNDE ORTAYA ÇIKAN OLGULAR.
   - Bilet kesin bir çözümle bitmese BİLE burası doldurulur.
   - Yaz: Denenen şeyler ve sonuçları, elenen ihtimaller, yapılan kontroller, ortaya çıkan kısıt/kurallar, gözlemlenen davranış, ürünün çalışma mantığı.
   - Ölçüt: "Aynı sorunla karşılaşan bir sonraki kişinin işine yarar mı?"
3) resolution: VARSA kesin çözüm. Yoksa boş string.
   - findings dolu, resolution boş olabilir; bu normaldir ve istenir.

=== OLGUSAL YAZIM KURALI (findings VE resolution için) ===
'Müşteriye bilgi verilmiştir', 'Sorun giderilmiştir' gibi PROSEDÜREL cümleler KULLANMA. "Ne söylendiği" değil, "hangi bilginin aktarıldığı" önemlidir.
KÖTÜ : "Gönderim limitleri hakkında müşteriye bilgi verildi."
İYİ  : "Toplu e-posta gönderimi için önce createemailcamp ile kampanya taslağı oluşturmak zorunludur; kampanyasız doğrudan gönderim yapılamaz. API üzerinden duraklatma desteklenmez, yalnızca panelden yapılır."

=== OUTCOME DEĞERLERİ (Zorunlu) ===
- resolved       : kesin çözüm uygulandı
- workaround     : geçici çözüm veya alternatif yol bulundu
- explained      : hata yoktu; ürünün nasıl çalıştığı olgusal olarak açıklandı
- not_reproduced : sorun bizim tarafımızda tekrarlanamadı
- unresolved     : tanı yapıldı, olgular ortaya çıktı ama çözüme ulaşılmadı
- none           : yeniden kullanılabilir HİÇBİR bilgi yok (findings ve resolution boş string bırakılır)

=== KRİTİK AYIRIM: "İŞ YAPILDI" vs "BİLGİ ÜRETİLDİ" ===
Bir bilette somut bir sonuç olması TEK BAŞINA bilgi anlamına gelmez.
İş talepleri, efor onayları, atama/planlama, salt teslim ("canlıya alındı", "test sekmesinde") ve salt durum bildirimleri ("onay verildi", "hesap bulunamadı") için: outcome='none'.

Test: "Aynı durumla karşılaşan bir sonraki kişi bu metinden ÖĞRENECEĞİ bir şey var mı — bir kural, kısıt, davranış, neden veya yöntem?" Hayır ise outcome='none'.

GÖMÜLÜ BULGU: Bilet ağırlıklı olarak teslim/iş anlatısı olsa BİLE, içinde bir kural, kısıt, neden veya yöntem geçiyorsa outcome='none' SEÇME; yalnızca o bulguyu findings'e al, teslim anlatısını ALMA.
Örnek: "Çalışma test sekmesinde hazırlandı; test listesi adı görünmediği için data listesi yeniden yüklendi ve testler başarılı oldu; kampanya 16.07 10:00'a zamanlandı."
  -> findings: "Test listesi adı görünmüyorsa data listesinin yeniden yüklenmesi gerekir."
  -> hazırlama/zamanlama anlatısı yazılmaz.

DİKKAT (İstisna): Biletin HERHANGİ BİR YERİNDE teknik veri (hata raporu, log, kural/puan dökümü, konfigürasyon, hata kodu, kara liste kaydı, API yanıtı) varsa, çevresindeki yazışma ne kadar zayıf olursa olsun outcome='none' SEÇİLEMEZ; bu veri findings alanına olgusal biçimde aktarılır.
Örnek: gövdesinde spam kural puanları ve kara liste kaydı bulunan bir bilet, iç notları sadece "hesap bulunamadı" olsa bile 'none' değildir.

=== affected_component ===
module ve sub_component değerlerini [UI_MENU_TREE] veya [CLUSTERED_TAG_CATALOG] içinden seç. REST/SOAP servisleriyle ilgiliyse module='REST/SOAP API' ve sub_component olarak [API_REFERENCE] içindeki servis adını kullan.

=== technical_artifacts ===
İç notlardaki hata kodları, IP'ler, SQL sorguları, SP isimleri, veritabanı kolon/parametre adları (KEY_ID, COLUMN30 gibi), sistem parametreleri, Jira kayıtları ve döküman URL'lerini yakala.
ASLA ALMA: kişiye özel e-posta adresleri, 32 karakterlik hash/token/GUID/hesap anahtarları, kişi ve şirket isimleri. Sadece evrensel, yeniden kullanılabilir teknik terimleri al.

=== ÇIKTI DİLİ ===
symptom, findings, root_cause ve resolution MUTLAKA TÜRKÇE. technical_artifacts orijinal haliyle bırakılır, çevrilmez.

=== [UI_MENU_TREE] ===
{ui_menu_tree}

=== [CLUSTERED_TAG_CATALOG] ===
{tag_catalog}

=== [API_REFERENCE] ===
{api_reference}
"""


class Extractor:
    """Multi-intent çıkarım (strict JSON şema). Model: OPENAI_ETL_MODEL, boşsa OPENAI_MODEL."""

    def __init__(
        self,
        ui_menu_tree_json: str,
        tag_catalog_json: str,
        api_reference_json: str = "{}",
        rpm: int | None = None,
        max_retries: int = 6,
    ) -> None:
        from .config import settings as _s

        self.model = os.environ.get("OPENAI_ETL_MODEL") or llm.chat_model()
        self.effort = os.environ.get("OPENAI_ETL_REASONING_EFFORT") or "low"
        # System prompt sabit kalmalı; OpenAI ortak prefix'i önbelleğe alır.
        self.system = SYSTEM_PROMPT_V3.format(
            ui_menu_tree=ui_menu_tree_json,
            tag_catalog=tag_catalog_json,
            api_reference=api_reference_json,
        )
        self.limiter = RateLimiter(rpm if rpm is not None else _s.openai_rpm)
        self.max_retries = max_retries
        self.stats = {"calls": 0, "prompt_tokens": 0, "cache_hit_tokens": 0, "completion_tokens": 0}
        self._stats_lock = threading.Lock()

    def extract(self, ticket_id: int, ticket_text: str, ticket_tags: list[str]) -> dict:
        tags_hint = ", ".join(ticket_tags) if ticket_tags else "(etiket yok)"
        user = (f"ANALİZ EDİLECEK BİLET (ticket_id={ticket_id}):\n"
                f"BU BİLETİN ETİKETLERİ: {tags_hint}\n\n{ticket_text}")
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self.limiter.wait()
            try:
                out, resp = llm.parse(TicketExtractionV3, self.system, user, model=self.model,
                                      temperature=0.1, effort=self.effort, max_tokens=16000)
            except BadRequestError as exc:
                # 400 kalıcıdır (ör. bağlam sınırı aşıldı); tekrar denemek boşa istek.
                raise QuotaError(f"OpenAI isteği reddetti: {exc}") from exc
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise QuotaError(f"OpenAI çağrısı başarısız: {exc}") from exc

            with self._stats_lock:
                self.stats["calls"] += 1
                self.stats["prompt_tokens"] += resp.usage.prompt_tokens
                self.stats["cache_hit_tokens"] += llm.cached_tokens(resp)
                self.stats["completion_tokens"] += resp.usage.completion_tokens
            out.ticket_id = ticket_id  # modeli sabitle
            return out.model_dump()
        raise QuotaError(f"Tüm denemeler tükendi: {last}")

    def cache_ratio(self) -> float:
        p = self.stats["prompt_tokens"]
        return self.stats["cache_hit_tokens"] / p if p else 0.0
