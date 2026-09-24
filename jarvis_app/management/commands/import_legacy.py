"""Übernimmt Daten der alten Flask-Version in die Django-Datenbank.

config/users.json          → Benutzer (Passwort-Hashes bleiben gültig)
config/license_keys.json   → Lizenzschlüssel
config/autoupdate/apps.json→ Autoupdate-Apps und Versionen
config/alarm.json          → Wecker des Admins
"""
import base64
import json
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from jarvis_app.models import Alarm, LicenseKey, UpdateApp, UpdateVersion


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Command(BaseCommand):
    help = "Importiert Benutzer, Lizenzen, Autoupdate-Daten und Wecker aus der Flask-Version."

    def handle(self, *args, **options):
        cfg = settings.BASE_DIR / "config"
        User = get_user_model()

        users = _load(cfg / "users.json") or {}
        for name, info in users.items():
            if User.objects.filter(username=name).exists():
                continue
            try:
                salt, digest = info["password"].split(":", 1)
                pw = f"pbkdf2_sha256$260000${salt}${base64.b64encode(bytes.fromhex(digest)).decode()}"
            except (KeyError, ValueError):
                continue
            u = User(username=name, password=pw, is_superuser=info.get("role") == "admin",
                     is_staff=info.get("role") == "admin")
            if info.get("created_at"):
                u.date_joined = datetime.fromtimestamp(info["created_at"], tz=timezone.utc)
            u.save()
            self.stdout.write(f"Benutzer übernommen: {name}")

        for key, info in (_load(cfg / "license_keys.json") or {}).items():
            LicenseKey.objects.get_or_create(key=key, defaults={
                "label": info.get("label", ""), "max_uses": info.get("max_uses", 20),
                "uses": info.get("uses", 0), "active": info.get("active", True)})

        for app in (_load(cfg / "autoupdate" / "apps.json") or {}).get("apps", []):
            obj, _ = UpdateApp.objects.get_or_create(slug=app["slug"], defaults={
                "name": app.get("name", app["slug"]), "description": app.get("description", "")})
            for v in app.get("versions", []):
                UpdateVersion.objects.get_or_create(app=obj, version=v["version"], defaults={
                    "release_date": v.get("release_date", ""), "download_link": v.get("download_link", ""),
                    "release_notes": v.get("release_notes", ""), "is_active": v.get("is_active", True)})
            self.stdout.write(f"Autoupdate-App übernommen: {app['slug']}")

        owner = User.objects.filter(is_superuser=True).order_by("id").first()
        if owner and not Alarm.objects.filter(user=owner).exists():
            seen = set()
            for a in _load(cfg / "alarm.json") or []:
                music = a.get("music", "") if a.get("music") != "play" else ""
                if (a.get("time"), music) in seen or not a.get("time"):
                    continue
                seen.add((a["time"], music))
                Alarm.objects.create(user=owner, time=a["time"], music=music, active=a.get("active", True))
                self.stdout.write(f"Wecker übernommen: {a['time']}")

        self.stdout.write(self.style.SUCCESS("Import abgeschlossen."))
