import requests
from datetime import datetime

def weather_action(parameters: dict, player=None, session_memory=None):
    city = parameters.get("city", "").strip()
    days = int(parameters.get("days", 1))
    if not city:
        city = _get_home_location()
    if not city:
        return "Keine Stadt angegeben. Bitte Ort in den Einstellungen festlegen oder direkt angeben."

    try:
        # 1. Geocode city → coordinates via OpenStreetMap
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "de", "format": "json"},
            timeout=8,
        )
        geo.raise_for_status()
        geo_data = geo.json()
        results = geo_data.get("results")
        if not results:
            return f"Konnte '{city}' nicht finden."
        r = results[0]
        lat, lon = r["latitude"], r["longitude"]
        name = r.get("name", city)
        country = r.get("country", "")

        # 2. Fetch weather from Open-Meteo (kein API-Key nötig)
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
            "forecast_days": min(days, 7),
        }
        wx = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=8)
        wx.raise_for_status()
        w = wx.json()
        current = w.get("current", {})
        daily = w.get("daily", {})

        lines = [f"Wetter für {name}{', ' + country if country else ''}:"]

        if current:
            temp = current.get("temperature_2m")
            feels = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            code = current.get("weather_code", 0)
            wind = current.get("wind_speed_10m")
            weather_desc = _wmo_code(code)
            parts = [f"{weather_desc}, {temp:.0f}°C (gefühlt {feels:.0f}°C)"]
            if humidity:
                parts.append(f"Luftfeuchte: {humidity}%")
            if wind:
                parts.append(f"Wind: {wind:.0f} km/h")
            lines.append("Aktuell: " + " | ".join(parts))
        else:
            lines.append("Keine aktuellen Daten.")

        # forecast
        if daily and daily.get("time"):
            lines.append("")
            lines.append("Vorhersage:")
            for i in range(len(daily["time"])):
                date = daily["time"][i]
                wc = daily["weather_code"][i] if daily.get("weather_code") else 0
                t_max = daily["temperature_2m_max"][i] if daily.get("temperature_2m_max") else "?"
                t_min = daily["temperature_2m_min"][i] if daily.get("temperature_2m_min") else "?"
                precip = daily["precipitation_sum"][i] if daily.get("precipitation_sum") else 0
                day_name = _day_name(date)
                lines.append(f"  {day_name}: {_wmo_code(wc)}, {t_max:.0f}/{t_min:.0f}°C, {precip:.0f}mm Regen")

        msg = "\n".join(lines)
        if player:
            player.write_log(f"JARVIS:\n{msg}")
        return msg

    except requests.RequestException as e:
        return f"Wetter-Fehler: {e}"
    except Exception as e:
        return f"Wetter-Fehler: {e}"

def _wmo_code(code: int) -> str:
    codes = {
        0: "☀️ Klar", 1: "🌤 Überwiegend klar", 2: "⛅ Teilweise bewölkt", 3: "☁️ Bewölkt",
        45: "🌫 Nebel", 48: "🌫 Reifnebel",
        51: "🌧 Nieselregen", 53: "🌧 Nieselregen", 55: "🌧 Nieselregen",
        56: "🌧 Eisregen", 57: "🌧 Eisregen",
        61: "🌧 Regen", 63: "🌧 Regen", 65: "🌧 Regen",
        66: "🌧 Eisregen", 67: "🌧 Eisregen",
        71: "🌨 Schneefall", 73: "🌨 Schneefall", 75: "🌨 Schneefall",
        77: "🌨 Schneekörner",
        80: "🌦 Regenschauer", 81: "🌦 Regenschauer", 82: "🌦 Regenschauer",
        85: "🌨 Schneeschauer", 86: "🌨 Schneeschauer",
        95: "⛈ Gewitter", 96: "⛈ Gewitter mit Hagel", 99: "⛈ Gewitter mit Hagel",
    }
    return codes.get(code, f"Unbekannt ({code})")

def _day_name(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        return days[dt.weekday()]
    except:
        return date_str

def _get_home_location() -> str:
    try:
        import json, os, sys
        p = Path(__file__).resolve().parent.parent / "config" / "settings.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("home_location", "")
    except:
        pass
    return ""
