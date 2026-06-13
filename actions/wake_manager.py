import json, os, sys, threading, time, subprocess, platform, shutil, tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
WAKE_CONFIG_FILE = CONFIG_DIR / "wake_config.json"

_DEFAULT_CONFIG = {
    "clap_enabled": True,
    "clap_sensitivity": 7.0,
    "spotify_uri": "https://open.spotify.com/track/39shmbIHICJ2Wxnk1fPSdz?si=2900c75c2e2d4b82",
    "open_claude": True,
    "claude_url": "https://claude.ai/new",
    "claude_monitor": 1,
    "open_binance": True,
    "binance_url": "https://www.binance.com/en/trade/BTC_USDT",
    "binance_monitor": 3,
    "open_cursor": True,
    "cursor_fullscreen": True,
    "welcome_enabled": True,
    "welcome_phrase": "Welcome home sir. How was your day?",
    "chrome_fullscreen": True,
}

def _load_config() -> dict:
    if WAKE_CONFIG_FILE.exists():
        try:
            return {**_DEFAULT_CONFIG, **json.loads(WAKE_CONFIG_FILE.read_text(encoding="utf-8"))}
        except:
            pass
    return dict(_DEFAULT_CONFIG)

def _save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WAKE_CONFIG_FILE.write_text(json.dumps(cfg, indent=4), encoding="utf-8")


def open_url(url: str) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(url)
        else:
            import webbrowser
            webbrowser.open(url)
        return True
    except:
        return False


def open_spotify(uri: str = None) -> bool:
    cfg = _load_config()
    uri = uri or cfg.get("spotify_uri", "")
    if not uri:
        return False
    return open_url(uri)


def _chrome_exe() -> str | None:
    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            p = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(p):
                return p
    return shutil.which("google-chrome") or shutil.which("chrome")


def _get_monitor_rects() -> list[tuple[int, int, int, int]]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    collected = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
    def _cb(_hm, _hdc, lprc, _lp):
        r = lprc.contents
        collected.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None, None, _cb, 0)
    collected.sort(key=lambda t: (t[0], t[1]))
    return collected


def _get_chrome_hwnds() -> set[int]:
    if sys.platform != "win32":
        return set()
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    found = set()
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lp):
        if user32.GetWindow(hwnd, 4):
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x00000080:
            return True
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        hproc = kernel32.OpenProcess(0x1000, False, pid.value)
        if not hproc:
            return True
        try:
            buf = ctypes.create_unicode_buffer(4096)
            sz = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(sz)):
                return True
            if os.path.basename(buf.value).lower() != "chrome.exe":
                return True
        finally:
            kernel32.CloseHandle(hproc)
        r = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            if r.right - r.left < 80 or r.bottom - r.top < 80:
                return True
        found.add(int(hwnd))
        return True
    user32.EnumWindows(_enum, 0)
    return found


def open_chrome_url(url: str, monitor: int = 1, fullscreen: bool = True):
    chrome = _chrome_exe()
    if not chrome:
        open_url(url)
        return
    rects = _get_monitor_rects()
    if not rects:
        open_url(url)
        return
    idx = min(monitor - 1, len(rects) - 1)
    ml, mt, mr, mb = rects[idx]
    before = _get_chrome_hwnds()
    try:
        subprocess.Popen(
            [chrome, "--new-window", url,
             f"--window-position={ml},{mt}",
             f"--window-size={mr-ml},{mb-mt}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
    except:
        open_url(url)
        return
    if fullscreen and sys.platform == "win32":
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            time.sleep(0.2)
            now = _get_chrome_hwnds()
            new = now - before
            if new:
                import ctypes
                hwnd = ctypes.c_void_p(max(new))
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetWindowPos(hwnd, 0, ml, mt, mr-ml, mb-mt, 0x0040|0x0020)
                ctypes.windll.user32.ShowWindow(hwnd, 3)
                fg = ctypes.windll.user32.GetForegroundWindow()
                ctypes.windll.user32.AttachThreadInput(
                    ctypes.windll.user32.GetWindowThreadProcessId(fg, None),
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None), True)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                ctypes.windll.user32.keybd_event(0x7A, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x7A, 0, 2, 0)
                break


def _cursor_exe() -> str | None:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        for sub in ("Programs\\cursor\\Cursor.exe", "Programs\\Cursor\\Cursor.exe"):
            p = os.path.join(local, sub)
            if os.path.isfile(p):
                return p
    return shutil.which("cursor")


def _cursor_hwnd() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    best, best_area = None, 0
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lp):
        nonlocal best, best_area
        if user32.GetWindow(hwnd, 4):
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x00000080:
            return True
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        hproc = kernel32.OpenProcess(0x1000, False, pid.value)
        if not hproc:
            return True
        try:
            buf = ctypes.create_unicode_buffer(4096)
            sz = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(sz)):
                return True
            if os.path.basename(buf.value).lower() != "cursor.exe":
                return True
        finally:
            kernel32.CloseHandle(hproc)
        r = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            a = max(0, r.right - r.left) * max(0, r.bottom - r.top)
            if a > best_area:
                best_area = a
                best = int(hwnd)
        return True
    user32.EnumWindows(_enum, 0)
    return best


