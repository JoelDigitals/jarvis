import json, os, re, subprocess, time
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _BASE / "config"
_API_FILE = _CONFIG_DIR / "api_keys.json"

_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode"}
_TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".html", ".css", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini"}
_MAX_FILE_CHARS = 20000
_MAX_CONTEXT_CHARS = 80000

def _get_anthropic_key() -> str:
    if _API_FILE.exists():
        data = json.loads(_API_FILE.read_text(encoding="utf-8"))
        return data.get("anthropic_api_key", "")
    return ""

def _call_claude(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    key = _get_anthropic_key()
    if not key:
        return "Kein Anthropic API-Key hinterlegt. Füge 'anthropic_api_key' in config/api_keys.json ein."

    try:
        import anthropic
    except ImportError:
        return "anthropic-Paket nicht installiert. pip install anthropic"

    try:
        client = anthropic.Anthropic(api_key=key)
        kwargs = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text if resp.content else ""
    except Exception as e:
        return f"Claude API-Fehler: {e}"

def _call_claude_json(prompt: str, system: str = "", max_tokens: int = 8192) -> dict:
    raw = _call_claude(prompt, system, max_tokens)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"error": f"Konnte keine JSON-Antwort parsen: {raw[:200]}"}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        return {"error": f"JSON-Fehler: {e} — Antwort: {raw[:200]}"}

def _list_project_files(root: Path) -> list[str]:
    files = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in _TEXT_EXT:
            continue
        files.append(str(p.relative_to(root)).replace("\\", "/"))
    return files

def _read_files(root: Path, rel_paths: list[str]) -> dict:
    out = {}
    used = 0
    for rel in rel_paths:
        if used >= _MAX_CONTEXT_CHARS:
            break
        fp = root / rel
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")[:_MAX_FILE_CHARS]
            out[rel] = text
            used += len(text)
        except Exception:
            continue
    return out

def _project_task(project_path: str, task: str, run_command: str = "", max_iterations: int = 3) -> str:
    root = Path(project_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return f"Projektordner nicht gefunden: {project_path}"

    all_files = _list_project_files(root)
    if not all_files:
        return f"Keine Quelldateien in {project_path} gefunden."

    tree_str = "\n".join(all_files[:400])
    select = _call_claude_json(
        f"Hier ist die Dateiliste eines Projekts:\n{tree_str}\n\n"
        f"Aufgabe: {task}\n\n"
        "Welche Dateien brauchst du, um diese Aufgabe umzusetzen? "
        "Antworte NUR mit JSON: {\"files\": [\"relativer/pfad.py\", ...]}",
        "Du bist ein erfahrener Softwareentwickler.", 1024,
    )
    rel_paths = select.get("files") or []
    rel_paths = [f for f in rel_paths if f in all_files][:25]
    if not rel_paths:
        return f"Konnte keine relevanten Dateien für die Aufgabe finden ({select.get('error','')})."

    context = _read_files(root, rel_paths)
    files_blob = "\n\n".join(f"--- {p} ---\n{c}" for p, c in context.items())

    last_result = ""
    for attempt in range(max(1, max_iterations)):
        extra = f"\n\nLetzter Testlauf ergab folgenden Fehler, behebe ihn:\n{last_result}" if last_result else ""
        edit = _call_claude_json(
            f"Projektdateien:\n{files_blob}\n\nAufgabe: {task}{extra}\n\n"
            "Gib NUR JSON zurück mit den vollständigen neuen Dateiinhalten für jede geänderte Datei: "
            "{\"summary\": \"kurze Zusammenfassung auf Deutsch\", \"files\": {\"relativer/pfad.py\": \"vollständiger neuer Inhalt\"}}",
            "Du bist ein erfahrener Softwareentwickler. Schreibe sauberen, vollständigen Code, keine Auslassungen mit '...'.",
            8192,
        )
        if "error" in edit:
            return f"Fehler von Claude: {edit['error']}"
        changed = edit.get("files") or {}
        if not changed:
            return "Claude hat keine Dateiänderungen zurückgegeben."
        for rel, content in changed.items():
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            context[rel] = content
        files_blob = "\n\n".join(f"--- {p} ---\n{c}" for p, c in context.items())

        if not run_command:
            return f"{edit.get('summary','Änderungen durchgeführt.')} ({len(changed)} Datei(en) geändert: {', '.join(changed)})"

        try:
            proc = subprocess.run(run_command, shell=True, cwd=str(root), capture_output=True,
                                   text=True, timeout=60)
            output = (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            output = f"Konnte Testlauf nicht ausführen: {e}"

        if "proc" in locals() and proc.returncode == 0:
            return f"{edit.get('summary','Änderungen durchgeführt.')} Test erfolgreich. ({len(changed)} Datei(en) geändert)"
        last_result = output[-2000:]

    return f"Nach {max_iterations} Versuchen weiterhin Fehler: {last_result[:300]}"

def claude_action(parameters: dict = None, player=None) -> str:
    params = parameters or {}
    action = params.get("action", "chat").strip().lower()
    prompt = params.get("prompt", "").strip()
    system = params.get("system", "").strip()
    code = params.get("code", "").strip()
    language = params.get("language", "python")
    file_path = params.get("file_path", "")
    output_path = params.get("output_path", "")
    project_path = params.get("project_path", "").strip()
    run_command = params.get("run_command", "").strip()

    if action == "project_task":
        if not project_path or not prompt:
            return "Bitte project_path und prompt (Aufgabenbeschreibung) angeben."
        return _project_task(project_path, prompt, run_command)

    if not prompt and not code:
        return "Bitte gib einen prompt oder code an."

    if action == "chat":
        return _call_claude(prompt, system, 4096)

    if action == "write":
        if not output_path:
            return "Bitte output_path angeben."
        full_prompt = f"Schreibe {language}-Code für folgende Aufgabe:\n{prompt}"
        if system:
            full_prompt = f"{system}\n\n{full_prompt}"
        code_text = _call_claude(full_prompt, "", 8192)
        try:
            Path(output_path).write_text(code_text, encoding="utf-8")
            return f"Code geschrieben nach: {output_path}"
        except Exception as e:
            return f"Fehler beim Schreiben: {e}"

    if action == "explain":
        full = f"Erkläre folgenden {language}-Code:\n\n{code}"
        return _call_claude(full, system, 4096)

    if action == "debug":
        error = params.get("error", "")
        full = f"Debugge folgenden {language}-Code:\n\n{code}\n\nFehler: {error}"
        return _call_claude(full, system, 4096)

    if action == "refactor":
        full = f"Optimiere/Refaktorisiere folgenden {language}-Code:\n\n{code}"
        return _call_claude(full, system, 4096)

    if action == "review":
        if file_path:
            try:
                code = Path(file_path).read_text(encoding="utf-8")
            except:
                return f"Konnte Datei nicht lesen: {file_path}"
        full = f"Review folgenden {language}-Code. Gib Verbesserungsvorschläge:\n\n{code}"
        return _call_claude(full, system, 4096)

    return f"Unbekannte Aktion: {action}. Verfügbar: chat, write, explain, debug, refactor, review, project_task"
