from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1100, 740
_MIN_W,     _MIN_H     = 900, 620
_LEFT_W  = 170
_RIGHT_W = 360

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#0d1117"
    PANEL     = "#161b22"
    PANEL2    = "#1c2333"
    BORDER    = "#21262d"
    BORDER_B  = "#30363d"
    BORDER_A  = "#58a6ff"
    PRI       = "#58a6ff"
    PRI_DIM   = "#1f6feb"
    PRI_GHO   = "#0d2d6b"
    ACC       = "#f0883e"
    ACC2      = "#d29922"
    GREEN     = "#3fb950"
    GREEN_D   = "#238636"
    RED       = "#da3633"
    MUTED_C   = "#f85149"
    TEXT      = "#e6edf3"
    TEXT_DIM  = "#8b949e"
    TEXT_MED  = "#7d8590"
    WHITE     = "#f0f6fc"
    DARK      = "#010409"
    BAR_BG    = "#21262d"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._gpu_cache_time = 0.0
        self._gpu_available = True
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(10.0)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        # GPU check nur alle 60s, und ganz skipen wenn nicht verfügbar
        if self._gpu_available and now - self._gpu_cache_time > 60:
            gpu = self._get_gpu()
            self._gpu_cache_time = now
            if gpu < 0:
                self._gpu_available = False  # kein GPU-Tool gefunden -> nie wieder probieren
        else:
            gpu = self.gpu

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._muted    = False
        self._speaking = False
        self.state    = "INITIALISING"

        self._face_px: QPixmap | None = None
        self._face_cache: dict[int, QPixmap] = {}
        self._backing   = QPixmap()
        self._backing_dirty = True
        self._load_face(face_path)

        self._glow_tmr = QTimer(self)
        self._glow_tmr.timeout.connect(self._on_glow_tick)
        self._glow_tmr.setSingleShot(False)

    def _on_glow_tick(self):
        self.update()
        # dynamic timer: faster when active, slower when idle
        active = self._speaking or self._muted or self.state in ("THINKING", "PROCESSING")
        self._glow_tmr.setInterval(60 if active else 250)

    @property
    def muted(self):
        return self._muted

    @muted.setter
    def muted(self, v):
        if self._muted != v:
            self._muted = v
            if v:
                self._glow_tmr.start(60)
            self.update()

    @property
    def speaking(self):
        return self._speaking

    @speaking.setter
    def speaking(self, v):
        if self._speaking != v:
            self._speaking = v
            if v:
                self._glow_tmr.start(60)
            self.update()

    def set_state(self, s):
        self.state = s
        if s in ("THINKING", "PROCESSING"):
            self._glow_tmr.start(60)
        self.update()

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None
        self._backing_dirty = True
        self.update()

    def resizeEvent(self, ev):
        self._backing_dirty = True
        super().resizeEvent(ev)

    def _render_backing(self):
        W, H = self.width(), self.height()
        if W < 1 or H < 1:
            return
        if self._backing.size() != self.size():
            self._backing = QPixmap(W, H)
        p = QPainter(self._backing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = QColor(C.BG)
        grad = QRadialGradient(W / 2, H / 2, min(W, H) * 0.5)
        grad.setColorAt(0.0, qcol("#0d1117", 255))
        grad.setColorAt(0.8, qcol("#0d1117", 255))
        grad.setColorAt(1.0, qcol("#010409", 255))
        p.fillRect(0, 0, W, H, grad)

        cx, cy = W / 2, H / 2
        fw = min(W, H)

        if self._face_px:
            fsz = int(fw * 0.62)
            cached = self._face_cache.get(fsz)
            if cached is None:
                self._face_cache.clear()
                cached = self._face_px.scaled(
                    fsz, fsz, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._face_cache[fsz] = cached
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), cached)
        else:
            p.setPen(QPen(qcol(C.PRI, 60), 1))
            p.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "JARVIS")

        p.end()
        self._backing_dirty = False

    def _glow_color(self) -> tuple[QColor, QColor]:
        if self._muted:
            return qcol(C.MUTED_C, 30), qcol(C.MUTED_C, 8)
        if self._speaking:
            t = time.monotonic()
            pulse = 0.5 + 0.5 * math.sin(t * 3.0)
            return qcol(C.ACC, int(20 + 30 * pulse)), qcol(C.ACC, int(5 + 10 * pulse))
        if self.state in ("THINKING", "PROCESSING"):
            t = time.monotonic()
            pulse = 0.5 + 0.5 * math.sin(t * 2.0)
            return qcol(C.ACC2, int(10 + 25 * pulse)), qcol(C.ACC2, int(3 + 8 * pulse))
        if self.state == "LISTENING":
            t = time.monotonic()
            pulse = 0.5 + 0.5 * math.sin(t * 2.5)
            return qcol(C.GREEN, int(10 + 25 * pulse)), qcol(C.GREEN, int(3 + 8 * pulse))
        return qcol(C.PRI, 15), qcol(C.PRI, 5)

    def paintEvent(self, _):
        if self._backing_dirty or self._backing.size() != self.size():
            self._render_backing()

        p = QPainter(self)
        p.drawPixmap(0, 0, self._backing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        t = time.monotonic()

        # ── glow rings ──
        glow_a, glow_b = self._glow_color()
        ring_r = fw * 0.34
        for i, (col, w) in enumerate([(glow_a, 6), (glow_b, 12)]):
            if col.alpha() > 2:
                p.setPen(QPen(col, w))
                p.drawEllipse(QPointF(cx, cy), ring_r + i * 4, ring_r + i * 4)

        # ── outer ring ──
        p.setPen(QPen(qcol(C.BORDER_B, 80), int(fw * 0.01) + 1))
        p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        # ── status label ──
        blink_on = (int(t * 2) % 12) < 6
        sy = cy + fw * 0.40
        if self._muted:
            txt, col = "⊘  STUMM",     qcol(C.MUTED_C)
        elif self._speaking:
            txt, col = "●  SPRECHE",    qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if blink_on else "◇"
            txt, col = f"{sym}  DENKE",    qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if blink_on else "▶"
            txt, col = f"{sym}  ARBEITE",  qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if blink_on else "○"
            txt, col = f"{sym}  HÖRE",     qcol(C.GREEN)
        else:
            sym = "●" if blink_on else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)


