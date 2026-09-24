"""Hermes Agent (Nous Research) als Arbeits-Agent für JARVIS.

Hermes Agent ist ein eigenständiger, selbstlernender KI-Agent mit Terminal-, Datei-,
Web- und Skill-Werkzeugen. JARVIS delegiert größere Arbeitsaufträge an ihn
(recherchieren, Dateien erstellen, Code schreiben und ausführen, Server-Aufgaben …).

Anbindung über die OpenAI-kompatible API von `hermes gateway`:
    API_SERVER_ENABLED=true  API_SERVER_KEY=<geheim>  (Standard: http://127.0.0.1:8642)
Doku: https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/

Konfiguration in config/settings.json → "hermes_config":
    {"base_url": "http://127.0.0.1:8642", "api_key": "...", "model": "hermes-agent"}
"""
from __future__ import annotations

import json

from jarvis_core.paths import DataPath

SETTINGS_PATH = DataPath("config") / "settings.json"
DEFAULT_URL = "http://127.0.0.1:8642"
DEFAULT_TIMEOUT = 900  # Sekunden – Agenten-Aufträge dürfen dauern


def load_config(override: dict | None = None) -> dict:
    cfg = {}
    try:
        cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("hermes_config") or {}
    except (OSError, ValueError):
        pass
    if override:
        cfg = {**cfg, **{k: v for k, v in override.items() if v}}
    cfg.setdefault("base_url", DEFAULT_URL)
    cfg.setdefault("model", "hermes-agent")
    cfg["base_url"] = str(cfg["base_url"]).rstrip("/")
    return cfg


def _headers(cfg: dict, session_key: str = "") -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        h["Authorization"] = f"Bearer {cfg['api_key']}"
    if session_key:
        h["X-Hermes-Session-Key"] = session_key[:256]
    return h


def status(cfg: dict) -> str:
    import requests
    try:
        r = requests.get(f"{cfg['base_url']}/health", timeout=8)
        if r.status_code != 200:
            return f"Hermes Agent antwortet mit HTTP {r.status_code}."
        models = requests.get(f"{cfg['base_url']}/v1/models", headers=_headers(cfg), timeout=8)
        if models.status_code == 401:
            return "Hermes Agent läuft, aber der API-Key ist falsch."
        names = [m.get("id") for m in (models.json().get("data") or [])] if models.ok else []
        return f"Hermes Agent ist erreichbar ({cfg['base_url']}). Modelle: {', '.join(names) or cfg['model']}."
    except requests.RequestException as e:
        return (f"Hermes Agent unter {cfg['base_url']} nicht erreichbar ({e.__class__.__name__}). "
                "Läuft 'hermes gateway' mit API_SERVER_ENABLED=true?")


def run_task(task: str, cfg: dict, session_key: str = "", context: str = "",
             timeout: int = DEFAULT_TIMEOUT) -> str:
    """Schickt einen Auftrag an Hermes und wartet auf das Ergebnis."""
    import requests

    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": task})
    try:
        r = requests.post(
            f"{cfg['base_url']}/v1/chat/completions",
            headers=_headers(cfg, session_key),
            json={"model": cfg.get("model", "hermes-agent"), "messages": messages, "stream": False},
            timeout=timeout,
        )
    except requests.Timeout:
        return f"Hermes Agent hat nach {timeout}s noch kein Ergebnis geliefert."
    except requests.RequestException as e:
        return f"Hermes Agent nicht erreichbar ({cfg['base_url']}): {e}"
    if r.status_code == 401:
        return "Hermes Agent: API-Key ungültig (API_SERVER_KEY prüfen)."
    if not r.ok:
        return f"Hermes Agent Fehler HTTP {r.status_code}: {r.text[:300]}"
    try:
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or "Hermes hat den Auftrag erledigt."
    except (ValueError, KeyError, IndexError):
        return r.text[:2000]


def hermes_action(parameters: dict = None, player=None) -> str:
    params = dict(parameters or {})
    cfg = load_config(params.pop("_config", None))
    action = str(params.get("action") or "run").strip().lower()
    if action == "status":
        return status(cfg)
    task = str(params.get("task") or "").strip()
    if not task:
        return "Bitte beschreibe den Auftrag für den Hermes Agent."
    if player:
        player.write_log(f"[Hermes] Auftrag: {task[:120]}")
    return run_task(task, cfg, session_key=str(params.get("_session_key") or "jarvis"),
                    context=str(params.get("_context") or ""))
