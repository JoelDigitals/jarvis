"""Django-Settings für die JARVIS Web-Anwendung.

Lokal: SQLite + Debug. Online (Render): DATABASE_URL (PostgreSQL), DJANGO_SECRET_KEY,
DJANGO_DEBUG=0. Alle Werte kommen aus Umgebungsvariablen.
"""
import os
import secrets
import sys
import time
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Actions rechnen mit lokaler Zeit (datetime.now()) → Server auf deutsche Zeit stellen
if hasattr(time, "tzset"):  # nur Linux/macOS; Windows nutzt die Systemzeitzone
    os.environ.setdefault("TZ", "Europe/Berlin")
    time.tzset()

# Kennzeichnet für Actions/Handler, dass JARVIS als Web-App läuft
os.environ.setdefault("JARVIS_SERVER_MODE", "1")


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _secret_key() -> str:
    key = os.environ.get("DJANGO_SECRET_KEY")
    if key:
        return key
    # Lokal: einmalig erzeugen und in config/ ablegen (per .gitignore ausgeschlossen)
    path = BASE_DIR / "config" / ".django_secret"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(50)
        path.write_text(key, encoding="utf-8")
        return key
    except OSError:
        return secrets.token_urlsafe(50)


SECRET_KEY = _secret_key()
IS_RENDER = bool(os.environ.get("RENDER"))
DEBUG = _env_bool("DJANGO_DEBUG", not IS_RENDER)

ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],.onrender.com").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")
CSRF_TRUSTED_ORIGINS.append("https://*.onrender.com")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "jarvis_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jarvis_web.urls"
WSGI_APPLICATION = "jarvis_web.wsgi.application"
ASGI_APPLICATION = "jarvis_web.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

# Nur ein Prozess: Voice-Sessions, Desktop-Agent und Scheduler leben im Speicher.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Eigene Einstellungen/Gedächtnis jedes Benutzers (außer dem Besitzer): userdata/<user_id>/config|memory|content
JARVIS_USERDATA = Path(os.environ.get("JARVIS_USERDATA", BASE_DIR / "userdata"))

# Hochgeladene Dateien + Ergebnisse von file_processor
MEDIA_ROOT = Path(os.environ.get("JARVIS_MEDIA_ROOT", BASE_DIR / "media"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
SESSION_COOKIE_AGE = 30 * 24 * 3600
SESSION_COOKIE_SAMESITE = "Lax"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── JARVIS ──
JARVIS_TEXT_MODEL = os.environ.get("JARVIS_TEXT_MODEL", "gemini-2.5-flash")
JARVIS_LIVE_MODEL = os.environ.get("JARVIS_LIVE_MODEL", "models/gemini-3.1-flash-live-preview")
JARVIS_VOICE = os.environ.get("JARVIS_VOICE", "Charon")
# Hintergrund-Jobs (Tagesbericht, E-Mail-Scan, Erinnerungen, Wecker). Nur in EINER Instanz aktiv lassen.
JARVIS_BACKGROUND_JOBS = _env_bool("JARVIS_BACKGROUND_JOBS", True)
JARVIS_EMAIL_SCAN = _env_bool("JARVIS_EMAIL_SCAN", True)
JARVIS_DISCORD = _env_bool("JARVIS_DISCORD", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.channels.server": {"level": "WARNING"}},
}