class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 3, W - 6, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("du:") or tl.startswith("you:"):  self._tag = "you"
        elif tl.startswith("jarvis:"):                        self._tag = "ai"
        elif tl.startswith("datei:") or tl.startswith("file:"): self._tag = "file"
        elif "err" in tl or "fehler" in tl:                     self._tag = "err"
        else:                                                   self._tag = "sys"
        self._tmr.start(25)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.setSingleShot(False)
        self._anim_tmr.stop()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def _start_anim(self):
        if not self._anim_tmr.isActive():
            self._anim_tmr.start(100)

    def _stop_anim(self):
        self._anim_tmr.stop()
        self._dash_offset = 0.0
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            self._start_anim()
            self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        self._stop_anim()
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True
        self._start_anim()
        self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False
        self._stop_anim()
        self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Consolas", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Datei hier ablegen  oder  Klicken zum Durchsuchen")
        p.setFont(QFont("Consolas", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Bilder · Video · Audio · PDF · Docs · Code · Daten")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Consolas", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Loslassen zum Laden")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Consolas", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Consolas", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Consolas", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("INITIALISIERUNG ERFORDERLICH", 13, True))
        layout.addWidget(_lbl("JARVIS vor dem ersten Start konfigurieren.", 9, color=C.TEXT_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API SCHLÜSSEL", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Consolas", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(8)

        layout.addWidget(_lbl("OPENROUTER API SCHLÜSSEL", 8, color=C.TEXT_DIM,
                       align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = QLineEdit()
        self._or_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_input.setPlaceholderText("sk-or-…")
        self._or_input.setFont(QFont("Consolas", 10))
        self._or_input.setFixedHeight(32)
        self._or_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACC2}; }}
        """)
        layout.addWidget(self._or_input)

        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("BETRIEBSSYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-erkannt: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  SYSTEME INITIALISIEREN")
        init_btn.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        if not or_key:
            self._or_input.setStyleSheet(
                self._or_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, or_key, self._sel_os)


class _SectionCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _SectionCard {{
                background: rgba(13, 17, 23, 200);
                border: 1px solid {C.BORDER}; border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(6)

        hdr = QHBoxLayout(); hdr.setSpacing(8)
        hl = QLabel(title)
        hl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        hl.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 2px;")
        hdr.addWidget(hl)
        if subtitle:
            sl = QLabel(subtitle)
            sl.setFont(QFont("Consolas", 7))
            sl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            hdr.addWidget(sl)
        hdr.addStretch()
        lay.addLayout(hdr)
        self._lay = lay

    def add_widget(self, w):
        self._lay.addWidget(w)

    def add_layout(self, l):
        self._lay.addLayout(l)

    def add_spacing(self, px=4):
        self._lay.addSpacing(px)


class SettingsOverlay(QWidget):
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SettingsOverlay {{
                background: rgba(22, 27, 34, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        from config.settings import load
        cfg = load()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ── header ──
        hdr = QHBoxLayout(); hdr.setContentsMargins(18, 10, 12, 4)
        title = QLabel("EINSTELLUNGEN")
        title.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent; letter-spacing: 3px;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.RED};
                border: 1px solid {C.RED}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.RED}22; }}
        """)
        close_btn.clicked.connect(self.close)
        hdr.addWidget(close_btn)
        main_layout.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); main_layout.addWidget(sep)

        # ── helpers ──
        def _inp(ph="", val="", h=28):
            e = QLineEdit(val)
            e.setPlaceholderText(ph)
            e.setFont(QFont("Consolas", 10))
            e.setFixedHeight(h)
            e.setStyleSheet(f"""
                QLineEdit {{ background: #000d12; color: {C.TEXT};
                    border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px; }}
                QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
                QLineEdit:disabled {{ color: {C.TEXT_DIM}; }}
            """)
            return e

        def _btn(txt, color=C.PRI, h=28):
            b = QPushButton(txt)
            b.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            b.setFixedHeight(h)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {color};
                    border: 1px solid {color}; border-radius: 3px; }}
                QPushButton:hover {{ background: {color}22; }}
            """)
            return b

        def _cb(txt, checked=False):
            c = QCheckBox(txt)
            c.setChecked(checked)
            c.setFont(QFont("Consolas", 9))
            c.setStyleSheet(f"""
                QCheckBox {{ color: {C.TEXT}; background: transparent; spacing: 8px; }}
                QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {C.BORDER};
                    border-radius: 2px; background: #000d12; }}
                QCheckBox::indicator:checked {{ background: {C.PRI}; border: 1px solid {C.PRI}; }}
            """)
            return c

        # ── scroll area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        c = QWidget()
        c.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(c)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        # ════════════════════════════════════
        # 1  PERSON
        # ════════════════════════════════════
        card = _SectionCard("PERSON", "Anrede, Standort")
        self._name_inp = _inp("Anrede / Name (z.B. Sir, Joel)", cfg.get("user_name", "Sir"))
        card.add_widget(self._name_inp)
        self._loc_inp = _inp("Wohnort (z.B. Lebach, Deutschland)", cfg.get("home_location", ""))
        card.add_widget(self._loc_inp)
        lay.addWidget(card)

        # ════════════════════════════════════
        # 2  E-MAIL
        # ════════════════════════════════════
        card = _SectionCard("E-MAIL", "Konten + täglicher Bericht")
        self._email_layout = QVBoxLayout(); self._email_layout.setSpacing(4)
        self._email_rows = []
        accounts = cfg.get("email_accounts", [])
        for acct in (accounts if accounts else [{}]):
            self._add_email_row(
                acct.get("name",""), acct.get("email",""), acct.get("password",""),
                acct.get("imap_server","imap.gmail.com"), acct.get("smtp_server","smtp.gmail.com"),
                str(acct.get("smtp_port", 587))
            )
        card.add_layout(self._email_layout)
        add_em = _btn("+ E-Mail-Konto", C.GREEN)
        add_em.clicked.connect(lambda: self._add_email_row("","","","","","587"))
        card.add_widget(add_em)
        card.add_spacing(4)

        # daily report sub-section
        dr = cfg.get("daily_report", {})
        self._dr_enabled = _cb("Täglichen E-Mail-Bericht senden", dr.get("enabled", True))
        card.add_widget(self._dr_enabled)

        dr_row = QHBoxLayout(); dr_row.setSpacing(6)
        self._dr_recipient = _inp("Empfänger (E-Mail)", dr.get("recipient_email", ""))
        dr_row.addWidget(self._dr_recipient, stretch=3)
        self._dr_times = _inp("Zeiten (z.B. 08:00 13:00 18:00 23:00)",
                              " ".join(dr.get("times", ["08:00","13:00","18:00","23:00"])))
        dr_row.addWidget(self._dr_times, stretch=2)
        card.add_layout(dr_row)

        incl_row = QHBoxLayout(); incl_row.setSpacing(12)
        self._dr_inc_dash = _cb("Dashboard", dr.get("include_dashboard", True))
        self._dr_inc_wthr = _cb("Wetter", dr.get("include_weather", True))
        self._dr_inc_eml = _cb("E-Mails", dr.get("include_emails", True))
        incl_row.addWidget(self._dr_inc_dash)
        incl_row.addWidget(self._dr_inc_wthr)
        incl_row.addWidget(self._dr_inc_eml)
        incl_row.addStretch()
        card.add_layout(incl_row)
        self._email_forward_to = _inp("Weiterleitung (eingehende Mails im Autopilot)", cfg.get("email_forward_to", ""))
        card.add_widget(self._email_forward_to)
        card.add_spacing(4)
        self._default_sender = _inp("Standard-Absender (Name des E-Mail-Kontos)", cfg.get("default_sender", ""))
        card.add_widget(self._default_sender)
        lay.addWidget(card)

        # ════════════════════════════════════
        # 3  ADMIN-API + JDS
        # ════════════════════════════════════
        card = _SectionCard("JOEL-DIGITALS.DE", "Admin-API + JDS CRM")
        self._admin_secret = _inp("Admin-API-Secret", cfg.get("admin_api_secret", ""))
        self._admin_secret.setEchoMode(QLineEdit.EchoMode.Password)
        card.add_widget(self._admin_secret)

        jds_cfg = cfg.get("jds_config", {})
        self._jds_url = _inp("JDS Basis-URL", jds_cfg.get("base_url", ""))
        jds_r = QHBoxLayout(); jds_r.setSpacing(6)
        self._jds_team = _inp("Team-Code", jds_cfg.get("team_code", ""))
        self._jds_token = _inp("API-Token", jds_cfg.get("api_token", ""))
        self._jds_token.setEchoMode(QLineEdit.EchoMode.Password)
        jds_r.addWidget(self._jds_team, stretch=1)
        jds_r.addWidget(self._jds_token, stretch=2)
        card.add_widget(self._jds_url)
        card.add_layout(jds_r)
        self._jds_task_user = _inp("JDS User-ID für JARVIS-Aufgaben", jds_cfg.get("task_user_id", ""))
        card.add_widget(self._jds_task_user)
        lay.addWidget(card)

        # ════════════════════════════════════
        # 4  DISCORD
        # ════════════════════════════════════
        card = _SectionCard("DISCORD", "Bot-Integration")
        disc = cfg.get("discord_config", {})
        self._discord_token = _inp("Bot-Token", disc.get("bot_token", ""))
        self._discord_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._discord_channels = _inp("Kanal-IDs (Leerzeichen-getrennt)",
                                       " ".join(disc.get("allowed_channels", [])))
        card.add_widget(self._discord_token)
        card.add_widget(self._discord_channels)
        lay.addWidget(card)

        # ════════════════════════════════════
        # 5  WISSENSSEITEN
        # ════════════════════════════════════
        card = _SectionCard("WISSENSSEITEN", "Domains + Logins zum Durchsuchen")
        self._site_layout = QVBoxLayout(); self._site_layout.setSpacing(4)
        self._site_rows = []
        sites = cfg.get("knowledge_sites", [])
        for site in (sites if sites else [{}]):
            self._add_site_row(
                site.get("name",""), site.get("url",""),
                site.get("login_path",""), site.get("username",""),
                site.get("password",""), site.get("pages", [])
            )
        card.add_layout(self._site_layout)
        add_site = _btn("+ Wissensseite", C.ACC2)
        add_site.clicked.connect(lambda: self._add_site_row("","","","","",[]))
        card.add_widget(add_site)
        lay.addWidget(card)

        # ════════════════════════════════════
        # SAVE
        # ════════════════════════════════════
        save_btn = _btn("▸  SPEICHERN", C.PRI, h=34)
        save_btn.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        save_btn.clicked.connect(self._save)
        lay.addWidget(save_btn)

        scroll.setWidget(c)
        main_layout.addWidget(scroll, stretch=1)

    # ───── email helpers ─────

    def _add_email_row(self, name="", email="", password="",
                       imap="imap.gmail.com", smtp="smtp.gmail.com", port="587"):
        group = QVBoxLayout(); group.setSpacing(3)

        def _field(ph, val, w=180):
            e = QLineEdit(val)
            e.setPlaceholderText(ph)
            e.setFont(QFont("Consolas", 9))
            e.setFixedHeight(24)
            e.setStyleSheet(f"background:#000d12;color:{C.TEXT};border:1px solid {C.BORDER};border-radius:2px;padding:2px 6px;")
            return e

        row0 = QHBoxLayout(); row0.setSpacing(4)
        n = _field("Name/Label", name, 120)
        e = _field("E-Mail", email, 200)
        pw = _field("Passwort", password, 160)
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        rm = QPushButton("✕")
        rm.setFixedSize(22, 24)
        rm.setStyleSheet(f"background:transparent;color:{C.RED};border:none;")
        rm.clicked.connect(lambda: self._remove_email_group(group))
        row0.addWidget(n); row0.addWidget(e); row0.addWidget(pw); row0.addWidget(rm)
        group.addLayout(row0)

        row1 = QHBoxLayout(); row1.setSpacing(4)
        im = _field("IMAP-Server (z.B. imap.strato.de)", imap, 200)
        sm = _field("SMTP-Server (z.B. smtp.strato.de)", smtp, 200)
        sp = _field("SMTP-Port (587)", port, 70)
        row1.addWidget(im); row1.addWidget(sm); row1.addWidget(sp)
        group.addLayout(row1)

        self._email_layout.addLayout(group)
        self._email_rows.append((group, n, e, pw, im, sm, sp))

    def _remove_email_group(self, group):
        for i in range(group.count()):
            item = group.itemAt(i)
            if item:
                for j in range(item.count()):
                    w = item.itemAt(j).widget()
                    if w: w.deleteLater()
        self._email_layout.removeItem(group)
        self._email_rows = [r for r in self._email_rows if r[0] != group]

    # ───── site helpers ─────

    def _add_site_row(self, name="", url="", login_path="", username="",
                      password="", pages=None):
        group = QVBoxLayout(); group.setSpacing(3)
        pages = pages or []

        def _field(ph, val, w=200):
            e = QLineEdit(val)
            e.setPlaceholderText(ph)
            e.setFont(QFont("Consolas", 9))
            e.setFixedHeight(24)
            e.setStyleSheet(f"background:#000d12;color:{C.TEXT};border:1px solid {C.BORDER};border-radius:2px;padding:2px 6px;")
            return e

        row0 = QHBoxLayout(); row0.setSpacing(4)
        n = _field("Name (z.B. Mein Wiki)", name, 140)
        u = _field("Domain (z.B. https://example.de)", url, 240)
        r0 = QPushButton("✕"); r0.setFixedSize(22, 24)
        r0.setStyleSheet(f"background:transparent;color:{C.RED};border:none;")
        r0.clicked.connect(lambda: self._remove_site_group(group))
        row0.addWidget(n); row0.addWidget(u); row0.addWidget(r0)
        group.addLayout(row0)

        row1 = QHBoxLayout(); row1.setSpacing(4)
        lp = _field("Login-Pfad (optional: /login/)", login_path, 180)
        un = _field("Benutzername", username, 160)
        pw = _field("Passwort", password, 160)
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        row1.addWidget(lp); row1.addWidget(un); row1.addWidget(pw)
        group.addLayout(row1)

        # pages to browse
        pages_label = QLabel("SEITEN ZUM DURCHSUCHEN (pro Zeile ein Pfad, z.B. /admin/)")
        pages_label.setFont(QFont("Consolas", 8))
        pages_label.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        group.addWidget(pages_label)

        pages_edit = QLineEdit(" ".join(pages) if pages else "")
        pages_edit.setPlaceholderText("/admin/ /admin-bestellungen/ /dokumentation/")
        pages_edit.setFont(QFont("Consolas", 9))
        pages_edit.setFixedHeight(24)
        pages_edit.setStyleSheet(f"background:#000d12;color:{C.TEXT};border:1px solid {C.BORDER};border-radius:2px;padding:2px 6px;")
        group.addWidget(pages_edit)

        self._site_layout.addLayout(group)
        self._site_rows.append((group, n, u, lp, un, pw, pages_edit))

    def _remove_site_group(self, group):
        for i in range(group.count()):
            item = group.itemAt(i)
            if item:
                for j in range(item.count()):
                    w = item.itemAt(j).widget()
                    if w: w.deleteLater()
        self._site_layout.removeItem(group)
        self._site_rows = [r for r in self._site_rows if r[0] != group]

    # ───── save ─────

    def _save(self):
        from config.settings import save, load as load_settings
        cfg = load_settings()
        cfg["user_name"] = self._name_inp.text().strip() or "Sir"
        cfg["home_location"] = self._loc_inp.text().strip()
        cfg["admin_api_secret"] = self._admin_secret.text().strip()

        accounts = []
        for _, n, e, pw, im, sm, sp in self._email_rows:
            name = n.text().strip()
            email = e.text().strip()
            password = pw.text().strip()
            if name and email:
                accounts.append({
                    "name": name, "email": email,
                    "password": password,
                    "imap_server": im.text().strip() or "imap.gmail.com",
                    "smtp_server": sm.text().strip() or "smtp.gmail.com",
                    "smtp_port": int(sp.text().strip() or "587"),
                })
        cfg["email_accounts"] = accounts

        # sync first account to legacy email_config.json
        if accounts:
            a0 = accounts[0]
            from config.settings import BASE as SETTINGS_BASE
            legacy = SETTINGS_BASE / "email_config.json"
            legacy.write_text(json.dumps({
                "email": a0["email"], "password": a0["password"],
                "imap_server": a0["imap_server"],
                "smtp_server": a0["smtp_server"],
                "smtp_port": a0["smtp_port"],
            }, indent=2), encoding="utf-8")

        sites = []
        for _, n, u, lp, un, pw, pe in self._site_rows:
            name = n.text().strip()
            url = u.text().strip()
            login_path = lp.text().strip()
            username = un.text().strip()
            password = pw.text().strip()
            raw_pages = pe.text().strip()
            pages = [p.strip() for p in raw_pages.split() if p.strip()]
            if name and url:
                sites.append({
                    "name": name, "url": url.rstrip("/"),
                    "login_path": login_path, "username": username,
                    "password": password, "pages": pages,
                })
        cfg["knowledge_sites"] = sites

        # ───── JDS config ─────
        jds = {
            "base_url": self._jds_url.text().strip(),
            "team_code": self._jds_team.text().strip(),
            "api_token": self._jds_token.text().strip(),
            "task_user_id": self._jds_task_user.text().strip(),
        }
        cfg["jds_config"] = jds

        # sync JDS to legacy jds_config.json
        if jds.get("base_url"):
            from config.settings import BASE as SETTINGS_BASE
            legacy_jds = SETTINGS_BASE / "jds_config.json"
            legacy_jds.write_text(json.dumps(jds, indent=2), encoding="utf-8")

        cfg["default_sender"] = self._default_sender.text().strip()

        # ───── E-Mail forward ─────
        cfg["email_forward_to"] = self._email_forward_to.text().strip()

        # ───── Discord config ─────
        raw_channels = self._discord_channels.text().strip()
        channels = [c.strip() for c in raw_channels.split() if c.strip()]
        cfg["discord_config"] = {
            "bot_token": self._discord_token.text().strip(),
            "allowed_channels": channels,
        }

        # ───── Daily report ─────
        raw_times = self._dr_times.text().strip()
        times = [t.strip() for t in raw_times.split() if t.strip()]
        cfg["daily_report"] = {
            "enabled": self._dr_enabled.isChecked(),
            "recipient_email": self._dr_recipient.text().strip(),
            "times": times,
            "include_dashboard": self._dr_inc_dash.isChecked(),
            "include_weather": self._dr_inc_wthr.isChecked(),
            "include_emails": self._dr_inc_eml.isChecked(),
        }

        save(cfg)
        self.done.emit()
        self.close()


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("JARVIS — Joel Digitals")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(5000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 4, 14, 4)

        def _badge(txt, color, bold=False, sz=8):
            l = QLabel(txt)
            l.setFont(QFont("Consolas", sz, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            l.setStyleSheet(f"color: {color}; background: transparent; letter-spacing: 1px;")
            return l

        left = QVBoxLayout(); left.setSpacing(0)
        left.addWidget(_badge("◆ JOEL DIGITALS", C.PRI, bold=True, sz=9))
        left.addWidget(_badge("KI-ASSISTENT v2.0", C.TEXT_DIM, sz=7))
        lay.addLayout(left)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(0)
        title = QLabel("JARVIS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 3px;")
        mid.addWidget(title)
        sub = QLabel("JOEL DIGITALS · KI-ASSISTENT")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Consolas", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; letter-spacing: 2px;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        # auto-pilot indicator
        self._ap_lbl = QLabel("")
        self._ap_lbl.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        self._ap_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; letter-spacing: 1px; padding-right: 8px;")
        self._ap_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self._ap_lbl.setFixedWidth(60)
        lay.addWidget(self._ap_lbl)

        right_col = QVBoxLayout(); right_col.setSpacing(0)
        self._clock_lbl = QLabel("00:00")
        self._clock_lbl.setFont(QFont("Consolas", 20, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent; letter-spacing: 2px;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Consolas", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; letter-spacing: 1px;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.PANEL}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        # accent bar
        ab = QFrame()
        ab.setFixedHeight(2)
        ab.setStyleSheet(f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
                         f"stop:0 {C.PRI}, stop:0.5 {C.ACC}, stop:1 {C.GREEN}); "
                         f"border: none; border-radius: 1px;")
        lay.addWidget(ab)

        hdr = QLabel("SYSTEMMONITOR")
        hdr.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; "
                          f"padding-bottom: 2px; letter-spacing: 2px;")
        lay.addWidget(hdr)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("RAM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 4, 6, 4)
        ip_lay.setSpacing(2)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Consolas", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Consolas", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addStretch()

        for txt, col in [
            ("◇ KI AKTIV",    C.GREEN),
            ("◈ SICHERHEIT\n  OK",      C.PRI),
            ("◆ JOEL\n  DIGITALS",   C.ACC),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 5px 8px;"
            )
            lay.addWidget(lbl)

        lay.addSpacing(6)
        set_btn = QPushButton("⚙  EINSTELLUNGEN")
        set_btn.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        set_btn.setFixedHeight(28)
        set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.PRI_DIM};
                background: {C.PRI_GHO};}}
        """)
        set_btn.clicked.connect(self._open_settings)
        lay.addWidget(set_btn)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(txt)
            l.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; letter-spacing: 2px;")
            return l

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.Shape.HLine)
            s.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;"); return s

        lay.addWidget(_sec("LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        lay.addWidget(_sep())

        lay.addWidget(_sec("DATEI"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("Keine Datei — ablegen oder klicken")
        self._file_hint.setFont(QFont("Consolas", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        lay.addWidget(_sep())

        lay.addWidget(_sec("BEFEHL"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("🎙  MIKROFON AKTIV")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("⛶  [F11]  VOLLBILD")
        fs_btn.setFixedHeight(24)
        fs_btn.setFont(QFont("Consolas", 8))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
                background: {C.PRI_GHO};}}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(4)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Befehl oder Frage…")
        self._input.setFont(QFont("Consolas", 10))
        self._input.setFixedHeight(28)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(28, 28)
        send.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_DIM}; color: {C.WHITE};
                border: none; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Consolas", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Stumm  ·  [F11] Vollbild"))
        lay.addStretch()
        lay.addWidget(_fl("Joel Digitals  ·  JARVIS  ·  v2.0"))
        lay.addStretch()
        lay.addWidget(_fl("© JOEL DIGITALS", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Sag JARVIS was damit gemacht werden soll")
        self._log.append_log(f"DATEI: {p.name} ({size}) geladen")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _open_settings(self):
        ov = SettingsOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 600, 560
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(lambda: self._log.append_log("SYS: Einstellungen gespeichert."))
        ov.show()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Mikrofon stumm.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Mikrofon aktiv.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MIKROFON STUMM")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MIKROFON AKTIV")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"Du: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        if state == "SPEAKING":
            self.hud.speaking = True
        else:
            self.hud.set_state(state)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (bool(d.get("gemini_api_key")) and
                    bool(d.get("openrouter_api_key")) and
                    bool(d.get("os_system")))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 430
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    # Change signature:
    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({
                "gemini_api_key":    key,
                "openrouter_api_key": or_key,
                "os_system":         os_name,
            }, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialisiert. OS={os_name.upper()}. JARVIS bereit.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def set_autopilot(self, active: bool):
        self._win._ap_lbl.setText("AUTOPILOT" if active else "")