"""Plugin-System – lädt eigene Fähigkeiten aus actions/plugins/*.py, ohne main.py anzufassen.

Ein Plugin ist eine .py-Datei in actions/plugins/ mit:
    TOOL = {
        "name": "mein_tool",
        "description": "Was das Tool tut, wann die KI es nutzen soll.",
        "parameters": {"type": "OBJECT", "properties": {...}, "required": [...]},
    }
    def run(parameters: dict, player=None) -> str:
        ...

Dateien, die mit "_" beginnen, werden ignoriert.
"""
import importlib.util
import traceback
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parent / "plugins"

_cache: dict | None = None


def _load_all() -> dict:
    plugins = {}
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    for f in PLUGINS_DIR.glob("*.py"):
        if f.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tool = getattr(mod, "TOOL", None)
            run_fn = getattr(mod, "run", None)
            if not tool or not callable(run_fn):
                print(f"[PLUGIN] ⚠️ {f.name} hat kein gültiges TOOL/run() — übersprungen.")
                continue
            name = tool.get("name")
            if not name:
                continue
            plugins[name] = {"tool": tool, "run": run_fn, "file": f.name}
            print(f"[PLUGIN] ✅ geladen: {name} ({f.name})")
        except Exception as e:
            print(f"[PLUGIN] ❌ Fehler in {f.name}: {e}")
            traceback.print_exc()
    return plugins


def get_plugins(force_reload: bool = False) -> dict:
    global _cache
    if _cache is None or force_reload:
        _cache = _load_all()
    return _cache


def get_plugin_tool_declarations() -> list:
    return [p["tool"] for p in get_plugins().values()]


def run_plugin(name: str, parameters: dict, player=None) -> str | None:
    """Gibt None zurück, wenn kein Plugin mit diesem Namen existiert (kein Fehler)."""
    plugins = get_plugins()
    p = plugins.get(name)
    if not p:
        return None
    try:
        return p["run"](parameters=parameters, player=player)
    except Exception as e:
        return f"Plugin-Fehler ({name}): {e}"
