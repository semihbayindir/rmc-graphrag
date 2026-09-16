from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from .client import ZendeskClient
from .config import settings


def resolve_group_ids(client: ZendeskClient, group_names: tuple[str, ...]) -> dict[int, str]:
    """Grup isimlerini -> {id: name} sözlüğüne çevirir (lokal filtreleme için)."""
    wanted = {n.lower() for n in group_names}
    found: dict[int, str] = {}
    for g in client.paginate_cursor("groups.json", data_key="groups"):
        if g.get("name", "").lower() in wanted:
            found[g["id"]] = g["name"]
    missing = wanted - {name.lower() for name in found.values()}
    if missing:
        print(f"  [uyarı] Bulunamayan gruplar: {', '.join(sorted(missing))}")
    return found


class AgentResolutionError(RuntimeError):
    """E-posta -> user_id çözümlemesi güvenli biçimde yapılamadı."""


def resolve_agents(client: ZendeskClient, teams_path: str = "data/teams.yaml") -> list[dict[str, Any]]:
    """teams.yaml'daki e-postaları Zendesk user_id'lerine çevirir.

    /users/search.json aynı kişi için birden çok hesap döndürebilir; bu yüzden
    role in {agent, admin} filtresi uygulanır. İstisnalar teams.yaml'da allow_end_user ile işaretlenir.
    """
    import yaml

    cfg = yaml.safe_load(open(teams_path, encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for team, tinfo in cfg["teams"].items():
        for entry in tinfo["agents"]:
            email = entry["email"]
            users = client.get("users/search.json", params={"query": email}).get("users", [])
            if not users:
                raise AgentResolutionError(f"{email}: Zendesk'te bulunamadı")
            staff = [u for u in users if u.get("role") in ("agent", "admin")]
            if not staff:
                if not entry.get("allow_end_user"):
                    raise AgentResolutionError(
                        f"{email}: yalnızca end-user hesabı var (rol={users[0].get('role')}). "
                        "Gerçekten bu hesap isteniyorsa teams.yaml'da allow_end_user: true ekleyin."
                    )
                staff = [users[0]]
            elif len(staff) > 1:
                raise AgentResolutionError(
                    f"{email}: birden çok personel hesabı eşleşti "
                    f"({[u['id'] for u in staff]}); teams.yaml'da netleştirin."
                )
            u = staff[0]
            out.append({
                "email": email,
                "user_id": u["id"],
                "role": u.get("role"),
                "team": team,
                "team_label": tinfo.get("label", team),
            })
    return out


def agent_team_map(agents: list[dict[str, Any]]) -> dict[int, str]:
    """user_id -> ekip. Yorum yazarından SOURCED_FROM atfı için."""
    return {a["user_id"]: a["team"] for a in agents}


def get_group_agent_ids(client: ZendeskClient, group_id: int) -> list[int]:
    """Bir gruptaki ajanların user_id listesi (yorum-yazarı filtresi için)."""
    ids: list[int] = []
    for m in client.paginate_cursor(
        f"groups/{group_id}/memberships.json",
        params={"page[size]": 100},
        data_key="group_memberships",
    ):
        if m.get("user_id"):
            ids.append(m["user_id"])
    return ids


def commenter_search_query(user_id: int, months_back: int, solved_only: bool = True) -> str:
    """Belirli bir kullanıcının yorum yazdığı biletler için Search sorgusu.

    `updated>=` kullanır (created değil): SAT'ın son N ayda dokunduğu,
    başka grupta açılmış/kapanmış eski biletleri de yakalar.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
    q = f"type:ticket commenter:{user_id} updated>={since}"
    if solved_only:
        q += " status>=solved"
    return q


def fetch_comments(client: ZendeskClient, ticket_id: int) -> list[dict[str, Any]]:
    """Bir biletin tüm yorumları — public VE internal (public:false) dahil."""
    return list(
        client.paginate_cursor(
            f"tickets/{ticket_id}/comments.json",
            params={"page[size]": 100},
            data_key="comments",
        )
    )


def start_time_epoch(months_back: int) -> int:
    """months_back ay öncesinin Unix epoch değeri (incremental start_time)."""
    dt = datetime.now(timezone.utc) - timedelta(days=months_back * 30)
    return int(dt.timestamp())


def solved_search_query(group_names: tuple[str, ...], months_back: int) -> str:
    """Yöntem A için Search Export sorgusu."""
    since = (datetime.now(timezone.utc) - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
    groups = " ".join(f'group:"{g}"' for g in group_names)
    return f"type:ticket status>=solved created>={since} {groups}"


def load_written_ids(path: str, id_key: str = "id") -> set[int]:
    """Daha önce yazılmış kayıtların ID'lerini topla (resume için)."""
    ids: set[int] = set()
    if not os.path.exists(path):
        return ids
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line)[id_key])
                except (ValueError, KeyError):
                    continue
    return ids


class JsonlWriter:
    """Streaming JSONL yazıcı. append=True ile kesintiden sonra devam eder."""

    def __init__(self, path: str, append: bool = False) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._fh = open(path, "a" if append else "w", encoding="utf-8")
        self.count = 0

    def write(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()  # kesintide resume için: her satır anında diske
        self.count += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
