import json
from pathlib import Path
import sys

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

SETTINGS_PATH = _base_dir() / "config" / "settings.json"

# reuse the singleton browser thread from browser_control
from actions.browser_control import _bt, _ensure_started


def _load_sites() -> list[dict]:
    try:
        if SETTINGS_PATH.exists():
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return d.get("knowledge_sites", [])
    except:
        pass
    return []


def knowledge_list(parameters: dict, player=None) -> str:
    sites = _load_sites()
    if not sites:
        return "Keine Wissensseiten konfiguriert. Bitte in den Einstellungen hinzufügen."
    lines = ["Konfigurierte Wissensseiten:"]
    for s in sites:
        name = s.get("name", "?")
        url = s.get("url", "?")
        pages = s.get("pages", [])
        has_login = bool(s.get("username") and s.get("password"))
        lines.append(f"  • {name} ({url}) — {len(pages)} Seiten{' ✓ Login' if has_login else ''}")
    return "\n".join(lines)


def knowledge_query(parameters: dict, player=None) -> str:
    site_name = (parameters.get("site_name") or "").strip().lower()
    query = (parameters.get("query") or "").strip()

    sites = _load_sites()
    if not sites:
        return "Keine Wissensseiten konfiguriert."

    if site_name:
        matched = [s for s in sites if s.get("name", "").lower() == site_name]
        if not matched:
            names = ", ".join(s.get("name", "?") for s in sites)
            return f"Seite '{site_name}' nicht gefunden. Verfügbar: {names}"
        sites = matched

    _ensure_started()

    all_results = []

    for site in sites:
        name = site.get("name", "Unbekannt")
        url = site.get("url", "").rstrip("/")
        login_path = site.get("login_path", "").strip("/")
        username = site.get("username", "")
        password = site.get("password", "")
        pages = site.get("pages", [])
        page_results = []

        try:
            # 1. open site
            _bt.run(_bt._go_to(url))
            page_results.append(f"[{name}] {url} geöffnet")

            # 2. login if credentials exist
            if username and password and login_path:
                login_url = f"{url}/{login_path}"
                _bt.run(_bt._go_to(login_url))
                _bt.run(_bt._smart_type("Benutzername oder E-Mail", username))
                _bt.run(_bt._smart_type("Passwort", password))

                import asyncio
                import re

                # try common login button texts
                login_clicked = False
                for btn_text in ["Anmelden", "Login", "Einloggen", "Sign in", "Log in", "Submit"]:
                    try:
                        _bt.run(_bt._smart_click(btn_text), timeout=8)
                        login_clicked = True
                        break
                    except:
                        continue

                if not login_clicked:
                    # fallback: press Enter on focused element
                    try:
                        _bt.run(_bt._press("Enter"), timeout=5)
                        login_clicked = True
                    except:
                        pass

                page_results.append(f"  Login {'erfolgreich' if login_clicked else 'fehlgeschlagen'}")
                import time
                time.sleep(2)

            # 3. scrape each configured page
            if not pages:
                # site root only
                text = _bt.run(_bt._get_text())
                page_results.append(f"  Startseite: {len(text)} Zeichen")
                if query and query.lower() in text.lower():
                    page_results.append(f"  → Treffer für '{query}' auf der Startseite")
                all_results.append((name, page_results, text[:3000]))
                continue

            combined_text = ""
            for page_path in pages:
                page_url = f"{url}/{page_path.lstrip('/')}"
                try:
                    _bt.run(_bt._go_to(page_url))
                    text = _bt.run(_bt._get_text())
                    combined_text += f"\n\n=== {page_path} ===\n\n{text}"
                    page_results.append(f"  {page_path}: {len(text)} Zeichen")
                except Exception as e:
                    page_results.append(f"  {page_path}: Fehler — {e}")

            # 4. search for query in combined text
            if query:
                found = []
                for i, p in enumerate(pages):
                    if not combined_text:
                        break
                    # crude per-page matching by heading markers
                    marker = f"=== {p} ==="
                    idx = combined_text.find(marker)
                    if idx >= 0:
                        end = combined_text.find("\n\n===", idx + 1)
                        if end < 0:
                            end = len(combined_text)
                        page_section = combined_text[idx:end]
                        if query.lower() in page_section.lower():
                            found.append(p)
                if found:
                    page_results.append(f"  → '{query}' gefunden auf: {', '.join(found)}")
                else:
                    page_results.append(f"  → '{query}' nicht gefunden")

            all_results.append((name, page_results, combined_text[:2000]))

        except Exception as e:
            all_results.append((name, [f"  Fehler: {e}"], ""))

    # build summary
    summary_lines = []
    for name, logs, text_snippet in all_results:
        summary_lines.append(f"── {name} ──")
        summary_lines.extend(logs)
        if text_snippet:
            summary_lines.append(f"Auszug:\n{text_snippet[:500]}")

    return "\n".join(summary_lines) if summary_lines else "Keine Ergebnisse."


def knowledge_action(parameters: dict, player=None) -> str:
    action = (parameters.get("action") or "list").strip().lower()
    if action == "query":
        return knowledge_query(parameters, player)
    else:
        return knowledge_list(parameters, player)
