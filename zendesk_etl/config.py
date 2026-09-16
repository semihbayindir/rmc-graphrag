from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv() -> None:
    """Basit .env yükleyici (harici bağımlılık gerektirmez)."""
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # https://{subdomain}.zendesk.com
    subdomain: str = os.environ.get("ZENDESK_SUBDOMAIN", "")

    # OAuth 2.0 client_credentials (Admin Center > Apps and integrations > OAuth Clients).
    # Not: Zendesk bu akışta refresh_token VERMEZ ve token ~30 dk sonra düşer;
    # yenileme akışı client.py içindeki OAuthToken tarafından yönetilir.
    oauth_client_id: str = os.environ.get("ZENDESK_OAUTH_CLIENT_ID", "")
    oauth_client_secret: str = os.environ.get("ZENDESK_OAUTH_CLIENT_SECRET", "")
    # UYARI: client_credentials granüler scope listesini ("tickets:read users:read")
    # sessizce reddedip SIFIR yetkili token verir. Çalışan tek değer: "read".
    oauth_scope: str = os.environ.get("ZENDESK_OAUTH_SCOPE", "read")

    # Filtrelenecek teknik ekip grupları (virgülle ayır)
    tech_groups: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            g.strip()
            for g in os.environ.get("ZENDESK_TECH_GROUPS", "Teknik Destek,Ar-Ge").split(",")
            if g.strip()
        )
    )

    # Gruptan ayrılmış ama biletlerini istediğimiz eski ajanların user_id'leri
    # (güncel grup üyeliğinde görünmedikleri için elle ekleniyor)
    extra_agent_ids: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            int(x.strip())
            for x in os.environ.get("ZENDESK_EXTRA_AGENT_IDS", "").split(",")
            if x.strip().isdigit()
        )
    )

    # Kaç aylık geçmiş çekilecek (varsayılan 18 ay = 1.5 yıl)
    months_back: int = int(os.environ.get("ZENDESK_MONTHS_BACK", "18"))

    # Zendesk dakikadaki istek sınırı
    max_requests_per_minute: int = int(os.environ.get("ZENDESK_RPM", "60"))

    # ETL scriptleri için ortak OpenAI istek/dk sınırı
    openai_rpm: int = int(os.environ.get("OPENAI_RPM", "500"))

    out_raw_dir: str = os.environ.get("ZENDESK_RAW_DIR", "data/raw")
    out_norm_dir: str = os.environ.get("ZENDESK_NORM_DIR", "data/normalized")

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    @property
    def oauth_token_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/oauth/tokens"

    def validate(self) -> None:
        missing = [
            name
            for name, val in (
                ("ZENDESK_SUBDOMAIN", self.subdomain),
                ("ZENDESK_OAUTH_CLIENT_ID", self.oauth_client_id),
                ("ZENDESK_OAUTH_CLIENT_SECRET", self.oauth_client_secret),
            )
            if not val
        ]
        if missing:
            raise SystemExit(
                "Eksik ortam değişkenleri: " + ", ".join(missing) + "\n"
                ".env dosyasını .env.example'a göre doldurun."
            )


settings = Settings()
