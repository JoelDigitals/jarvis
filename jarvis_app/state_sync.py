"""Spiegelt JARVIS-Zustandsdateien (config/, memory/, content/) in die Datenbank.

Die Actions arbeiten unverändert mit ihren JSON-Dateien. Beim Start werden die Dateien
aus der DB wiederhergestellt, nach jeder Änderung werden sie zurückgeschrieben. Damit
bleiben Gedächtnis, Einstellungen, Wissensdatenbank usw. online über Deploys erhalten.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import threading
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections

log = logging.getLogger("jarvis.state")

BASE: Path = settings.BASE_DIR
# Glob-Muster relativ zum Projektordner (Besitzer + Benutzer-Verzeichnisse userdata/<id>/)
_USER_PATTERNS = ["config/*.json", "config/*.pickle", "memory/*.json", "content/*.json", "content/**/*.json"]
PATTERNS = _USER_PATTERNS + [f"userdata/*/{p}" for p in _USER_PATTERNS]
EXCLUDED_NAMES = {".django_secret", "agent.json"}
MAX_BYTES = 5 * 1024 * 1024

_lock = threading.Lock()
_known: dict[str, str] = {}  # rel_path -> sha1 (zuletzt synchronisiert)


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _iter_files():
    seen = set()
    for pattern in PATTERNS:
        for p in BASE.glob(pattern):
            if p in seen or not p.is_file() or p.name in EXCLUDED_NAMES or p.stat().st_size > MAX_BYTES:
                continue
            seen.add(p)
            yield p


def _rel(p: Path) -> str:
    return p.relative_to(BASE).as_posix()


def is_allowed_path(rel_path: str) -> bool:
    """Nur Dateien in den gesicherten Ordnern dürfen per Upload gesetzt werden."""
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    parts = rel_path.split("/")
    if ".." in parts or not parts[-1] or parts[-1] in EXCLUDED_NAMES:
        return False
    return any(fnmatch.fnmatchcase(rel_path, pat) for pat in PATTERNS)


def restore() -> int:
    """DB → Festplatte. Schreibt Dateien, die fehlen oder vom DB-Stand abweichen."""
    from .models import StateFile

    count = 0
    with _lock:
        for sf in StateFile.objects.all():
            target = BASE / sf.path
            data = bytes(sf.content)
            try:
                if target.exists() and _sha1(target.read_bytes()) == sf.sha1:
                    _known[sf.path] = sf.sha1
                    continue
                if target.exists() and target.stat().st_mtime > sf.updated_at.timestamp():
                    # Lokale Datei ist neuer (z. B. Desktop-JARVIS hat sie geändert) → nicht überschreiben
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                _known[sf.path] = sf.sha1
                count += 1
            except OSError as e:
                log.warning("Konnte %s nicht wiederherstellen: %s", sf.path, e)
    if count:
        log.info("[State] %d Datei(en) aus der Datenbank wiederhergestellt", count)
    return count


def snapshot() -> int:
    """Festplatte → DB. Speichert alle geänderten Dateien."""
    from .models import StateFile

    count = 0
    with _lock:
        for p in _iter_files():
            rel = _rel(p)
            try:
                data = p.read_bytes()
            except OSError:
                continue
            digest = _sha1(data)
            if _known.get(rel) == digest:
                continue
            StateFile.objects.update_or_create(path=rel, defaults={"content": data, "sha1": digest})
            _known[rel] = digest
            count += 1
    return count


def write_file(rel_path: str, data: bytes) -> None:
    """Datei setzen (Upload im Admin-Bereich oder vom Desktop-Agent) und sofort sichern."""
    from .models import StateFile

    rel_path = rel_path.replace("\\", "/").lstrip("/")
    if not is_allowed_path(rel_path):
        raise ValueError(f"Pfad nicht erlaubt: {rel_path}")
    target = BASE / rel_path
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = _sha1(data)
        StateFile.objects.update_or_create(path=rel_path, defaults={"content": data, "sha1": digest})
        _known[rel_path] = digest


def snapshot_async() -> None:
    def _run():
        try:
            snapshot()
        except Exception as e:  # DB kurz nicht erreichbar o. ä. → nächster Lauf holt es nach
            log.warning("[State] Snapshot fehlgeschlagen: %s", e)
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True, name="state-snapshot").start()
