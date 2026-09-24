"""Einmalige Initialisierung beim Serverstart (aus asgi.py aufgerufen)."""
import logging

from django.conf import settings
from django.db import close_old_connections

log = logging.getLogger("jarvis.startup")


def run():
    # Eigener Thread: ORM-Zugriffe dürfen nicht in einem laufenden Event-Loop passieren
    import threading
    t = threading.Thread(target=_run, name="jarvis-startup", daemon=True)
    t.start()
    t.join(timeout=60)


def _run():
    from . import state_sync
    from .config_store import ensure_api_keys

    try:
        state_sync.restore()
    except Exception as e:  # z. B. Migrationen noch nicht ausgeführt
        log.warning("[Startup] Zustand nicht wiederhergestellt: %s", e)
    try:
        ensure_api_keys()
        state_sync.snapshot()
    except Exception as e:
        log.warning("[Startup] API-Keys/Snapshot: %s", e)
    finally:
        close_old_connections()

    if settings.JARVIS_BACKGROUND_JOBS:
        from . import scheduler
        scheduler.start()
