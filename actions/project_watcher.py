"""Projekt-Watcher – überwacht konfigurierte Ordner selbstständig auf Fehler."""
import json, re, py_compile, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE / "config"
WATCH_FILE = CONFIG_DIR / "watched_projects.json"

_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)|^\s*\w*Error:|^\s*\w*Exception:", re.MULTILINE)


def _load() -> dict:
    if WATCH_FILE.exists():
        try:
            return json.loads(WATCH_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"projects": []}
    return {"projects": []}


def _save(data: dict):
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _py_files(root: Path):
    for p in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def _log_files(root: Path):
    for ext in ("*.log",):
        for p in root.rglob(ext):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            yield p


def scan_project(path: str) -> list[str]:
    """Gibt eine Liste menschenlesbarer Problembeschreibungen zurück (leer = alles ok)."""
    root = Path(path).expanduser().resolve()
    issues = []
    if not root.exists():
        return [f"Ordner nicht gefunden: {path}"]

    for py_file in _py_files(root):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            rel = py_file.relative_to(root)
            issues.append(f"Syntaxfehler in {rel}: {str(e.exc_value)[:150]}")
        except Exception:
            continue

    for log_file in _log_files(root):
        try:
            text = log_file.read_text(encoding="utf-8", errors="ignore")[-20000:]
        except Exception:
            continue
        if _TRACEBACK_RE.search(text):
            rel = log_file.relative_to(root)
            tail = text.strip().splitlines()[-1] if text.strip() else ""
            issues.append(f"Fehler im Log {rel}: {tail[:150]}")

    return issues


def project_watch_action(parameters: dict = None, player=None) -> str:
    params = parameters or {}
    action = params.get("action", "list").strip().lower()
    path = params.get("path", "").strip()
    name = params.get("name", "").strip() or path

    data = _load()

    if action == "add":
        if not path:
            return "Bitte einen Projektpfad angeben."
        if not Path(path).expanduser().exists():
            return f"Ordner nicht gefunden: {path}"
        if any(p["path"] == path for p in data["projects"]):
            return f"{name} wird bereits überwacht."
        data["projects"].append({"path": path, "name": name})
        _save(data)
        return f"{name} wird jetzt überwacht."

    if action == "remove":
        before = len(data["projects"])
        data["projects"] = [p for p in data["projects"] if p["path"] != path and p["name"] != name]
        _save(data)
        return "Entfernt." if len(data["projects"]) < before else "Projekt nicht in der Überwachung gefunden."

    if action == "list":
        if not data["projects"]:
            return "Keine Projekte werden überwacht."
        return "Überwachte Projekte: " + ", ".join(p["name"] for p in data["projects"])

    if action == "scan_now":
        if not data["projects"]:
            return "Keine Projekte konfiguriert. Sag mir, welchen Ordner ich überwachen soll."
        out = []
        for p in data["projects"]:
            issues = scan_project(p["path"])
            if issues:
                out.append(f"{p['name']}: " + " | ".join(issues[:5]))
            else:
                out.append(f"{p['name']}: keine Probleme gefunden.")
        return "\n".join(out)

    return "Unbekannte Aktion. Verfügbar: add, remove, list, scan_now"
