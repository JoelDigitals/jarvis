"""Benachrichtigungen: speichern, live an Browser-Tabs pushen, am PC (Desktop-Agent) und per Discord-DM zeigen."""
from __future__ import annotations

from .hub import hub
from .models import Notification


def notify(user_id: int, title: str, body: str = "", kind: str = "info", data: dict | None = None,
           speak: str | None = None, to_agent: bool = True, to_discord: bool = True) -> Notification:
    n = Notification.objects.create(user_id=user_id, title=title, body=body, kind=kind, data=data or {})
    payload = n.as_dict()
    payload["type"] = "notification"
    if speak:
        payload["speak"] = speak
    hub.send_to_user(user_id, payload)
    if to_agent:
        hub.agent_notify(user_id, title, body)
    if to_discord:
        from .discord_bridge import manager
        manager.send_dm(user_id, f"**{title}**\n{body}".strip())
    return n
