"""Benutzer-Datenverzeichnisse: jeder Benutzer hat eigene Einstellungen, Keys und eigenes Gedächtnis."""
from __future__ import annotations

import json
from contextlib import contextmanager

from jarvis_core.paths import use_data_root

from .models import Profile


def profile_of(user) -> Profile:
    return Profile.objects.select_related("user").get_or_create(user=user)[0]


def ensure_user_data(profile: Profile) -> None:
    """Legt das Verzeichnis an und trägt ggf. die mitgenutzten Server-Keys ein (im aktiven Scope)."""
    from .config_store import load_settings, save_settings, sync_shared_keys

    root = profile.data_root
    for sub in ("config", "memory", "content"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if profile.uses_main_data:
        return
    settings_file = root / "config" / "settings.json"
    if not settings_file.exists():
        save_settings({"user_name": profile.user.first_name or profile.user.username,
                       "daily_report": {**load_settings().get("daily_report", {}), "enabled": False}})
    memory_file = root / "memory" / "long_term.json"
    if not memory_file.exists():
        memory_file.write_text(json.dumps({"identity": {}, "preferences": {}, "projects": {}, "relationships": {},
                                           "wishes": {}, "notes": {}}, indent=2), encoding="utf-8")
    sync_shared_keys(profile.may_use_server_keys())


@contextmanager
def user_scope(user_or_profile):
    """Alle Actions/Einstellungen innerhalb dieses Blocks gelten für den Benutzer."""
    profile = user_or_profile if isinstance(user_or_profile, Profile) else profile_of(user_or_profile)
    with use_data_root(profile.data_root):
        ensure_user_data(profile)
        yield profile
