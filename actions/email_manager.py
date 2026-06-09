import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
import json
import re
from pathlib import Path
import sys

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

SETTINGS_PATH = _base_dir() / "config" / "settings.json"
LEGACY_PATH   = _base_dir() / "config" / "email_config.json"
EMAIL_CACHE   = _base_dir() / "memory" / "email_cache.json"

def _load_all_accounts() -> list[dict]:
    try:
        if SETTINGS_PATH.exists():
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            accounts = d.get("email_accounts", [])
            if accounts:
                return accounts
    except:
        pass
    try:
        if LEGACY_PATH.exists():
            cfg = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
            if cfg.get("email"):
                return [{
                    "name": "Standard",
                    "email": cfg["email"],
                    "password": cfg.get("password", ""),
                    "imap_server": cfg.get("imap_server", "imap.gmail.com"),
                    "smtp_server": cfg.get("smtp_server", "smtp.gmail.com"),
                    "smtp_port": cfg.get("smtp_port", 587),
                }]
    except:
        pass
    return []

def _get_default_sender() -> str:
    try:
        from config.settings import load
        return (load().get("default_sender") or "").strip().lower()
    except:
        return ""

def _pick_account(parameters: dict) -> dict:
    accounts = _load_all_accounts()
    if not accounts:
        return {}
    name = (parameters.get("account") or "").strip().lower()
    if name:
        for a in accounts:
            if a.get("name", "").lower() == name:
                return a
    default = _get_default_sender()
    if default:
        for a in accounts:
            if a.get("name", "").lower() == default:
                return a
    return accounts[0]

def _decode_str(s: str) -> str:
    decoded, charset = decode_header(s)[0]
    if isinstance(decoded, bytes):
        charset = charset or "utf-8"
        try:
            return decoded.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return decoded.decode("utf-8", errors="replace")
    return str(decoded)

def _connect_imap(cfg: dict):
    imap = imaplib.IMAP4_SSL(cfg.get("imap_server", "imap.gmail.com"), 993)
    imap.login(cfg["email"], cfg["password"])
    imap.select("INBOX")
    return imap

def email_list(parameters: dict, player=None) -> str:
    cfg = _pick_account(parameters)
    if not cfg.get("email") or not cfg.get("password"):
        return "Keine E-Mail-Konfiguration gefunden. Bitte in den Einstellungen einrichten."

    try:
        count = min(int(parameters.get("count", 5)), 20)
        folder = parameters.get("folder", "INBOX")
        unread_only = parameters.get("unread_only", False)
        account_info = f" ({cfg.get('name','')}):" if cfg.get("name") else ":"

        imap = _connect_imap(cfg)
        imap.select(folder)

        search_crit = "UNSEEN" if unread_only else "ALL"
        status, ids = imap.search(None, search_crit)
        if status != "OK":
            return "Konnte keine E-Mails abrufen."

        msg_ids = ids[0].split() if ids[0] else []
        if not msg_ids:
            return f"Keine E-Mails{account_info}"

        msg_ids = msg_ids[-count:]
        result_lines = [f"E-Mails{account_info}"]

        for mid in msg_ids:
            status, data = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            raw = email.message_from_bytes(data[0][1])
            subject = _decode_str(raw["Subject"] or "(Kein Betreff)")
            sender = _decode_str(raw["From"] or "(Unbekannt)")
            date = raw["Date"] or ""
            result_lines.append(f"  {sender} — {subject}")

        imap.logout()
        return "\n".join(result_lines) if len(result_lines) > 1 else "Keine E-Mails gefunden."

    except imaplib.IMAP4.error as e:
        return f"IMAP-Fehler: {e}"
    except Exception as e:
        return f"E-Mail-Fehler: {e}"

