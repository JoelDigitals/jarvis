import json
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

NOMINATIM = "https://nominatim.openstreetmap.org"
OSRM = "https://router.project-osrm.org"
OVERPASS = "https://overpass-api.de/api/interpreter"

def _req(url, timeout=10, data=None):
    req = Request(url, headers={"User-Agent": "JARVIS/1.0"}, data=data)
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _geocode(address):
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
    data = _req(f"{NOMINATIM}/search?{urlencode(params)}")
    if data:
        r = data[0]
        return {
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "display": r.get("display_name", address)
        }
    return None

def maps_api(parameters, response=None, player=None, session_memory=None):
    action = (parameters or {}).get("action", "").lower().strip()
    addr_from = (parameters or {}).get("from", "")
    addr_to = (parameters or {}).get("to", "")
    address = (parameters or {}).get("address", "")
    query = (parameters or {}).get("query", "")
    lat = (parameters or {}).get("lat")
    lng = (parameters or {}).get("lng")
    rad = (parameters or {}).get("radius", 1000)

    try:
        if action == "geocode":
            if not address:
                return "Bitte address angeben."
            r = _geocode(address)
            if r:
                return f"{r['display']}\nKoordinaten: {r['lat']}, {r['lon']}"
            return f"Adresse '{address}' nicht gefunden."

        elif action == "directions":
            if not addr_from or not addr_to:
                return "Bitte from und to angeben."
            f = _geocode(addr_from)
            t = _geocode(addr_to)
            if not f or not t:
                return "Start oder Ziel nicht gefunden."
            params = {
                "overview": "full", "geometries": "geojson",
                "steps": "false", "alternatives": "false"
            }
            url = f"{OSRM}/route/driving/{f['lon']},{f['lat']};{t['lon']},{t['lat']}?{urlencode(params)}"
            data = _req(url)
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                dist_km = route["distance"] / 1000
                dur_min = route["duration"] / 60
                return (f"Strecke: {dist_km:.1f}km, Dauer: {dur_min:.0f}min\n"
                        f"Von: {f['display']}\nNach: {t['display']}")
            return "Route konnte nicht berechnet werden."

        elif action == "distance":
            if not addr_from or not addr_to:
                return "Bitte from und to angeben."
            f = _geocode(addr_from)
            t = _geocode(addr_to)
            if not f or not t:
                return "Start oder Ziel nicht gefunden."
            params = {"overview": "false", "steps": "false", "alternatives": "false"}
            url = f"{OSRM}/route/driving/{f['lon']},{f['lat']};{t['lon']},{t['lat']}?{urlencode(params)}"
            data = _req(url)
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                return f"Luftlinie: {route['distance']/1000:.1f}km, Fahrzeit: {route['duration']/60:.0f}min"
            return "Distanz konnte nicht berechnet werden."

        elif action == "search":
            if not query:
                return "Bitte query angeben."
            bbox = ""
            if lat is not None and lng is not None:
                bbox = f"({float(lat)-float(rad)/111000},{float(lng)-float(rad)/111000},{float(lat)+float(rad)/111000},{float(lng)+float(rad)/111000})"
            q_esc = query.replace('"', '')
            overpass_query = f"""
            [out:json][timeout:10]{bbox};
            node["name"~"{q_esc}",i](if:number(t["name"])==0);
            out 5;
            """
            data = _req(OVERPASS, data=overpass_query.encode())
            elements = data.get("elements", [])
            if not elements:
                return f"Keine POIs zu '{query}' gefunden."
            lines = [f"Ergebnisse für '{query}':"]
            for el in elements[:8]:
                name = el.get("tags", {}).get("name", "?")
                lt = el.get("lat", el.get("center", {}).get("lat", "?"))
                ln = el.get("lon", el.get("center", {}).get("lon", "?"))
                lines.append(f"  {name} ({lt}, {ln})")
            return "\n".join(lines)

        else:
            return ("Verfügbare Aktionen: geocode, directions, distance, search. "
                    "Parameter: action, address, from, to, query, lat, lng, radius")

    except Exception as e:
        return f"Fehler bei Maps-Abfrage: {e}"