def focus_cursor() -> bool:
    if sys.platform != "win32":
        exe = _cursor_exe()
        if exe:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False
    hwnd = _cursor_hwnd()
    if hwnd is None:
        exe = _cursor_exe()
        if exe:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(1)
            hwnd = _cursor_hwnd()
    if hwnd is not None:
        import ctypes
        cfg = _load_config()
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        fg = user32.GetForegroundWindow()
        user32.AttachThreadInput(
            user32.GetWindowThreadProcessId(fg, None),
            user32.GetWindowThreadProcessId(hwnd, None), True)
        user32.SetForegroundWindow(hwnd)
        if cfg.get("cursor_fullscreen", True):
            time.sleep(0.3)
            user32.keybd_event(0x7A, 0, 0, 0)
            user32.keybd_event(0x7A, 0, 2, 0)
        return True
    return False


def run_morning_routine(config: dict = None) -> str:
    cfg = {**_load_config(), **(config or {})}
    log = []
    spotify = cfg.get("spotify_uri", "")
    if spotify:
        ok = open_spotify(spotify)
        log.append(f"Spotify: {'gestartet' if ok else 'fehlgeschlagen'}")
        time.sleep(1)
    if cfg.get("open_claude"):
        open_chrome_url(cfg.get("claude_url", "https://claude.ai/new"),
                        cfg.get("claude_monitor", 1),
                        cfg.get("chrome_fullscreen", True))
        log.append("Claude geöffnet")
    if cfg.get("open_binance"):
        open_chrome_url(cfg.get("binance_url", "https://www.binance.com/en/trade/BTC_USDT"),
                        cfg.get("binance_monitor", 3),
                        cfg.get("chrome_fullscreen", True))
        log.append("Binance geöffnet")
    if cfg.get("open_cursor"):
        ok = focus_cursor()
        log.append(f"Cursor: {'fokussiert' if ok else 'gestartet'}")
    return "Morgen-Routine: " + ", ".join(log)


# ─── Clap Detection ─────────────────────────────────────────────

_CLAP_CALLBACK = None
_CLAP_RUNNING = False

def _clap_detect_loop(sensitivity: float = 7.0, callback=None):
    global _CLAP_RUNNING
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        print("[WAKE] ⚠️ numpy/sounddevice nicht installiert — Clap-Erkennung deaktiviert")
        return
    _CLAP_RUNNING = True
    SAMPLE_RATE = 44100
    BLOCK_MS = 40
    blocksize = int(SAMPLE_RATE * BLOCK_MS / 1000)
    COOLDOWN_S = 3.0
    MIN_DOUBLE_GAP_S = 0.12
    MAX_DOUBLE_GAP_S = 0.35
    SPIKE_RATIO = sensitivity
    RETRIGGER_RATIO = 0.55
    NOISE_FLOOR_ALPHA = 0.995
    MIN_RMS = 0.04
    QUIET_GATE_MULT = 3.0
    noise_floor = 1e-4
    spike_armed = True
    first_clap = None
    last_double = 0.0
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=blocksize) as stream:
            while _CLAP_RUNNING:
                data, _ = stream.read(blocksize)
                level = float(np.sqrt(np.mean(data.astype(np.float64)**2)))
                quiet_gate = noise_floor * QUIET_GATE_MULT
                if level < quiet_gate:
                    noise_floor = NOISE_FLOOR_ALPHA * noise_floor + (1 - NOISE_FLOOR_ALPHA) * level
                    noise_floor = max(noise_floor, 1e-7)
                threshold = max(noise_floor * SPIKE_RATIO, MIN_RMS)
                now = time.monotonic()
                if level < threshold * RETRIGGER_RATIO:
                    spike_armed = True
                if spike_armed and level >= threshold and (now - last_double) >= COOLDOWN_S:
                    spike_armed = False
                    if first_clap is None:
                        first_clap = now
                    else:
                        gap = now - first_clap
                        first_clap = None
                        if MIN_DOUBLE_GAP_S <= gap <= MAX_DOUBLE_GAP_S:
                            last_double = now
                            print(f"[WAKE] 👏 Double-Clap erkannt (gap={gap:.3f}s)")
                            if callback:
                                try:
                                    callback()
                                except:
                                    pass
    except Exception as e:
        print(f"[WAKE] ⚠️ Clap-Detection-Fehler: {e}")
    finally:
        _CLAP_RUNNING = False

def start_clap_detection(sensitivity: float = None, callback=None):
    global _CLAP_RUNNING
    if _CLAP_RUNNING:
        print("[WAKE] Clap-Erkennung läuft bereits")
        return False
    if sensitivity is None:
        cfg = _load_config()
        sensitivity = cfg.get("clap_sensitivity", 7.0)
    _CLAP_CALLBACK = callback
    t = threading.Thread(target=_clap_detect_loop, args=(sensitivity, callback), daemon=True)
    t.start()
    print(f"[WAKE] 👂 Clap-Erkennung gestartet (sensitivity={sensitivity})")
    return True

def stop_clap_detection():
    global _CLAP_RUNNING
    _CLAP_RUNNING = False
    print("[WAKE] Clap-Erkennung gestoppt")

def is_clap_running() -> bool:
    return _CLAP_RUNNING
