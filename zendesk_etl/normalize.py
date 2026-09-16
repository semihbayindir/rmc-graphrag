from __future__ import annotations

from typing import Any


# İzin verilen statüler (>= solved). Zendesk sırası: new < open < pending < hold < solved < closed
SOLVED_STATUSES = {"solved", "closed"}


def is_solved(ticket: dict[str, Any]) -> bool:
    return ticket.get("status") in SOLVED_STATUSES


def normalize_ticket(ticket: dict[str, Any], comments: list[dict[str, Any]]) -> dict[str, Any]:
    """Bilet + yorumları -> graf düğümlerine hazır tek kayıt.

    Çıktı şeması (graf besleme):
      - ticket (metadata)         -> Ticket düğümü
      - description               -> Description düğümü
      - comments[] (public+internal) -> Comment/Note düğümleri
      - custom_fields[]           -> RootCause / ProductModule düğümleri
    """
    cfs = {
        cf.get("id"): cf.get("value")
        for cf in (ticket.get("custom_fields") or [])
        if cf.get("value") not in (None, "")
    }

    return {
        # --- Ticket Metadata ---
        "id": ticket.get("id"),
        "subject": ticket.get("subject"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "group_id": ticket.get("group_id"),
        "created_at": ticket.get("created_at"),
        "updated_at": ticket.get("updated_at"),
        "tags": ticket.get("tags", []),
        # --- Description düğümü ---
        "description": ticket.get("description"),
        # --- Custom fields (kök neden, ürün modülü vb.) ---
        "custom_fields": cfs,
        # --- Yorum geçmişi (public + internal notlar dahil) ---
        "comments": [
            {
                "id": c.get("id"),
                "author_id": c.get("author_id"),
                "public": c.get("public"),  # False = teknik ekip internal notu
                "created_at": c.get("created_at"),
                "body": c.get("plain_body") or c.get("body"),
                "attachments": [
                    {"file_name": a.get("file_name"), "url": a.get("content_url")}
                    for a in (c.get("attachments") or [])
                ],
            }
            for c in comments
        ],
        "comment_count": len(comments),
        "internal_note_count": sum(1 for c in comments if c.get("public") is False),
    }
