import re
import json
import sys
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
    _SCRAPE_OK = True
except ImportError:
    _SCRAPE_OK = False

try:
    from google import genai
    _GENAI_OK = True
except ImportError:
    _GENAI_OK = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

API_CONFIG_PATH = _base_dir() / "config" / "api_keys.json"

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _extract_text(url: str, max_chars: int = 15000) -> str:
    if not _SCRAPE_OK:
        return "BeautifulSoup nicht installiert. pip install beautifulsoup4 requests"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars]
    except requests.Timeout:
        return "Zeitüberschreitung beim Abruf der Seite."
    except Exception as e:
        return f"Fehler beim Abruf: {e}"

def web_summarize(parameters: dict, player=None) -> str:
    url = parameters.get("url", "").strip()
    action = parameters.get("action", "summarize").strip().lower()

    if not url:
        return "Keine URL angegeben."

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if player:
        player.write_log(f"[WebSummarizer] Lese: {url}")

    text = _extract_text(url)
    if len(text) < 50:
        return f"Konnte nicht genug Inhalt von {url} extrahieren."

    if action == "rohtext":
        return text[:3000]

    if not _GENAI_OK:
        short = text[:500]
        return f"Inhalt von {url}:\n\n{short}..."

    try:
        import google.generativeai as genai_ai
        genai_ai.configure(api_key=_get_api_key())
        model = genai_ai.GenerativeModel("gemini-2.5-flash")

        action_map = {
            "summarize": "Fasse den folgenden Webseiten-Inhalt auf Deutsch kurz und verständlich zusammen. "
                         "Nenne die wichtigsten Punkte in 3-5 Sätzen.",
            "analyze": "Analysiere den folgenden Webseiten-Inhalt auf Deutsch. "
                       "Was ist das Hauptthema? Für wen ist die Seite gedacht? Welche Kernaussagen gibt es?",
            "extract": "Extrahiere alle wichtigen Informationen aus dem folgenden Webseiten-Inhalt auf Deutsch. "
                       "Strukturierte Aufzählung.",
            "compare": "Fasse den Inhalt auf Deutsch zusammen und vergleiche ihn mit typischen Alternativen.",
        }
        prompt = action_map.get(action, action_map["summarize"])
        full_prompt = f"{prompt}\n\nURL: {url}\n\nInhalt:\n{text}"

        response = model.generate_content(full_prompt)
        result = response.text.strip()
        return result

    except Exception as e:
        short = text[:1000]
        return f"KI-Analyse fehlgeschlagen: {e}\n\nRohtext:\n{short}..."

def web_search_summarize(parameters: dict, player=None) -> str:
    query = parameters.get("query", "").strip()
    if not query:
        return "Keine Suchanfrage angegeben."

    if player:
        player.write_log(f"[WebSummarizer] Suche: {query}")

    try:
        from actions.web_search import web_search as ws
        search_result = ws(parameters={"query": query, "mode": "search"}, player=player)
        if not search_result or len(search_result) < 20:
            return f"Keine Suchergebnisse für: {query}"
        return web_summarize(parameters={"url": "", "action": "summarize"}, player=player)
    except Exception as e:
        return f"Suche fehlgeschlagen: {e}"
