import json, threading, time
from pathlib import Path
import sys

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

KB_PATH = _base_dir() / "memory" / "knowledge_base.json"
_lock = threading.Lock()

def _load() -> dict:
    try:
        if KB_PATH.exists():
            return json.loads(KB_PATH.read_text(encoding="utf-8"))
    except: pass
    return {}

def _save(data: dict):
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    KB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def kb_set(category: str, key: str, value: str) -> str:
    with _lock:
        data = _load()
        if category not in data:
            data[category] = {}
        data[category][key] = {"value": value, "updated": time.strftime("%Y-%m-%d %H:%M")}
        _save(data)
    return f"Wissen gespeichert: {category} → {key}"

def kb_get(category: str = "", key: str = "") -> str:
    data = _load()
    if not data:
        return "Keine Einträge in der Wissensdatenbank."
    if category:
        cat = data.get(category, {})
        if key:
            entry = cat.get(key)
            if entry:
                return f"{category} → {key}: {entry['value']} (seit {entry['updated']})"
            return f"Schlüssel '{key}' nicht in '{category}' gefunden."
        if cat:
            lines = [f"{k}: {v['value']}" for k, v in cat.items()]
            return f"{category}: " + " | ".join(lines)
        return f"Kategorie '{category}' leer."
    parts = []
    for cat, entries in data.items():
        items = [f"{k}: {v['value']}" for k, v in entries.items()]
        parts.append(f"{cat}: " + ", ".join(items[:5]))
    return "Wissensdatenbank: " + " ||| ".join(parts) if parts else "Leer."

def kb_delete(category: str, key: str = "") -> str:
    with _lock:
        data = _load()
        if category in data:
            if key:
                if key in data[category]:
                    del data[category][key]
                    _save(data)
                    return f"'{key}' aus '{category}' gelöscht."
                return f"'{key}' nicht gefunden."
            del data[category]
            _save(data)
            return f"Kategorie '{category}' gelöscht."
    return f"'{category}' nicht gefunden."

def kb_action(parameters: dict, player=None) -> str:
    action = (parameters.get("action") or "get").strip().lower()
    cat = (parameters.get("category") or "").strip()
    key = (parameters.get("key") or "").strip()
    val = (parameters.get("value") or "").strip()
    if action == "set":
        if not cat or not key or not val:
            return "category, key und value erforderlich."
        return kb_set(cat, key, val)
    elif action == "delete":
        return kb_delete(cat, key)
    elif action == "get":
        return kb_get(cat, key)
    else:
        return f"Unbekannte Aktion: {action}"
