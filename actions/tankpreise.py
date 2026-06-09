import json, os, sys, time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

BASE = Path(__file__).resolve().parent.parent
CFG_PATH = BASE / "config" / "api_keys.json"

API_URL = "https://creativecommons.tankerkoenig.de/json"

def _api_key():
    try:
        d = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        return d.get("tankerkoenig_api_key", "")
    except:
        return ""

def _get(path, params):
    key = _api_key()
    if not key:
        return {"error": "Kein Tankerkoenig-API-Key in config/api_keys.json (tankerkoenig_api_key)"}
    params["apikey"] = key
    url = f"{API_URL}/{path}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "JARVIS/1.0"})
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

def tankpreise(parameters, response=None, player=None, session_memory=None):
    action = (parameters or {}).get("action", "").lower().strip()
    lat = (parameters or {}).get("lat")
    lng = (parameters or {}).get("lng")
    rad = (parameters or {}).get("radius", 5)
    sid = (parameters or {}).get("station_id", "")
    fuel = (parameters or {}).get("fuel", "e5")
    sort = (parameters or {}).get("sort", "price")

    rad_km = min(max(int(rad), 1), 25)

    try:
        if action == "stations":
            if not lat or not lng:
                return "Bitte lat und lng angeben."
            data = _get("list.php", {"lat": lat, "lng": lng, "rad": rad_km, "sort": sort, "type": fuel})
            if data.get("ok"):
                stations = data.get("stations", [])
                if not stations:
                    return "Keine Tankstellen gefunden."
                lines = [f"Tankstellen im Umkreis von {rad_km}km ({fuel.upper()}):"]
                for s in stations[:10]:
                    price = s.get("price", "?")
                    lines.append(f"  {s.get('name','?')} — {price:.3f}€" if isinstance(price,(int,float)) else f"  {s.get('name','?')} — {price}€")
                return "\n".join(lines)
            return f"Fehler: {data.get('message','Unbekannt')}"

        elif action == "prices":
            if not sid:
                return "Bitte station_id angeben."
            data = _get("prices.php", {"ids": sid})
            if data.get("ok"):
                s = data.get("prices", {}).get(sid, {})
                if not s:
                    return "Keine Preise für diese Station."
                lines = [f"Preise für Station {sid}:"]
                for ft in ("e5","e10","diesel"):
                    if ft in s:
                        lines.append(f"  {ft.upper()}: {s[ft]:.3f}€" if isinstance(s[ft],(int,float)) else f"  {ft.upper()}: {s[ft]}€")
                return "\n".join(lines)
            return f"Fehler: {data.get('message','Unbekannt')}"

        elif action == "search":
            if not lat or not lng:
                return "Bitte lat und lng angeben."
            data = _get("list.php", {"lat": lat, "lng": lng, "rad": rad_km, "sort": sort, "type": fuel})
            if data.get("ok"):
                stations = data.get("stations", [])
                if not stations:
                    return "Keine Tankstellen gefunden."
                cheapest = min(stations, key=lambda s: s.get("price", 9999))
                return (f"Günstigste Tankstelle: {cheapest.get('name','?')} "
                        f"({cheapest.get('price',0):.3f}€), "
                        f"Adresse: {cheapest.get('street','?')} {cheapest.get('houseNumber','')}, "
                        f"{cheapest.get('postCode','')} {cheapest.get('place','?')}")
            return f"Fehler: {data.get('message','Unbekannt')}"

        else:
            return ("Verfügbare Aktionen: search, stations, prices. "
                    "Parameter: action, lat, lng, radius (km, default 5), station_id, "
                    "fuel (e5/e10/diesel), sort (price/dist)")

    except Exception as e:
        return f"Fehler bei Tankpreis-Abfrage: {e}"
