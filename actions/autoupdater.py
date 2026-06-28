"""Autoupdater Client – Prüft auf neue Versionen, lädt sie herunter und installiert sie automatisch"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "version.txt"


def _read_current_version() -> str:
    if VERSION_FILE.exists():
        v = VERSION_FILE.read_text(encoding="utf-8").strip()
        if v:
            return v
    return "0.0.0.0"


def _write_current_version(version: str):
    VERSION_FILE.write_text(version.strip(), encoding="utf-8")


def check_for_update(
    server_url: str,
    app_slug: str,
    current_version: str | None = None,
    timeout: int = 5,
) -> dict:
    if current_version is None:
        current_version = _read_current_version()
    url = f"{server_url.rstrip('/')}/api/autoupdate/check/{app_slug}?current_version={current_version}"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        return {"error": str(e), "update_available": False}
    except Exception as e:
        return {"error": str(e), "update_available": False}


def get_download_link(
    server_url: str,
    app_slug: str,
    current_version: str | None = None,
    timeout: int = 5,
) -> str | None:
    result = check_for_update(server_url, app_slug, current_version, timeout)
    if result.get("update_available"):
        return result.get("download_link")
    return None


def apply_update(download_link: str, new_version: str, timeout: int = 60) -> str:
    """Lädt die neue Jarvis.exe herunter und ersetzt die laufende automatisch (kein manueller Schritt nötig).

    Funktioniert nur in einer gebauten .exe (sys.frozen). Im Quellcode-Betrieb wird nur benachrichtigt.
    """
    if not getattr(sys, "frozen", False):
        return "Update erkannt, aber automatische Installation nur in der gebauten Jarvis.exe möglich."

    exe_path = Path(sys.executable).resolve()
    tmp_dir = Path(tempfile.gettempdir())
    new_exe = tmp_dir / f"Jarvis_{new_version}.exe"

    req = Request(download_link, method="GET")
    with urlopen(req, timeout=timeout) as resp, open(new_exe, "wb") as f:
        shutil.copyfileobj(resp, f)

    bat_path = tmp_dir / "jarvis_update.bat"
    bat_path.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'move /y "{new_exe}" "{exe_path}"\r\n'
        f'start "" "{exe_path}"\r\n'
        f'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(bat_path)], creationflags=subprocess.CREATE_NO_WINDOW)
    _write_current_version(new_version)
    return f"Update auf {new_version} wird installiert, Jarvis startet gleich neu."
