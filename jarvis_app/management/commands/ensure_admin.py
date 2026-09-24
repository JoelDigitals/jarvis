"""Legt den Admin-Account aus Umgebungsvariablen an (für Render beim Deploy).

JARVIS_ADMIN_USER      (Standard: JoelDigitals)
JARVIS_ADMIN_PASSWORD  (Pflicht, sonst passiert nichts)
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Admin-Benutzer aus JARVIS_ADMIN_USER/JARVIS_ADMIN_PASSWORD anlegen bzw. Passwort setzen."

    def handle(self, *args, **options):
        username = os.environ.get("JARVIS_ADMIN_USER", "JoelDigitals")
        password = os.environ.get("JARVIS_ADMIN_PASSWORD", "")
        if not password:
            self.stdout.write("JARVIS_ADMIN_PASSWORD nicht gesetzt – übersprungen.")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username)
        user.is_superuser = user.is_staff = user.is_active = True
        if created or not user.check_password(password):
            user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin '{username}' {'angelegt' if created else 'aktualisiert'}."))
