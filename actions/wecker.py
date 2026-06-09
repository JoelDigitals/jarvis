import json, os, sys, threading, time
from pathlib import Path
from datetime import datetime, timedelta

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

MUSIC_DIR = _base_dir() / "music"
ALARM_FILE = _base_dir() / "config" / "alarm.json"

def _load_alarms() -> list:
    try:
        if ALARM_FILE.exists():
            return json.loads(ALARM_FILE.read_text(encoding="utf-8"))
    except: pass
    return []

def _save_alarms(alarms: list):
    ALARM_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALARM_FILE.write_text(json.dumps(alarms, indent=4), encoding="utf-8")

def _find_music() -> list[Path]:
    if not MUSIC_DIR.exists():
        return []
    exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
    return sorted([f for f in MUSIC_DIR.iterdir() if f.suffix.lower() in exts])

def _play_music_file(path: Path):
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play()
    except ImportError:
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(str(path), winsound.SND_ASYNC)
        except:
            pass

def _stop_music():
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except:
        pass

_alarm_threads = []

def wecker(parameters: dict = None, player=None, session_memory=None) -> str:
    action = (parameters or {}).get("action", "status").strip().lower()
    if action == "set":
        time_str = parameters.get("time", "").strip()
        if not time_str:
            return "Bitte eine Uhrzeit angeben (z.B. 07:00)."
        music = parameters.get("music", "").strip()
        alarms = _load_alarms()
        alarm = {"time": time_str, "music": music, "active": True, "id": len(alarms) + 1}
        alarms.append(alarm)
        _save_alarms(alarms)
        _schedule_alarm(alarm)
        return f"Wecker auf {time_str} gestellt."

    elif action == "list":
        alarms = _load_alarms()
        if not alarms:
            return "Keine Wecker gesetzt."
        lines = ["Wecker:"]
        for a in alarms:
            status = "✅" if a.get("active") else "❌"
            music = f" ({a.get('music','Standard')})" if a.get("music") else ""
            lines.append(f"  {status} {a['time']}{music}")
        return "\n".join(lines)

    elif action == "remove":
        alarm_id = int(parameters.get("id", 0))
        alarms = _load_alarms()
        alarms = [a for a in alarms if a.get("id") != alarm_id]
        _save_alarms(alarms)
        return f"Wecker {alarm_id} entfernt."

    elif action == "play":
        songs = _find_music()
        if not songs:
            return "Keine Musikdateien im music/-Ordner gefunden."
        _play_music_file(songs[0])
        return f"Spiele {songs[0].name}."

    elif action == "stop":
        _stop_music()
        _stop_radio()
        return "Musik gestoppt."

    elif action == "radio":
        station = (parameters.get("music") or "sr1").strip().lower()
        STATIONS = {
            "sr1":        "https://liveradio.sr.de/sr/sr1/mp3/128/stream.mp3",
            "sr1wie":     "https://sr.audiostream.io/sr/1013/mp3/128/stream.mp3",
            "sr3":        "https://liveradio.sr.de/sr/sr3/mp3/128/stream.mp3",
            "sr kultur":  "https://liveradio.sr.de/sr/srkultur/mp3/128/stream.mp3",
            "swr1":       "https://liveradio.swr.de/sw282p3/swr1bw/128.mp3",
            "swr3":       "https://liveradio.swr.de/sw282p3/swr3/128.mp3",
            "1live":      "https://wdr-1live-live.icecastssl.wdr.de/wdr/1live/live/mp3/128/stream.mp3",
            "wdr2":       "https://wdr-wdr2-live.icecastssl.wdr.de/wdr/wdr2/live/mp3/128/stream.mp3",
            "deutschlandfunk": "https://st01.sslstream.dlf.de/dlf/01/high/aac/stream.aac",
        }
        url = STATIONS.get(station)
        if not url:
            return f"Unbekannter Sender. Verfügbar: {', '.join(STATIONS.keys())}"
        return _play_radio(url)

    alarms = _load_alarms()
    if alarms:
        times = ", ".join(a["time"] for a in alarms if a.get("active"))
        return f"Wecker aktiv: {times}."
    return "Keine Wecker."

_RADIO_PROCESS: "subprocess.Popen | None" = None

def _play_radio(url: str) -> str:
    global _RADIO_PROCESS
    _stop_radio()
    import subprocess
    import os
    # mehrere mögliche VLC-Pfade durchprobieren
    vlc_candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files\VLC\vlc.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\VLC\vlc.exe"),
        os.path.expandvars(r"%APPDATA%\VLC\vlc.exe"),
    ]
    for vlc_path in vlc_candidates:
        if not os.path.isfile(vlc_path):
            continue
        try:
            _RADIO_PROCESS = subprocess.Popen(
                [vlc_path, "--intf", "dummy", "--no-video", "--no-volume-save", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            import time
            time.sleep(0.5)
            if _RADIO_PROCESS.poll() is not None:
                continue
            return f"Radio gestartet."
        except Exception:
            continue
    # VLC nicht gefunden → Browser-Fallback
    try:
        import webbrowser
        webbrowser.open(url)
        return f"Radio im Browser geöffnet."
    except:
        return f"Radio-Fehler: VLC nicht gefunden und Browser-Fallback fehlgeschlagen."

def _stop_radio():
    global _RADIO_PROCESS
    if _RADIO_PROCESS:
        try:
            _RADIO_PROCESS.terminate()
            _RADIO_PROCESS.wait(timeout=3)
        except:
            pass
        _RADIO_PROCESS = None

def _schedule_alarm(alarm: dict):
    def _fire():
        while True:
            now = datetime.now()
            try:
                h, m = alarm["time"].split(":")
                target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            except:
                return
            if target <= now:
                target += timedelta(days=1)
            delay = (target - now).total_seconds()
            time.sleep(delay)
            songs = _find_music()
            if songs:
                wanted = alarm.get("music", "").strip().lower()
                to_play = None
                if wanted:
                    for s in songs:
                        if wanted in s.stem.lower():
                            to_play = s
                            break
                if not to_play and songs:
                    to_play = songs[0]
                if to_play:
                    _play_music_file(to_play)
            if not alarm.get("repeat", True):
                alarm["active"] = False
                _save_alarms(_load_alarms())
    t = threading.Thread(target=_fire, daemon=True)
    t.start()
    _alarm_threads.append(t)

def schedule_all():
    for a in _load_alarms():
        if a.get("active"):
            _schedule_alarm(a)

def play_wakeup_music():
    songs = _find_music()
    if songs:
        _play_music_file(songs[0])
        return True
    return False