def email_read(parameters: dict, player=None) -> str:
    cfg = _pick_account(parameters)
    if not cfg.get("email") or not cfg.get("password"):
        return "Keine E-Mail-Konfiguration."

    try:
        index = int(parameters.get("index", 1)) - 1
        folder = parameters.get("folder", "INBOX")

        imap = _connect_imap(cfg)
        imap.select(folder)
        status, ids = imap.search(None, "ALL")
        if status != "OK" or not ids[0]:
            return "Keine E-Mails gefunden."

        msg_ids = ids[0].split()
        if index >= len(msg_ids):
            return f"Es gibt nur {len(msg_ids)} E-Mails."
        mid = msg_ids[-(index + 1)]

        status, data = imap.fetch(mid, "(RFC822)")
        if status != "OK":
            return "Konnte Nachricht nicht abrufen."

        raw = email.message_from_bytes(data[0][1])
        subject = _decode_str(raw["Subject"] or "(Kein Betreff)")
        sender = _decode_str(raw["From"] or "(Unbekannt)")
        date = raw["Date"] or ""

        body = ""
        if raw.is_multipart():
            for part in raw.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                        break
        else:
            payload = raw.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        body = body.strip()[:2000] if body else "(Kein Inhalt)"
        imap.logout()

        return f"Von: {sender}\nBetreff: {subject}\nDatum: {date}\n\n{body}"

    except Exception as e:
        return f"Lesefehler: {e}"

def email_send(parameters: dict, player=None) -> str:
    cfg = _pick_account(parameters)
    if not cfg.get("email") or not cfg.get("password"):
        return "Keine E-Mail-Konfiguration."

    to = parameters.get("to", "").strip()
    subject = parameters.get("subject", "").strip()
    body = parameters.get("body", "").strip()

    if not to or not subject:
        return "Empfänger (to) und Betreff (subject) sind erforderlich."

    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["email"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        smtp_server = cfg.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(cfg.get("smtp_port", 587))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(cfg["email"], cfg["password"])
            server.send_message(msg)

        return f"E-Mail gesendet an {to} — Betreff: {subject}"

    except Exception as e:
        return f"Senden fehlgeschlagen: {e}"

def email_setup(parameters: dict, player=None) -> str:
    from config.settings import load, save
    email_addr = parameters.get("email", "").strip()
    password = parameters.get("password", "").strip()
    imap = parameters.get("imap_server", "imap.gmail.com")
    smtp = parameters.get("smtp_server", "smtp.gmail.com")
    smtp_port = int(parameters.get("smtp_port", 587))
    name = parameters.get("name", "Standard").strip()

    if not email_addr or not password:
        return "E-Mail und Passwort erforderlich. Nutzung: email_setup(email=\"...\", password=\"...\")"

    cfg = load()
    accounts = cfg.get("email_accounts", [])
    accounts.append({
        "name": name, "email": email_addr, "password": password,
        "imap_server": imap, "smtp_server": smtp, "smtp_port": smtp_port,
    })
    cfg["email_accounts"] = accounts
    save(cfg)
    return f"E-Mail-Konto '{name}' ({email_addr}) konfiguriert."

def test_connection() -> str:
    cfg = _pick_account({})
    if not cfg.get("email") or not cfg.get("password"):
        return "Keine E-Mail-Konfiguration."
    try:
        imap = _connect_imap(cfg)
        imap.logout()
        return f"Verbindung zu {cfg['email']} erfolgreich."
    except Exception as e:
        return f"Verbindungsfehler: {e}"

def email_accounts() -> str:
    accounts = _load_all_accounts()
    if not accounts:
        return "Keine E-Mail-Konten konfiguriert."
    default = _get_default_sender()
    lines = [f"Konfigurierte E-Mail-Konten ({len(accounts)}):"]
    for a in accounts:
        name = a.get("name", "?")
        email = a.get("email", "?")
        marker = " ← STANDARD" if name.lower() == default else ""
        lines.append(f"  • {name} — {email}{marker}")
    return "\n".join(lines)

def email_action(parameters: dict, player=None) -> str:
    action = parameters.get("action", "list").lower().strip()
    if action == "setup":
        return email_setup(parameters, player)
    elif action == "send":
        return email_send(parameters, player)
    elif action == "read":
        return email_read(parameters, player)
    elif action == "accounts":
        return email_accounts()
    else:
        return email_list(parameters, player)
