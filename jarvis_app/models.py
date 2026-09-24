import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


class Profile(models.Model):
    """JARVIS-spezifische Einstellungen pro Benutzer."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis")
    # Besitzer der Instanz: nutzt direkt config/ + memory/ des Projektordners (geteilt mit dem Desktop-JARVIS).
    # Alle anderen haben ein eigenes Datenverzeichnis userdata/<id>/ mit eigenen Einstellungen.
    uses_main_data = models.BooleanField(default=False)
    api_token = models.CharField(max_length=64, unique=True, default=_token)
    wake_word_mode = models.BooleanField(default=False)
    tts_enabled = models.BooleanField(default=True)
    hydration_reminder = models.BooleanField(default=False)
    current_file = models.CharField(max_length=500, blank=True)

    @property
    def full_access(self):
        """Voller Zugriff = Admin oder gültige Lizenz."""
        return self.user.is_superuser or self.license_valid()

    @property
    def has_full_access(self):
        return self.full_access

    @property
    def data_root(self):
        from jarvis_core.paths import PROJECT_ROOT
        if self.uses_main_data:
            return PROJECT_ROOT
        return settings.JARVIS_USERDATA / str(self.user_id)

    @property
    def data_prefix(self) -> str:
        """Pfad-Präfix relativ zum Projektordner (für die Zustandssicherung)."""
        return "" if self.uses_main_data else f"userdata/{self.user_id}/"

    def license(self):
        return LicenseKey.objects.filter(user_id=self.user_id).first()

    def license_valid(self) -> bool:
        if self.user.is_superuser:
            return True
        lic = self.license()
        return bool(lic and lic.is_valid)

    def may_use_server_keys(self) -> bool:
        if self.user.is_superuser:
            return True
        lic = self.license()
        return bool(lic and lic.is_valid and lic.use_server_key)

    def __str__(self):
        return f"Profil {self.user.username}"


class LicenseKey(models.Model):
    """Eine Lizenz gehört genau einem Benutzer (wird bei der Registrierung zugewiesen)."""

    key = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=120, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="jarvis_license")
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Darf der Nutzer die API-Keys des Servers (Gemini/OpenRouter/Tankerkönig) mitverwenden?
    use_server_key = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def generate_key() -> str:
        return "JARVIS-" + secrets.token_hex(8).upper()

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def is_valid(self) -> bool:
        return self.active and not self.is_expired

    def as_dict(self):
        return {
            "key": self.key, "label": self.label, "user": self.user.username if self.user else None,
            "active": self.active, "expired": self.is_expired, "valid": self.is_valid,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "use_server_key": self.use_server_key, "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }

    def __str__(self):
        return self.key


class ChatMessage(models.Model):
    ROLE_CHOICES = [("user", "Benutzer"), ("model", "JARVIS")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    text = models.TextField()
    source = models.CharField(max_length=20, default="text")  # text | voice | discord | hermes
    tools = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_notifications")
    kind = models.CharField(max_length=20, default="info")  # info | reminder | alarm | hydration | warning | report | hermes
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def as_dict(self):
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "body": self.body,
            "data": self.data, "read": self.read, "created_at": self.created_at.isoformat(),
        }


class Reminder(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_reminders")
    due_at = models.DateTimeField(db_index=True)
    message = models.CharField(max_length=500)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at"]


class Alarm(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jarvis_alarms")
    time = models.CharField(max_length=5)  # HH:MM
    music = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True)
    repeat = models.BooleanField(default=True)
    last_fired = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["time"]


class HermesTask(models.Model):
    """Aufträge an den Hermes Agent (Nous Research), die im Hintergrund laufen."""

    STATUS = [("running", "läuft"), ("done", "fertig"), ("failed", "fehlgeschlagen")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hermes_tasks")
    task = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS, default="running")
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def as_dict(self):
        return {
            "id": self.id, "task": self.task, "status": self.status, "result": self.result,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class StateFile(models.Model):
    """Spiegel der JSON-Dateien aus config/, memory/, content/ (und userdata/<id>/…) in der Datenbank.

    Online ist das Dateisystem flüchtig (Render). Die Actions lesen/schreiben weiter ihre
    Dateien, diese Tabelle sorgt dafür, dass sie Neustarts und Deploys überleben.
    """

    path = models.CharField(max_length=300, unique=True)
    content = models.BinaryField()
    sha1 = models.CharField(max_length=40)
    updated_at = models.DateTimeField(auto_now=True)


class JobState(models.Model):
    """Kleiner Key-Value-Speicher für Hintergrund-Jobs (Autopilot, Tagesbericht, E-Mail-Scan)."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key, default=None):
        obj = cls.objects.filter(key=key).first()
        return obj.value if obj else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={"value": value})


class UpdateApp(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True)

    def as_dict(self):
        return {
            "name": self.name, "slug": self.slug, "description": self.description,
            "versions": [v.as_dict() for v in self.sorted_versions()],
        }

    def sorted_versions(self):
        return sorted(self.versions.all(), key=lambda v: v.version_tuple, reverse=True)


class UpdateVersion(models.Model):
    app = models.ForeignKey(UpdateApp, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=40)
    release_date = models.CharField(max_length=20)
    download_link = models.URLField(max_length=500)
    release_notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("app", "version")]

    @property
    def version_tuple(self):
        return tuple(int(x) for x in self.version.split("."))

    def as_dict(self):
        return {
            "version": self.version, "release_date": self.release_date,
            "download_link": self.download_link, "release_notes": self.release_notes,
            "is_active": self.is_active,
        }
