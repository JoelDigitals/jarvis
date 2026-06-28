import json, os, time, subprocess, threading
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _BASE / "config"
_CONTENT_DIR = _BASE / "content" / "social"
_CONTENT_DIR.mkdir(parents=True, exist_ok=True)

_PLATFORMS = {"instagram", "tiktok", "twitter", "linkedin", "youtube", "facebook"}

def _load_platforms() -> dict:
    p = _CONFIG_DIR / "social_accounts.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

def _save_draft(platform: str, content: str, media_paths: list[str] = None, schedule: str = ""):
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe = platform.lower().replace(" ", "_")
    draft = {
        "platform": platform,
        "content": content,
        "media": media_paths or [],
        "schedule": schedule,
        "created": ts,
        "status": "draft",
    }
    fp = _CONTENT_DIR / f"{ts}_{safe}.json"
    fp.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(fp)

def _list_drafts(platform: str = "") -> list[dict]:
    drafts = []
    for fp in sorted(_CONTENT_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            if platform and d.get("platform", "").lower() != platform.lower():
                continue
            drafts.append(d)
        except:
            pass
    return drafts

def _publish_draft(draft_path: str) -> str:
    fp = Path(draft_path)
    if not fp.exists():
        return f"Datei nicht gefunden: {draft_path}"
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        d["status"] = "published"
        d["published_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        fp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        plat = d.get("platform", "unknown")
        preview = d.get("content", "")[:100]
        log_fp = _CONTENT_DIR / "published.log"
        log_fp.write_text(f"[{d['published_at']}] {plat}: {preview}\n", encoding="utf-8")
        return f"Veröffentlicht auf {plat}. Inhalt: {preview}..."
    except Exception as e:
        return f"Fehler beim Veröffentlichen: {e}"

def _analytics() -> dict:
    drafts = _list_drafts()
    total = len(drafts)
    published = sum(1 for d in drafts if d.get("status") == "published")
    by_platform = {}
    for d in drafts:
        p = d.get("platform", "unknown")
        by_platform[p] = by_platform.get(p, 0) + 1
    return {"total": total, "published": published, "by_platform": by_platform}

def social_action(parameters: dict = None, player=None) -> str:
    params = parameters or {}
    action = params.get("action", "create").lower().strip()
    platform = params.get("platform", "").lower().strip()
    content = params.get("content", "").strip()
    media = params.get("media", [])
    schedule = params.get("schedule", "").strip()
    draft_path = params.get("draft_path", "").strip()

    if action == "create":
        if not content:
            return "Bitte gib einen Inhalt (content) für den Post an."
        if platform and platform not in _PLATFORMS:
            return f"Unbekannte Plattform: {platform}. Verfügbar: {', '.join(sorted(_PLATFORMS))}"
        fp = _save_draft(platform or "allgemein", content, media, schedule)
        return f"Content als Entwurf gespeichert: {fp}"

    if action == "list":
        drafts = _list_drafts(platform)
        if not drafts:
            return "Keine Entwürfe gefunden."
        out = [f"Entwürfe ({len(drafts)}):"]
        for d in drafts[:10]:
            preview = d.get("content", "")[:80]
            plat = d.get("platform", "?")
            status = d.get("status", "draft")
            out.append(f"  [{plat}] {status}: {preview}...")
        return "\n".join(out)

    if action == "publish":
        if not draft_path:
            return "Bitte eine draft_path angeben."
        return _publish_draft(draft_path)

    if action == "analytics":
        a = _analytics()
        return f"Content-Statistiken: {a['total']} total, {a['published']} veröffentlicht. Pro Plattform: {a['by_platform']}"

    if action == "platforms":
        configured = _load_platforms()
        if configured:
            return f"Konfigurierte Plattformen: {', '.join(configured.keys())}"
        return f"Verfügbare Plattformen: {', '.join(sorted(_PLATFORMS))}. Konfiguration in config/social_accounts.json"

    return f"Unbekannte Aktion: {action}. Verfügbar: create, list, publish, analytics, platforms"
